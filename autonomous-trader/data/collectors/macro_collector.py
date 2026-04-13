"""
data/collectors/macro_collector.py
=====================================
Determines macroeconomic market conditions and regime.

Data sources:
  - FRED API (Federal Reserve — free, unlimited, no key required)
  - yfinance — for VIX, index prices, and moving averages
  - Computed from FRED + yfinance combined signals

The MacroCollector answers three questions for the trading system:
  1. What is the current market regime? (STRONG_BULL → STRONG_BEAR)
  2. Is the interest rate environment rising, falling, or stable?
  3. Which sectors are gaining / losing momentum?

Usage:
    from data.collectors.macro_collector import MacroCollector
    collector = MacroCollector()
    regime = collector.get_market_regime()
    rate_trend = collector.get_interest_rate_trend()
    sectors = collector.get_sector_rotation()
"""

from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple

import pandas as pd
import numpy as np
import yfinance as yf
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
import logging

try:
    import fredapi
    FRED_AVAILABLE = True
except ImportError:
    FRED_AVAILABLE = False

from config.settings import settings
from config.constants import (
    MarketRegime,
    REGIME_POSITION_MULTIPLIER,
    FRED_SERIES,
    VIX_LOW,
    VIX_MODERATE,
    VIX_HIGH,
    VIX_VERY_HIGH,
    VIX_EXTREME,
    NIFTY_50_SYMBOL,
    SP500_SYMBOL,
    VIX_SYMBOL,
    NSE_SECTOR_MAP,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class MacroSnapshot:
    """Complete macroeconomic snapshot used by agents to contextualise decisions."""
    timestamp: datetime
    regime: str                      # MarketRegime value
    regime_position_multiplier: float

    # VIX
    vix_current: Optional[float]
    vix_signal: str                  # "LOW_FEAR" | "MODERATE" | "HIGH_FEAR" | "EXTREME_FEAR"

    # Index position vs moving averages
    nifty_vs_sma200: Optional[float]  # % above/below 200-day SMA (positive = above)
    sp500_vs_sma200: Optional[float]

    # Rate environment
    interest_rate_trend: str          # "RISING" | "FALLING" | "STABLE"
    fed_funds_rate: Optional[float]
    treasury_10y: Optional[float]
    treasury_2y: Optional[float]
    yield_curve_spread: Optional[float]  # 10Y - 2Y (negative = potential recession signal)

    # Economic health
    us_gdp_growth: Optional[float]
    us_unemployment: Optional[float]
    us_inflation_cpi: Optional[float]

    # Derived signals
    recession_risk: str               # "LOW" | "MODERATE" | "HIGH"
    regime_reasoning: str             # Human-readable explanation of regime decision

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


# ═══════════════════════════════════════════════════════════════
# MACRO COLLECTOR
# ═══════════════════════════════════════════════════════════════

class MacroCollector:
    """
    Collects and synthesises macroeconomic data into a MarketRegime signal.

    The regime signal is the single most important override in the system:
    - STRONG_BEAR regime blocks ALL new trades regardless of individual stock signals
    - Lower regimes reduce position sizes automatically via position multiplier
    """

    # Cache macro data for 4 hours (FRED data only updates daily/monthly)
    _CACHE_TTL_SECONDS = 4 * 3600

    # Number of days for moving average calculation
    _SMA200_PERIOD = 200
    _SMA50_PERIOD = 50

    # Rate change thresholds to determine trend
    _RATE_CHANGE_SIGNIFICANT = 0.25  # 25 basis points = significant change

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(settings.database_path_resolved)
        self._fred = None
        self._ensure_cache_table()
        self._init_fred()

    def _ensure_cache_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS macro_cache (
                    cache_key  TEXT PRIMARY KEY,
                    data_json  TEXT NOT NULL,
                    cached_at  TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def _init_fred(self) -> None:
        """Initialises the FRED API client. No API key required for public data."""
        if not FRED_AVAILABLE:
            logger.warning("fredapi not installed — FRED economic data unavailable. "
                           "Install with: pip install fredapi")
            return
        try:
            # FRED public data requires no API key
            self._fred = fredapi.Fred()
            logger.debug("FRED API client initialised (no key needed for public series)")
        except Exception as e:
            logger.warning(f"FRED API init failed: {e} — macro data will be limited")
            self._fred = None

    # ── Internal: Cache helpers ────────────────────────────────────────────

    def _cache_get(self, key: str) -> Optional[dict]:
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT data_json, expires_at FROM macro_cache WHERE cache_key=?",
                    (key,),
                ).fetchone()
            if row:
                expires = datetime.fromisoformat(row[1])
                if datetime.utcnow() < expires:
                    return json.loads(row[0])
        except Exception as e:
            logger.debug(f"Macro cache read error [{key}]: {e}")
        return None

    def _cache_set(self, key: str, data: dict, ttl_seconds: int = None) -> None:
        ttl = ttl_seconds or self._CACHE_TTL_SECONDS
        try:
            now = datetime.utcnow()
            expires = now + timedelta(seconds=ttl)
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO macro_cache (cache_key, data_json, cached_at, expires_at)
                    VALUES (?, ?, ?, ?)
                """, (key, json.dumps(data), now.isoformat(), expires.isoformat()))
                conn.commit()
        except Exception as e:
            logger.debug(f"Macro cache write error [{key}]: {e}")

    # ── Internal: FRED data fetching ───────────────────────────────────────

    def _fetch_fred_series(
        self,
        series_id: str,
        observations_back: int = 12,
    ) -> Optional[pd.Series]:
        """
        Fetches the most recent N observations for a FRED data series.
        FRED data is public and unlimited — no API key required.
        """
        if self._fred is None:
            return None
        try:
            data = self._fred.get_series(
                series_id,
                observation_start=(
                    datetime.utcnow() - timedelta(days=observations_back * 35)
                ).strftime("%Y-%m-%d"),
            )
            if data is None or len(data) == 0:
                return None
            return data.dropna()
        except Exception as e:
            logger.debug(f"FRED series {series_id} fetch failed: {e}")
            return None

    def _get_latest_fred_value(self, series_id: str) -> Optional[float]:
        """Returns the single most recent value for a FRED series."""
        series = self._fetch_fred_series(series_id, observations_back=3)
        if series is not None and len(series) > 0:
            return float(series.iloc[-1])
        return None

    # ── Internal: yfinance index data ──────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        reraise=False,
    )
    def _get_index_sma_position(self, symbol: str, sma_period: int = 200) -> Optional[float]:
        """
        Fetches the current price of an index and calculates its position
        relative to its N-day simple moving average.

        Returns:
            Percentage above (+) or below (-) the SMA.
            E.g., 3.5 = price is 3.5% above SMA, -2.1 = 2.1% below SMA.
            None if data is unavailable.
        """
        try:
            # Need enough history for the SMA calculation
            ticker = yf.Ticker(symbol)
            hist = ticker.history(
                period=f"{sma_period + 50}d",
                interval="1d",
                auto_adjust=True,
            )
            if hist is None or len(hist) < sma_period:
                logger.debug(f"Insufficient history for {symbol} SMA{sma_period}")
                return None

            close = hist["Close"].dropna()
            current_price = float(close.iloc[-1])
            sma = float(close.rolling(window=sma_period).mean().iloc[-1])

            if sma <= 0:
                return None

            position_pct = (current_price - sma) / sma * 100
            logger.debug(f"{symbol} vs SMA{sma_period}: {position_pct:+.2f}% "
                         f"(price={current_price:.2f}, sma={sma:.2f})")
            return round(position_pct, 2)

        except Exception as e:
            logger.debug(f"SMA position for {symbol} failed: {e}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        reraise=False,
    )
    def _get_vix(self) -> Optional[float]:
        """Fetches the current VIX (CBOE Volatility Index) value."""
        try:
            ticker = yf.Ticker(VIX_SYMBOL)
            hist = ticker.history(period="5d", interval="1d")
            if hist is not None and len(hist) > 0:
                vix = float(hist["Close"].dropna().iloc[-1])
                logger.debug(f"VIX: {vix:.2f}")
                return vix
        except Exception as e:
            logger.debug(f"VIX fetch failed: {e}")
        return None

    # ── Internal: Regime determination logic ──────────────────────────────

    def _classify_vix(self, vix: Optional[float]) -> str:
        """Classifies VIX level into a human-readable signal."""
        if vix is None:
            return "UNKNOWN"
        if vix < VIX_LOW:
            return "LOW_FEAR"
        elif vix < VIX_MODERATE:
            return "MODERATE"
        elif vix < VIX_HIGH:
            return "ELEVATED"
        elif vix < VIX_VERY_HIGH:
            return "HIGH_FEAR"
        else:
            return "EXTREME_FEAR"

    def _compute_regime(
        self,
        vix: Optional[float],
        nifty_vs_sma200: Optional[float],
        sp500_vs_sma200: Optional[float],
        yield_curve: Optional[float],
        gdp_growth: Optional[float],
        unemployment: Optional[float],
    ) -> Tuple[MarketRegime, str]:
        """
        Synthesises all available signals into a single MarketRegime.

        Scoring system (total 0-10 points, higher = more bullish):
          +2 : VIX < 15 (low fear)
          +1 : VIX 15-20 (moderate)
          +0 : VIX 20-25 (elevated)
          -1 : VIX 25-35 (high fear)
          -2 : VIX > 35 (extreme fear — circuit breaker territory)

          +2 : Nifty/SPX price > SMA200 by >2% (clear uptrend)
          +1 : Nifty/SPX price within ±2% of SMA200 (at key level)
          -1 : Nifty/SPX price < SMA200 by >2% (downtrend)
          -2 : Nifty/SPX price < SMA200 by >5% (deep downtrend)

          +1 : Yield curve positive (not inverted)
          -1 : Yield curve inverted (< -0.25%)

          +1 : GDP growth > 2%
          -1 : GDP growth < 0% (recession)

        Thresholds:
          score ≥ 4  → STRONG_BULL
          score 2-3  → BULL
          score 0-1  → NEUTRAL
          score -1–-2 → BEAR
          score ≤ -3 → STRONG_BEAR
        """
        score = 0
        reasons = []

        # VIX contribution
        if vix is not None:
            if vix < VIX_LOW:
                score += 2
                reasons.append(f"VIX={vix:.1f} (low fear, +2)")
            elif vix < VIX_MODERATE:
                score += 1
                reasons.append(f"VIX={vix:.1f} (moderate, +1)")
            elif vix < VIX_HIGH:
                score += 0
                reasons.append(f"VIX={vix:.1f} (elevated, 0)")
            elif vix < VIX_VERY_HIGH:
                score -= 1
                reasons.append(f"VIX={vix:.1f} (high fear, -1)")
            else:
                score -= 2
                reasons.append(f"VIX={vix:.1f} (EXTREME FEAR, -2)")

        # Index vs SMA200 contribution (use whichever is available)
        primary_sma = nifty_vs_sma200 if nifty_vs_sma200 is not None else sp500_vs_sma200
        if primary_sma is not None:
            if primary_sma > 2.0:
                score += 2
                reasons.append(f"Index {primary_sma:+.1f}% above SMA200 (uptrend, +2)")
            elif primary_sma > -2.0:
                score += 1
                reasons.append(f"Index {primary_sma:+.1f}% near SMA200 (neutral zone, +1)")
            elif primary_sma > -5.0:
                score -= 1
                reasons.append(f"Index {primary_sma:+.1f}% below SMA200 (downtrend, -1)")
            else:
                score -= 2
                reasons.append(f"Index {primary_sma:+.1f}% below SMA200 (deep downtrend, -2)")

        # Yield curve contribution
        if yield_curve is not None:
            if yield_curve < -0.25:
                score -= 1
                reasons.append(f"Yield curve inverted ({yield_curve:+.2f}%, recession risk, -1)")
            else:
                score += 1
                reasons.append(f"Yield curve positive ({yield_curve:+.2f}%, +1)")

        # GDP growth contribution
        if gdp_growth is not None:
            if gdp_growth < 0:
                score -= 1
                reasons.append(f"GDP growth negative ({gdp_growth:.1f}%, recession signal, -1)")
            elif gdp_growth > 2.0:
                score += 1
                reasons.append(f"GDP growing ({gdp_growth:.1f}%, +1)")

        # Determine regime from score
        if score >= 4:
            regime = MarketRegime.STRONG_BULL
        elif score >= 2:
            regime = MarketRegime.BULL
        elif score >= 0:
            regime = MarketRegime.NEUTRAL
        elif score >= -2:
            regime = MarketRegime.BEAR
        else:
            regime = MarketRegime.STRONG_BEAR

        reasoning = (
            f"Market regime: {regime.value} (score={score}). "
            + " | ".join(reasons)
        )
        logger.info(reasoning)
        return regime, reasoning

    def _assess_recession_risk(
        self,
        yield_curve: Optional[float],
        unemployment: Optional[float],
        gdp_growth: Optional[float],
    ) -> str:
        """
        Simple recession risk assessment based on leading indicators.
        Returns: "LOW" | "MODERATE" | "HIGH"
        """
        risk_score = 0

        # Inverted yield curve is a classic recession predictor
        if yield_curve is not None and yield_curve < -0.50:
            risk_score += 2
        elif yield_curve is not None and yield_curve < -0.25:
            risk_score += 1

        # Rising unemployment
        if unemployment is not None and unemployment > 6.0:
            risk_score += 2
        elif unemployment is not None and unemployment > 4.5:
            risk_score += 1

        # Negative GDP
        if gdp_growth is not None and gdp_growth < 0:
            risk_score += 2
        elif gdp_growth is not None and gdp_growth < 1.0:
            risk_score += 1

        if risk_score >= 4:
            return "HIGH"
        elif risk_score >= 2:
            return "MODERATE"
        else:
            return "LOW"

    # ── Public: get_market_regime ──────────────────────────────────────────

    def get_market_regime(self) -> MacroSnapshot:
        """
        Determines the current market regime by synthesising all macro signals.

        This is the primary output of MacroCollector. The returned regime
        directly controls position sizing via REGIME_POSITION_MULTIPLIER.

        STRONG_BEAR → no new positions (multiplier = 0.0)
        STRONG_BULL → full positions (multiplier = 1.0)

        Data refresh: cached for 4 hours (macro data doesn't change minute-to-minute)

        Returns:
            MacroSnapshot with regime, multiplier, all raw indicators, and reasoning.
        """
        cache_key = "market_regime"
        cached = self._cache_get(cache_key)
        if cached:
            try:
                snapshot = MacroSnapshot(
                    timestamp=datetime.fromisoformat(cached["timestamp"]),
                    regime=cached["regime"],
                    regime_position_multiplier=cached["regime_position_multiplier"],
                    vix_current=cached.get("vix_current"),
                    vix_signal=cached["vix_signal"],
                    nifty_vs_sma200=cached.get("nifty_vs_sma200"),
                    sp500_vs_sma200=cached.get("sp500_vs_sma200"),
                    interest_rate_trend=cached["interest_rate_trend"],
                    fed_funds_rate=cached.get("fed_funds_rate"),
                    treasury_10y=cached.get("treasury_10y"),
                    treasury_2y=cached.get("treasury_2y"),
                    yield_curve_spread=cached.get("yield_curve_spread"),
                    us_gdp_growth=cached.get("us_gdp_growth"),
                    us_unemployment=cached.get("us_unemployment"),
                    us_inflation_cpi=cached.get("us_inflation_cpi"),
                    recession_risk=cached["recession_risk"],
                    regime_reasoning=cached["regime_reasoning"],
                )
                logger.debug(f"Market regime from cache: {snapshot.regime}")
                return snapshot
            except Exception as e:
                logger.debug(f"Macro cache parse failed: {e} — fetching fresh")

        logger.info("Fetching macro data for regime determination...")

        # ── Fetch all indicators ───────────────────────────────────────────

        # VIX (real-time sentiment gauge)
        vix = self._get_vix()

        # Index vs 200-day SMA
        nifty_sma = None
        sp500_sma = None

        if settings.TARGET_MARKET in ("india", "both"):
            nifty_sma = self._get_index_sma_position(NIFTY_50_SYMBOL, sma_period=200)

        if settings.TARGET_MARKET in ("us", "both"):
            sp500_sma = self._get_index_sma_position(SP500_SYMBOL, sma_period=200)

        # FRED economic indicators (free, no key)
        fed_funds_rate = self._get_latest_fred_value(FRED_SERIES["federal_funds_rate"])
        treasury_10y = self._get_latest_fred_value(FRED_SERIES["treasury_10y"])
        treasury_2y = self._get_latest_fred_value(FRED_SERIES["treasury_2y"])
        gdp_growth = self._get_latest_fred_value(FRED_SERIES["gdp_growth"])
        unemployment = self._get_latest_fred_value(FRED_SERIES["unemployment"])
        cpi = self._get_latest_fred_value(FRED_SERIES["cpi_inflation"])

        # Yield curve spread (10Y - 2Y) — classic recession predictor
        yield_curve = None
        if treasury_10y is not None and treasury_2y is not None:
            yield_curve = treasury_10y - treasury_2y

        # Interest rate trend
        interest_rate_trend = self.get_interest_rate_trend()

        # ── Compute regime ─────────────────────────────────────────────────
        regime, reasoning = self._compute_regime(
            vix=vix,
            nifty_vs_sma200=nifty_sma,
            sp500_vs_sma200=sp500_sma,
            yield_curve=yield_curve,
            gdp_growth=gdp_growth,
            unemployment=unemployment,
        )

        # Recession risk
        recession_risk = self._assess_recession_risk(yield_curve, unemployment, gdp_growth)

        # ── Build snapshot ─────────────────────────────────────────────────
        snapshot = MacroSnapshot(
            timestamp=datetime.utcnow(),
            regime=regime.value,
            regime_position_multiplier=REGIME_POSITION_MULTIPLIER[regime],
            vix_current=vix,
            vix_signal=self._classify_vix(vix),
            nifty_vs_sma200=nifty_sma,
            sp500_vs_sma200=sp500_sma,
            interest_rate_trend=interest_rate_trend,
            fed_funds_rate=fed_funds_rate,
            treasury_10y=treasury_10y,
            treasury_2y=treasury_2y,
            yield_curve_spread=yield_curve,
            us_gdp_growth=gdp_growth,
            us_unemployment=unemployment,
            us_inflation_cpi=cpi,
            recession_risk=recession_risk,
            regime_reasoning=reasoning,
        )

        self._cache_set(cache_key, snapshot.to_dict())
        logger.info(
            f"Market regime: {regime.value} | "
            f"Multiplier: {snapshot.regime_position_multiplier}x | "
            f"VIX: {vix} | Recession risk: {recession_risk}"
        )
        return snapshot

    # ── Public: get_interest_rate_trend ───────────────────────────────────

    def get_interest_rate_trend(self) -> str:
        """
        Determines if interest rates are RISING, FALLING, or STABLE
        based on the last 6 months of Fed Funds Rate data from FRED.

        Returns:
            "RISING" | "FALLING" | "STABLE"
        """
        cache_key = "interest_rate_trend"
        cached = self._cache_get(cache_key)
        if cached:
            return cached.get("trend", "STABLE")

        trend = "STABLE"  # Default if data unavailable
        try:
            series = self._fetch_fred_series(FRED_SERIES["federal_funds_rate"], observations_back=6)
            if series is not None and len(series) >= 2:
                recent = float(series.iloc[-1])
                older = float(series.iloc[0])
                change = recent - older

                if change > self._RATE_CHANGE_SIGNIFICANT:
                    trend = "RISING"
                elif change < -self._RATE_CHANGE_SIGNIFICANT:
                    trend = "FALLING"
                else:
                    trend = "STABLE"

                logger.info(f"Interest rate trend: {trend} "
                            f"(rate 6mo ago: {older:.2f}%, current: {recent:.2f}%, "
                            f"change: {change:+.2f}%)")
        except Exception as e:
            logger.warning(f"Interest rate trend calculation failed: {e} — defaulting to STABLE")

        self._cache_set(cache_key, {"trend": trend}, ttl_seconds=self._CACHE_TTL_SECONDS)
        return trend

    # ── Public: get_sector_rotation ────────────────────────────────────────

    def get_sector_rotation(self) -> Dict[str, str]:
        """
        Calculates sector momentum for the Indian market.
        Compares each sector's 1-month return vs the Nifty 50 benchmark.

        Sectors performing > 2% above Nifty → "BULLISH"
        Sectors performing > 2% below Nifty → "BEARISH"
        Others → "NEUTRAL"

        Uses sector ETFs/indices available on NSE via yfinance.
        Falls back to classifying based on Nifty sector index symbols.

        Returns:
            Dict mapping sector name → "BULLISH" | "NEUTRAL" | "BEARISH"
        """
        cache_key = "sector_rotation"
        cached = self._cache_get(cache_key)
        if cached and "sectors" in cached:
            return cached["sectors"]

        # NSE sector index symbols (available via yfinance with .NS suffix)
        sector_indices = {
            "IT": "^CNXIT",          # Nifty IT
            "Banking": "^NSEBANK",   # Nifty Bank
            "Pharma": "^CNXPHARMA",  # Nifty Pharma
            "Auto": "^CNXAUTO",      # Nifty Auto
            "FMCG": "^CNXFMCG",     # Nifty FMCG
            "Energy": "^CNXENERGY",  # Nifty Energy
            "Infra": "^CNXINFRA",    # Nifty Infrastructure
            "Metal": "^CNXMETAL",    # Nifty Metal
            "Realty": "^CNXREALTY",  # Nifty Realty
        }

        sector_signals: Dict[str, str] = {}

        try:
            # Get Nifty 50 benchmark 1-month return
            nifty_return = self._get_1month_return(NIFTY_50_SYMBOL)

            for sector, symbol in sector_indices.items():
                try:
                    sector_return = self._get_1month_return(symbol)
                    if sector_return is None or nifty_return is None:
                        sector_signals[sector] = "NEUTRAL"
                        continue

                    relative_perf = sector_return - nifty_return

                    if relative_perf > 2.0:
                        sector_signals[sector] = "BULLISH"
                    elif relative_perf < -2.0:
                        sector_signals[sector] = "BEARISH"
                    else:
                        sector_signals[sector] = "NEUTRAL"

                    logger.debug(f"Sector {sector}: {sector_return:+.1f}% "
                                 f"(vs Nifty {nifty_return:+.1f}%, "
                                 f"rel={relative_perf:+.1f}%) → {sector_signals[sector]}")
                except Exception as e:
                    logger.debug(f"Sector {sector} return failed: {e}")
                    sector_signals[sector] = "NEUTRAL"

        except Exception as e:
            logger.warning(f"Sector rotation calculation failed: {e}")
            # Return all neutral if calculation fails
            sector_signals = {s: "NEUTRAL" for s in sector_indices}

        if not sector_signals:
            sector_signals = {s: "NEUTRAL" for s in sector_indices}

        self._cache_set(
            cache_key,
            {"sectors": sector_signals},
            ttl_seconds=self._CACHE_TTL_SECONDS,
        )
        logger.info(
            "Sector rotation: "
            + ", ".join(f"{k}={v}" for k, v in sector_signals.items())
        )
        return sector_signals

    def _get_1month_return(self, symbol: str) -> Optional[float]:
        """
        Calculates the 1-month price return for a symbol.
        Returns percentage return (e.g., 3.5 means +3.5%).
        """
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="35d", interval="1d", auto_adjust=True)
            if hist is None or len(hist) < 20:
                return None
            close = hist["Close"].dropna()
            start_price = float(close.iloc[0])
            end_price = float(close.iloc[-1])
            if start_price <= 0:
                return None
            return (end_price - start_price) / start_price * 100
        except Exception:
            return None

    # ── Public: get_sector_for_symbol ──────────────────────────────────────

    def get_sector_for_symbol(self, symbol: str) -> Optional[str]:
        """Returns the sector for a given NSE symbol, if known."""
        return NSE_SECTOR_MAP.get(symbol)

    def is_bullish_sector(self, symbol: str) -> bool:
        """
        Returns True if the sector for this symbol is currently BULLISH,
        based on the latest sector rotation data.
        """
        sector = self.get_sector_for_symbol(symbol)
        if not sector:
            return True  # Unknown sector — don't penalise
        rotation = self.get_sector_rotation()
        return rotation.get(sector, "NEUTRAL") == "BULLISH"
