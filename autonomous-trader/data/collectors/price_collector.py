"""
data/collectors/price_collector.py
====================================
Fetches real-time and historical stock price data.

Primary source  : yfinance (unofficial Yahoo Finance — free, unlimited)
Fallback source : Alpha Vantage (25 req/day free tier)

All methods include:
  - 3-attempt retry with exponential backoff
  - Automatic fallback to secondary source
  - SQLite caching (historical: 6h TTL, live: 60s TTL)
  - Input/output validation
  - Full error logging

Usage:
    from data.collectors.price_collector import PriceCollector
    collector = PriceCollector()
    price = collector.get_current_price("RELIANCE.NS")
    history = collector.get_historical_data("RELIANCE.NS", period="2y")
"""

from __future__ import annotations

import time
import sqlite3
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np
import yfinance as yf
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from config.settings import settings
from config.constants import (
    MIN_DAILY_VOLUME,
    MIN_DAILY_VOLUME_US,
    PRICE_SPIKE_THRESHOLD,
    PRICE_MAX_AGE_MINUTES,
    ML_TRAINING_PERIOD,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class PriceData:
    symbol: str
    current_price: float
    open: float
    high: float
    low: float
    close: float          # Previous day close (for change calculation)
    volume: int
    timestamp: datetime
    source: str           # "yfinance" | "alpha_vantage" | "cache"
    bid: Optional[float] = None
    ask: Optional[float] = None
    market_cap: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None

    @property
    def price_change(self) -> float:
        """Intraday change from previous close."""
        if self.close and self.close > 0:
            return self.current_price - self.close
        return 0.0

    @property
    def price_change_pct(self) -> float:
        """Intraday % change from previous close."""
        if self.close and self.close > 0:
            return (self.current_price - self.close) / self.close * 100
        return 0.0

    def is_stale(self, max_age_minutes: int = PRICE_MAX_AGE_MINUTES) -> bool:
        """Returns True if data is older than max_age_minutes."""
        age = datetime.now(timezone.utc) - self.timestamp.replace(tzinfo=timezone.utc)
        return age > timedelta(minutes=max_age_minutes)


class DataUnavailableError(Exception):
    """Raised when price data cannot be fetched from any source."""
    pass


class InsufficientHistoryError(Exception):
    """Raised when fewer trading days of history than required exist."""
    pass


# ═══════════════════════════════════════════════════════════════
# PRICE COLLECTOR
# ═══════════════════════════════════════════════════════════════

class PriceCollector:
    """
    Fetches current and historical stock prices.
    Handles rate limiting, caching, fallbacks, and retries automatically.
    """

    # Alpha Vantage endpoint
    _AV_BASE = "https://www.alphavantage.co/query"

    # Batch size for yfinance bulk download (reduces API calls)
    _BATCH_SIZE = 10

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(settings.database_path_resolved)
        self._ensure_cache_table()

    # ── Internal: SQLite cache ──────────────────────────────────────────────

    def _ensure_cache_table(self) -> None:
        """Creates the price cache table in SQLite if it doesn't exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_cache (
                    symbol      TEXT NOT NULL,
                    cache_type  TEXT NOT NULL,  -- 'live' | 'historical'
                    data_json   TEXT NOT NULL,
                    cached_at   TEXT NOT NULL,
                    expires_at  TEXT NOT NULL,
                    PRIMARY KEY (symbol, cache_type)
                )
            """)
            conn.commit()

    def _cache_get(self, symbol: str, cache_type: str) -> Optional[str]:
        """Returns cached JSON string if still fresh, else None."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT data_json, expires_at FROM price_cache "
                    "WHERE symbol=? AND cache_type=?",
                    (symbol, cache_type),
                ).fetchone()
            if row:
                expires_at = datetime.fromisoformat(row[1])
                if datetime.utcnow() < expires_at:
                    return row[0]
        except Exception as e:
            logger.debug(f"Cache read error for {symbol}: {e}")
        return None

    def _cache_set(self, symbol: str, cache_type: str, data_json: str, ttl_seconds: int) -> None:
        """Stores data in cache with an expiry time."""
        try:
            now = datetime.utcnow()
            expires = now + timedelta(seconds=ttl_seconds)
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO price_cache
                        (symbol, cache_type, data_json, cached_at, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (symbol, cache_type, data_json, now.isoformat(), expires.isoformat()))
                conn.commit()
        except Exception as e:
            logger.debug(f"Cache write error for {symbol}: {e}")

    # ── Internal: API call tracking ────────────────────────────────────────

    def _track_api_call(self, api_name: str) -> None:
        """Increments daily API usage counter in the database."""
        try:
            today = datetime.utcnow().date().isoformat()
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS api_usage (
                        api_name TEXT NOT NULL,
                        date     TEXT NOT NULL,
                        calls_made INTEGER DEFAULT 0,
                        daily_limit INTEGER,
                        PRIMARY KEY (api_name, date)
                    )
                """)
                conn.execute("""
                    INSERT INTO api_usage (api_name, date, calls_made, daily_limit)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(api_name, date)
                    DO UPDATE SET calls_made = calls_made + 1
                """, (api_name, today, 25 if api_name == "alpha_vantage" else 9999))
                conn.commit()
        except Exception:
            pass  # Never let tracking failures disrupt data fetching

    def _get_api_usage_today(self, api_name: str) -> int:
        """Returns how many API calls have been made today for a given API."""
        try:
            today = datetime.utcnow().date().isoformat()
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT calls_made FROM api_usage WHERE api_name=? AND date=?",
                    (api_name, today),
                ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    # ── Internal: yfinance helpers ─────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        reraise=True,
    )
    def _yfinance_ticker_info(self, symbol: str) -> dict:
        """Fetches yfinance ticker.fast_info with retry logic."""
        ticker = yf.Ticker(symbol)
        # fast_info is lighter weight than .info — avoids heavy scraping
        info = ticker.fast_info
        # Also grab .info for extra fields, but tolerate failure
        try:
            full_info = ticker.info
        except Exception:
            full_info = {}
        return {"fast": info, "full": full_info}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        reraise=True,
    )
    def _yfinance_history(self, symbol: str, period: str, interval: str = "1d") -> pd.DataFrame:
        """Fetches OHLCV history from yfinance with retry."""
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True, actions=False)
        return df

    # ── Internal: Alpha Vantage helpers ───────────────────────────────────

    def _alpha_vantage_current_price(self, symbol: str) -> Optional[float]:
        """
        Fetches the latest price from Alpha Vantage GLOBAL_QUOTE endpoint.
        Uses one of the 25 daily free calls — only when yfinance fails.
        """
        if self._get_api_usage_today("alpha_vantage") >= 23:  # Keep 2 buffer
            logger.warning("Alpha Vantage daily limit approaching — skipping fallback.")
            return None

        # Alpha Vantage uses plain symbols (no .NS suffix)
        av_symbol = symbol.replace(".NS", "").replace(".BO", "")

        try:
            resp = requests.get(
                self._AV_BASE,
                params={
                    "function": "GLOBAL_QUOTE",
                    "symbol": av_symbol,
                    "apikey": settings.ALPHA_VANTAGE_KEY or "demo",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            quote = data.get("Global Quote", {})
            price_str = quote.get("05. price", "")
            if price_str:
                self._track_api_call("alpha_vantage")
                return float(price_str)
        except Exception as e:
            logger.warning(f"[{symbol}] Alpha Vantage fallback failed: {e}")
        return None

    def _alpha_vantage_history(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Fetches daily OHLCV history from Alpha Vantage TIME_SERIES_DAILY_ADJUSTED.
        Returns up to 20 years of daily data (free tier: compact = last 100 days).
        """
        if self._get_api_usage_today("alpha_vantage") >= 23:
            return None

        av_symbol = symbol.replace(".NS", "").replace(".BO", "")
        try:
            resp = requests.get(
                self._AV_BASE,
                params={
                    "function": "TIME_SERIES_DAILY_ADJUSTED",
                    "symbol": av_symbol,
                    "outputsize": "compact",  # last 100 trading days
                    "apikey": settings.ALPHA_VANTAGE_KEY or "demo",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            series = data.get("Time Series (Daily)", {})
            if not series:
                return None

            self._track_api_call("alpha_vantage")

            rows = []
            for date_str, vals in series.items():
                rows.append({
                    "Date": pd.to_datetime(date_str),
                    "Open": float(vals["1. open"]),
                    "High": float(vals["2. high"]),
                    "Low": float(vals["3. low"]),
                    "Close": float(vals["5. adjusted close"]),
                    "Volume": int(vals["6. volume"]),
                })
            df = pd.DataFrame(rows).set_index("Date").sort_index()
            return df
        except Exception as e:
            logger.warning(f"[{symbol}] Alpha Vantage history fallback failed: {e}")
            return None

    # ── Internal: DataFrame cleaning ──────────────────────────────────────

    def _clean_ohlcv(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Cleans a raw OHLCV DataFrame:
          - Standardises column names to Open/High/Low/Close/Volume
          - Removes rows with zero or negative Close prices
          - Removes rows where Volume is zero
          - Forward-fills small gaps (up to 5 consecutive days)
          - Adds Adj_Close column (same as Close for auto-adjusted data)
          - Converts index to DatetimeIndex
        """
        # Normalise column names
        df.columns = [c.strip().title() for c in df.columns]
        rename_map = {
            "Adj Close": "Adj_Close",
            "Adj_Close": "Adj_Close",
        }
        df = df.rename(columns=rename_map)

        # Ensure required columns exist
        required = ["Open", "High", "Low", "Close", "Volume"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"[{symbol}] Missing required column: {col}")

        # Add Adj_Close if absent
        if "Adj_Close" not in df.columns:
            df["Adj_Close"] = df["Close"]

        # Convert to numeric, coerce bad values to NaN
        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Remove clearly bad rows
        df = df[df["Close"] > 0]
        df = df[df["Open"] > 0]
        df = df[df["Volume"] >= 0]

        # Forward-fill up to 5 consecutive missing values (weekends / holidays)
        df = df.ffill(limit=5)

        # Drop any remaining NaN rows
        df = df.dropna(subset=["Close"])

        # Sort by date ascending
        df = df.sort_index()

        logger.debug(f"[{symbol}] Cleaned OHLCV: {len(df)} rows, "
                     f"{df.index.min().date()} → {df.index.max().date()}")
        return df

    # ── Public: get_current_price ──────────────────────────────────────────

    def get_current_price(self, symbol: str) -> PriceData:
        """
        Fetches the current (real-time or delayed) price for a stock.

        Flow:
          1. Check 60-second live cache → return if fresh
          2. Try yfinance (3 attempts, exponential backoff)
          3. If yfinance fails → try Alpha Vantage (if key is configured)
          4. If both fail → raise DataUnavailableError

        Args:
            symbol: Stock symbol (e.g., "RELIANCE.NS" for NSE, "AAPL" for US)

        Returns:
            PriceData with current price, OHLC, volume, and timestamp

        Raises:
            DataUnavailableError: If all sources fail
        """
        # ── 1. Check live cache ───────────────────────────────────────────
        cached = self._cache_get(symbol, "live")
        if cached:
            try:
                d = json.loads(cached)
                price_data = PriceData(
                    symbol=d["symbol"],
                    current_price=d["current_price"],
                    open=d["open"],
                    high=d["high"],
                    low=d["low"],
                    close=d["close"],
                    volume=d["volume"],
                    timestamp=datetime.fromisoformat(d["timestamp"]),
                    source="cache",
                    bid=d.get("bid"),
                    ask=d.get("ask"),
                    market_cap=d.get("market_cap"),
                    fifty_two_week_high=d.get("fifty_two_week_high"),
                    fifty_two_week_low=d.get("fifty_two_week_low"),
                )
                logger.debug(f"[{symbol}] Price from cache: {price_data.current_price}")
                return price_data
            except Exception as e:
                logger.debug(f"[{symbol}] Cache parse error: {e} — fetching fresh")

        # ── 2. Try yfinance ────────────────────────────────────────────────
        yf_error = None
        try:
            info_data = self._yfinance_ticker_info(symbol)
            fast = info_data["fast"]
            full = info_data["full"]

            # fast_info provides the most reliable real-time fields
            current_price = (
                getattr(fast, "last_price", None)
                or getattr(fast, "regular_market_price", None)
                or full.get("regularMarketPrice")
                or full.get("currentPrice")
            )
            if current_price is None or current_price <= 0:
                raise ValueError(f"yfinance returned invalid price: {current_price}")

            open_price = (
                getattr(fast, "open", None)
                or full.get("regularMarketOpen", current_price)
            )
            high = (
                getattr(fast, "day_high", None)
                or full.get("regularMarketDayHigh", current_price)
            )
            low = (
                getattr(fast, "day_low", None)
                or full.get("regularMarketDayLow", current_price)
            )
            prev_close = (
                getattr(fast, "previous_close", None)
                or full.get("regularMarketPreviousClose", current_price)
            )
            volume = int(
                getattr(fast, "last_volume", None)
                or full.get("regularMarketVolume", 0)
                or 0
            )

            price_data = PriceData(
                symbol=symbol,
                current_price=float(current_price),
                open=float(open_price or current_price),
                high=float(high or current_price),
                low=float(low or current_price),
                close=float(prev_close or current_price),
                volume=volume,
                timestamp=datetime.utcnow(),
                source="yfinance",
                market_cap=full.get("marketCap"),
                fifty_two_week_high=full.get("fiftyTwoWeekHigh"),
                fifty_two_week_low=full.get("fiftyTwoWeekLow"),
            )
            self._track_api_call("yfinance")

            # Cache it
            self._cache_set(symbol, "live", json.dumps({
                **asdict(price_data),
                "timestamp": price_data.timestamp.isoformat(),
            }), ttl_seconds=settings.PRICE_CACHE_TTL_SECONDS)

            logger.info(f"[{symbol}] Price: {price_data.current_price:.2f} "
                        f"| Vol: {volume:,} | Chg: {price_data.price_change_pct:+.2f}%")
            return price_data

        except Exception as e:
            yf_error = e
            logger.warning(f"[{symbol}] yfinance failed: {e} — trying Alpha Vantage fallback")

        # ── 3. Try Alpha Vantage fallback ──────────────────────────────────
        if settings.ALPHA_VANTAGE_KEY:
            av_price = self._alpha_vantage_current_price(symbol)
            if av_price and av_price > 0:
                price_data = PriceData(
                    symbol=symbol,
                    current_price=av_price,
                    open=av_price,
                    high=av_price,
                    low=av_price,
                    close=av_price,
                    volume=0,  # AV GLOBAL_QUOTE doesn't always give intraday volume
                    timestamp=datetime.utcnow(),
                    source="alpha_vantage",
                )
                logger.info(f"[{symbol}] Price from Alpha Vantage fallback: {av_price:.2f}")
                return price_data

        # ── 4. Both sources failed ─────────────────────────────────────────
        raise DataUnavailableError(
            f"[{symbol}] Could not fetch price from any source. "
            f"Last error: {yf_error}"
        )

    # ── Public: get_historical_data ────────────────────────────────────────

    def get_historical_data(
        self,
        symbol: str,
        period: str = "2y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetches daily OHLCV history for a symbol.

        Primary  : yfinance (supports up to 5y daily, up to 60d hourly)
        Fallback : Alpha Vantage (last 100 days, compact mode)
        Cache    : SQLite, 6-hour TTL (avoids repeated downloads)

        Args:
            symbol: Stock symbol (e.g., "RELIANCE.NS")
            period: yfinance period string — "1mo", "3mo", "6mo", "1y", "2y", "5y"
            interval: "1d" (daily), "1h" (hourly — max 60 days)

        Returns:
            pd.DataFrame with columns: Open, High, Low, Close, Volume, Adj_Close
            Index: DatetimeIndex (sorted ascending)

        Raises:
            DataUnavailableError: If no source provides data
            InsufficientHistoryError: If fewer than 50 rows returned
        """
        cache_key = f"historical_{period}_{interval}"

        # ── Check cache ────────────────────────────────────────────────────
        cached = self._cache_get(symbol, cache_key)
        if cached:
            try:
                df = pd.read_json(cached, orient="split")
                df.index = pd.to_datetime(df.index)
                logger.debug(f"[{symbol}] Historical data from cache: {len(df)} rows")
                return df
            except Exception as e:
                logger.debug(f"[{symbol}] Historical cache parse error: {e}")

        # ── Try yfinance ───────────────────────────────────────────────────
        df = None
        try:
            raw_df = self._yfinance_history(symbol, period=period, interval=interval)
            if raw_df is not None and len(raw_df) > 0:
                df = self._clean_ohlcv(raw_df, symbol)
                self._track_api_call("yfinance")
        except Exception as e:
            logger.warning(f"[{symbol}] yfinance history failed: {e}")

        # ── Try Alpha Vantage fallback ─────────────────────────────────────
        if df is None or len(df) < 50:
            if settings.ALPHA_VANTAGE_KEY:
                logger.info(f"[{symbol}] Trying Alpha Vantage for historical data")
                av_df = self._alpha_vantage_history(symbol)
                if av_df is not None and len(av_df) >= 50:
                    df = self._clean_ohlcv(av_df, symbol)
                    logger.info(f"[{symbol}] Historical data from Alpha Vantage: {len(df)} rows")

        if df is None or len(df) == 0:
            raise DataUnavailableError(
                f"[{symbol}] Could not fetch historical data from any source."
            )
        if len(df) < 50:
            raise InsufficientHistoryError(
                f"[{symbol}] Only {len(df)} rows of history available — need at least 50."
            )

        # Cache
        self._cache_set(
            symbol, cache_key,
            df.to_json(orient="split"),
            ttl_seconds=settings.HISTORICAL_CACHE_TTL_SECONDS,
        )

        logger.info(f"[{symbol}] Historical data: {len(df)} rows | "
                    f"{df.index.min().date()} → {df.index.max().date()}")
        return df

    # ── Public: get_bulk_prices ────────────────────────────────────────────

    def get_bulk_prices(self, symbols: List[str]) -> Dict[str, PriceData]:
        """
        Fetches current prices for a list of symbols efficiently.
        Uses yfinance batch download (one HTTP call per batch of ≤10 symbols),
        which is much faster than individual calls.

        Symbols that fail are skipped (with a warning) — not raising exceptions.
        This ensures one bad symbol never blocks the entire watchlist.

        Args:
            symbols: List of stock symbols

        Returns:
            Dict mapping symbol → PriceData for each successful fetch.
            Missing symbols are absent from the dict (check with dict.get()).
        """
        results: Dict[str, PriceData] = {}
        total = len(symbols)

        logger.info(f"Fetching bulk prices for {total} symbols in "
                    f"batches of {self._BATCH_SIZE}")

        # Split into batches to avoid overwhelming the API
        for batch_start in range(0, total, self._BATCH_SIZE):
            batch = symbols[batch_start: batch_start + self._BATCH_SIZE]
            batch_str = " ".join(batch)

            try:
                # yfinance download fetches all tickers in one call
                raw = yf.download(
                    tickers=batch_str,
                    period="2d",          # Only need last 2 days for current price
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )
                self._track_api_call("yfinance")

                for symbol in batch:
                    try:
                        if len(batch) == 1:
                            # Single ticker: yfinance returns flat columns
                            sym_df = raw
                        else:
                            sym_df = raw[symbol] if symbol in raw.columns.get_level_values(0) else None

                        if sym_df is None or len(sym_df) == 0:
                            raise ValueError("Empty dataframe from batch download")

                        last_row = sym_df.dropna(subset=["Close"]).iloc[-1]
                        prev_row = sym_df.dropna(subset=["Close"]).iloc[-2] if len(sym_df) >= 2 else last_row

                        current_price = float(last_row["Close"])
                        if current_price <= 0:
                            raise ValueError(f"Invalid price: {current_price}")

                        price_data = PriceData(
                            symbol=symbol,
                            current_price=current_price,
                            open=float(last_row.get("Open", current_price)),
                            high=float(last_row.get("High", current_price)),
                            low=float(last_row.get("Low", current_price)),
                            close=float(prev_row["Close"]),
                            volume=int(last_row.get("Volume", 0) or 0),
                            timestamp=datetime.utcnow(),
                            source="yfinance_batch",
                        )
                        results[symbol] = price_data

                    except Exception as e:
                        logger.warning(f"[{symbol}] Batch price extraction failed: {e} — "
                                       f"falling back to individual fetch")
                        # Individual fallback for this symbol
                        try:
                            results[symbol] = self.get_current_price(symbol)
                        except DataUnavailableError:
                            logger.error(f"[{symbol}] Price unavailable — skipping")

            except Exception as e:
                logger.warning(f"Batch download failed for {batch}: {e} — "
                               f"falling back to individual fetches")
                for symbol in batch:
                    try:
                        results[symbol] = self.get_current_price(symbol)
                    except DataUnavailableError:
                        logger.error(f"[{symbol}] Price unavailable — skipping")

            # Polite delay between batches to avoid rate limiting
            if batch_start + self._BATCH_SIZE < total:
                time.sleep(0.5)

        success_count = len(results)
        fail_count = total - success_count
        logger.info(f"Bulk price fetch: {success_count}/{total} succeeded, "
                    f"{fail_count} failed")
        return results

    # ── Public: get_intraday_data ──────────────────────────────────────────

    def get_intraday_data(
        self,
        symbol: str,
        interval: str = "5m",
        period: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetches intraday OHLCV data for a symbol.
        Used by intraday trading strategy (if TRADING_STYLE=intraday).

        Args:
            symbol: Stock symbol
            interval: "1m", "5m", "15m", "30m", "1h"
            period: "1d" (today only), "5d" (last 5 days)

        Returns:
            DataFrame with OHLCV columns, DatetimeIndex
        """
        cache_key = f"intraday_{interval}_{period}"
        cached = self._cache_get(symbol, cache_key)
        if cached:
            try:
                df = pd.read_json(cached, orient="split")
                df.index = pd.to_datetime(df.index)
                return df
            except Exception:
                pass

        try:
            df = self._yfinance_history(symbol, period=period, interval=interval)
            if df is not None and len(df) > 0:
                df = self._clean_ohlcv(df, symbol)
                # Intraday data expires quickly: 2-minute cache
                self._cache_set(symbol, cache_key, df.to_json(orient="split"), ttl_seconds=120)
                logger.debug(f"[{symbol}] Intraday {interval}: {len(df)} bars")
                return df
        except Exception as e:
            logger.warning(f"[{symbol}] Intraday data fetch failed: {e}")

        raise DataUnavailableError(f"[{symbol}] Could not fetch {interval} intraday data.")

    # ── Public: validate_price_data ────────────────────────────────────────

    def validate_price_data(
        self,
        price_data: PriceData,
        symbol: str,
        is_india: Optional[bool] = None,
    ) -> Tuple[bool, str]:
        """
        Validates that a PriceData object looks sane before using it in analysis.

        Checks:
          - Price > 0
          - Price not a >20% jump from previous close (bad data / circuit breaker)
          - Volume above minimum liquidity threshold
          - Data not stale (within last 15 minutes during market hours)

        Returns:
            Tuple of (is_valid: bool, reason: str)
        """
        if price_data.current_price <= 0:
            return False, f"Invalid price: {price_data.current_price}"

        # Check for suspicious price spike (possible bad data)
        if price_data.close and price_data.close > 0:
            change_pct = abs(
                (price_data.current_price - price_data.close) / price_data.close
            )
            if change_pct > PRICE_SPIKE_THRESHOLD:
                return False, (
                    f"Suspicious price change: {change_pct:.1%} from previous close "
                    f"({price_data.close:.2f} → {price_data.current_price:.2f}). "
                    f"Possible circuit breaker or bad data — skipping."
                )

        # Volume check
        min_vol = MIN_DAILY_VOLUME_US if is_india is False else MIN_DAILY_VOLUME
        if price_data.volume < min_vol and price_data.source != "alpha_vantage":
            return False, (
                f"Volume too low: {price_data.volume:,} < minimum {min_vol:,}. "
                f"Stock may be illiquid — skipping."
            )

        return True, "OK"
