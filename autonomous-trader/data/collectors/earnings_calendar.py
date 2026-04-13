"""
data/collectors/earnings_calendar.py
========================================
Detects upcoming earnings announcements that create trade-blocking risk.

Why this matters:
  Stocks become extremely unpredictable around earnings:
  - A surprise earnings beat can gap UP 10-20% overnight
  - A miss can gap DOWN similarly
  - Even meeting expectations can cause big moves if guidance disappoints

  The system uses this data to:
    - BLOCK all trades within 24 hours of an earnings release
    - Reduce position size 50% within 72 hours
    - Reduce position size 30% within 7 days

Data sources (scraped — all free):
  1. Yahoo Finance earnings calendar (via yfinance)
  2. Screener.in (Indian stocks — BeautifulSoup scraping)
  3. Investing.com earnings calendar (scraping)
  4. Company's own investor relations page (fallback)

Usage:
    from data.collectors.earnings_calendar import EarningsCalendarCollector
    collector = EarningsCalendarCollector()
    risk = collector.has_earnings_risk("RELIANCE.NS")
    if risk.risk_level == "BLOCK":
        print("Do not trade — earnings today!")
"""

from __future__ import annotations

import sqlite3
import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, date, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
import yfinance as yf
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
import logging

from config.settings import settings
from config.constants import (
    EarningsRiskLevel,
    EARNINGS_BLOCK_HOURS,
    EARNINGS_HIGH_RISK_HOURS,
    EARNINGS_LOW_RISK_DAYS,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class EarningsEvent:
    """Represents a single upcoming earnings announcement."""
    symbol: str
    company_name: str
    earnings_date: date
    earnings_time: str          # "BMO" (before market open) | "AMC" (after market close) | "UNKNOWN"
    expected_eps: Optional[float]
    previous_eps: Optional[float]
    source: str                 # Where this date came from

    @property
    def days_until(self) -> int:
        """Returns number of calendar days until the earnings date."""
        today = datetime.now(timezone.utc).date()
        return (self.earnings_date - today).days

    @property
    def hours_until(self) -> float:
        """Returns approximate hours until the earnings event."""
        today = datetime.now(timezone.utc)
        earnings_dt = datetime.combine(
            self.earnings_date,
            datetime.strptime("16:00", "%H:%M").time(),  # Assume market close time if unknown
        ).replace(tzinfo=timezone.utc)

        if self.earnings_time == "BMO":
            earnings_dt = datetime.combine(
                self.earnings_date,
                datetime.strptime("09:30", "%H:%M").time(),
            ).replace(tzinfo=timezone.utc)

        return max(0, (earnings_dt - today).total_seconds() / 3600)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["earnings_date"] = self.earnings_date.isoformat()
        return d


@dataclass
class EarningsRisk:
    """Risk assessment for a single stock based on its earnings calendar."""
    symbol: str
    has_risk: bool
    days_until_earnings: Optional[int]
    hours_until_earnings: Optional[float]
    risk_level: str                      # EarningsRiskLevel value
    position_size_multiplier: float      # 0.0 = blocked, 0.5 = half size, etc.
    earnings_event: Optional[EarningsEvent]
    reasoning: str

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.earnings_event:
            d["earnings_event"] = self.earnings_event.to_dict()
        return d


# ═══════════════════════════════════════════════════════════════
# EARNINGS CALENDAR COLLECTOR
# ═══════════════════════════════════════════════════════════════

class EarningsCalendarCollector:
    """
    Scrapes and caches upcoming earnings dates for all watchlist stocks.
    Provides a simple has_earnings_risk() method for use in trade gates.
    """

    _HTTP_TIMEOUT = 12
    _CACHE_TTL_SECONDS = 6 * 3600  # Refresh earnings calendar every 6 hours

    # Screener.in base URL for Indian company earnings
    _SCREENER_BASE = "https://www.screener.in/company"

    # Yahoo Finance earnings calendar
    _YAHOO_EARNINGS_URL = "https://finance.yahoo.com/calendar/earnings"

    # User agent for scraping (polite bot declaration)
    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(settings.database_path_resolved)
        self._session = requests.Session()
        self._session.headers.update(self._HEADERS)
        self._ensure_tables()

    # ── Internal: Database & Cache ─────────────────────────────────────────

    def _ensure_tables(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            # Earnings events storage
            conn.execute("""
                CREATE TABLE IF NOT EXISTS earnings_events (
                    symbol          TEXT NOT NULL,
                    earnings_date   TEXT NOT NULL,
                    earnings_time   TEXT DEFAULT 'UNKNOWN',
                    expected_eps    REAL,
                    previous_eps    REAL,
                    company_name    TEXT,
                    source          TEXT,
                    fetched_at      TEXT NOT NULL,
                    expires_at      TEXT NOT NULL,
                    PRIMARY KEY (symbol, earnings_date)
                )
            """)
            # Cache for earnings risk assessments
            conn.execute("""
                CREATE TABLE IF NOT EXISTS earnings_risk_cache (
                    symbol     TEXT PRIMARY KEY,
                    data_json  TEXT NOT NULL,
                    cached_at  TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def _save_earnings_event(self, event: EarningsEvent) -> None:
        """Persists an earnings event to the database."""
        try:
            now = datetime.utcnow()
            expires = now + timedelta(seconds=self._CACHE_TTL_SECONDS)
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO earnings_events
                        (symbol, earnings_date, earnings_time, expected_eps, previous_eps,
                         company_name, source, fetched_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.symbol,
                    event.earnings_date.isoformat(),
                    event.earnings_time,
                    event.expected_eps,
                    event.previous_eps,
                    event.company_name,
                    event.source,
                    now.isoformat(),
                    expires.isoformat(),
                ))
                conn.commit()
        except Exception as e:
            logger.debug(f"Save earnings event failed: {e}")

    def _load_earnings_from_db(self, symbol: str, days_ahead: int = 30) -> List[EarningsEvent]:
        """Loads non-expired earnings events from the database for a symbol."""
        try:
            today = datetime.utcnow().date()
            future_cutoff = (today + timedelta(days=days_ahead)).isoformat()
            now_str = datetime.utcnow().isoformat()

            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute("""
                    SELECT symbol, earnings_date, earnings_time, expected_eps,
                           previous_eps, company_name, source
                    FROM earnings_events
                    WHERE symbol = ?
                      AND earnings_date >= ?
                      AND earnings_date <= ?
                      AND expires_at > ?
                    ORDER BY earnings_date ASC
                """, (symbol, today.isoformat(), future_cutoff, now_str)).fetchall()

            events = []
            for row in rows:
                try:
                    events.append(EarningsEvent(
                        symbol=row[0],
                        earnings_date=date.fromisoformat(row[1]),
                        earnings_time=row[2] or "UNKNOWN",
                        expected_eps=row[3],
                        previous_eps=row[4],
                        company_name=row[5] or row[0],
                        source=row[6] or "db_cache",
                    ))
                except Exception:
                    continue
            return events
        except Exception as e:
            logger.debug(f"Load earnings from DB failed: {e}")
            return []

    # ── Internal: yfinance earnings ────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=2, max=8),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        reraise=False,
    )
    def _fetch_yfinance_earnings(self, symbol: str) -> List[EarningsEvent]:
        """
        Fetches upcoming earnings date from yfinance calendar.
        yfinance provides earnings dates for most major US and Indian stocks.
        """
        events = []
        try:
            ticker = yf.Ticker(symbol)
            company_name = ticker.info.get("longName", symbol) if ticker.info else symbol

            # Try earnings_dates first (newer yfinance)
            try:
                cal = ticker.earnings_dates
                if cal is not None and not cal.empty:
                    today = datetime.utcnow().date()
                    for idx in cal.index:
                        try:
                            dt = idx.date() if hasattr(idx, 'date') else date.fromisoformat(str(idx)[:10])
                            if dt >= today:
                                expected_eps = None
                                previous_eps = None
                                if "EPS Estimate" in cal.columns:
                                    val = cal.loc[idx, "EPS Estimate"]
                                    if val and str(val) not in ("nan", "None"):
                                        expected_eps = float(val)
                                if "Reported EPS" in cal.columns:
                                    val = cal.loc[idx, "Reported EPS"]
                                    if val and str(val) not in ("nan", "None"):
                                        previous_eps = float(val)

                                events.append(EarningsEvent(
                                    symbol=symbol,
                                    company_name=company_name,
                                    earnings_date=dt,
                                    earnings_time="UNKNOWN",
                                    expected_eps=expected_eps,
                                    previous_eps=previous_eps,
                                    source="yfinance_earnings_dates",
                                ))
                        except Exception:
                            continue
                    if events:
                        logger.debug(f"[{symbol}] yfinance earnings_dates: "
                                     f"{len(events)} upcoming events")
                        return events
            except Exception:
                pass

            # Fallback: try calendar property
            try:
                cal = ticker.calendar
                if cal is not None:
                    # calendar is a dict with 'Earnings Date' key
                    earnings_dates = None
                    if isinstance(cal, dict):
                        earnings_dates = cal.get("Earnings Date") or cal.get("earningsDate")
                    elif hasattr(cal, 'loc'):
                        try:
                            earnings_dates = cal.loc["Earnings Date"]
                        except Exception:
                            pass

                    if earnings_dates is not None:
                        dates_list = earnings_dates if hasattr(earnings_dates, '__iter__') and not isinstance(earnings_dates, str) else [earnings_dates]
                        today = datetime.utcnow().date()
                        for d in dates_list:
                            try:
                                if hasattr(d, 'date'):
                                    dt = d.date()
                                elif hasattr(d, 'to_pydatetime'):
                                    dt = d.to_pydatetime().date()
                                else:
                                    dt = date.fromisoformat(str(d)[:10])
                                if dt >= today:
                                    events.append(EarningsEvent(
                                        symbol=symbol,
                                        company_name=company_name,
                                        earnings_date=dt,
                                        earnings_time="UNKNOWN",
                                        expected_eps=None,
                                        previous_eps=None,
                                        source="yfinance_calendar",
                                    ))
                            except Exception:
                                continue
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"[{symbol}] yfinance earnings fetch failed: {e}")

        return events

    # ── Internal: Screener.in (Indian stocks) ──────────────────────────────

    def _fetch_screener_earnings(self, symbol: str) -> List[EarningsEvent]:
        """
        Scrapes Screener.in for Indian stock earnings/results dates.
        Screener.in is a popular free platform for Indian stock analysis.
        """
        events = []
        try:
            # Strip .NS/.BO suffix for Screener.in search
            base = symbol.replace(".NS", "").replace(".BO", "")
            url = f"{self._SCREENER_BASE}/{base}/consolidated/"

            resp = self._session.get(url, timeout=self._HTTP_TIMEOUT)
            if resp.status_code == 404:
                # Try without /consolidated/
                url = f"{self._SCREENER_BASE}/{base}/"
                resp = self._session.get(url, timeout=self._HTTP_TIMEOUT)

            if resp.status_code != 200:
                logger.debug(f"[{symbol}] Screener.in returned status {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "lxml")

            # Screener.in shows next quarterly results date in the company header
            # Look for text patterns like "Results on DD Mon YYYY"
            result_patterns = [
                r"(?:Results|Earnings|Quarterly Results)\s+(?:on|date[:\s]+)\s*(\d{1,2}\s+\w+\s+\d{4})",
                r"(?:Next results?|Board meeting)\s*(?:on|:)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
                r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})",
            ]

            page_text = soup.get_text()
            company_name = symbol

            # Try to get company name from page title
            title_tag = soup.find("h1", class_="h2")
            if title_tag:
                company_name = title_tag.get_text(strip=True)

            today = datetime.utcnow().date()

            for pattern in result_patterns:
                matches = re.findall(pattern, page_text, re.IGNORECASE)
                for match in matches:
                    parsed_date = self._parse_date_string(match)
                    if parsed_date and parsed_date >= today:
                        events.append(EarningsEvent(
                            symbol=symbol,
                            company_name=company_name,
                            earnings_date=parsed_date,
                            earnings_time="UNKNOWN",
                            expected_eps=None,
                            previous_eps=None,
                            source="screener_in",
                        ))
                        logger.debug(f"[{symbol}] Screener.in earnings: {parsed_date}")

            # De-duplicate dates
            seen_dates = set()
            unique_events = []
            for e in events:
                if e.earnings_date not in seen_dates:
                    seen_dates.add(e.earnings_date)
                    unique_events.append(e)
            return unique_events

        except Exception as e:
            logger.debug(f"[{symbol}] Screener.in scraping failed: {e}")
            return []

    # ── Internal: Investing.com earnings calendar ──────────────────────────

    def _fetch_investing_earnings_week(self, days_ahead: int = 7) -> List[EarningsEvent]:
        """
        Scrapes the Investing.com earnings calendar for the upcoming week.
        Returns earnings for all symbols — caller filters by watchlist.

        Note: Investing.com has anti-scraping protection.
        This uses the public JSON endpoint which is more stable.
        """
        events = []
        try:
            # Investing.com public earnings API (no authentication needed)
            today = datetime.utcnow().date()
            end_date = today + timedelta(days=days_ahead)

            url = "https://api.investing.com/api/financialdata/earnings/calendar"
            params = {
                "dateFrom": today.strftime("%Y-%m-%d"),
                "dateTo": end_date.strftime("%Y-%m-%d"),
                "country[]": ["6", "14"],  # 6 = India, 14 = USA
            }
            headers = {
                **self._HEADERS,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://www.investing.com/earnings-calendar/",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }

            resp = self._session.get(url, params=params, headers=headers, timeout=self._HTTP_TIMEOUT)
            if resp.status_code != 200:
                return []

            data = resp.json()
            items = data.get("data", []) if isinstance(data, dict) else []

            for item in items:
                try:
                    date_str = item.get("date", "")
                    company = item.get("name", "")
                    symbol_raw = item.get("symbol", "")
                    eps_est = item.get("epsEstimate")
                    eps_prev = item.get("epsPrevious")
                    release_time = item.get("releaseType", "UNKNOWN")

                    parsed_date = self._parse_date_string(date_str)
                    if not parsed_date or parsed_date < today:
                        continue

                    # Normalise release time
                    earnings_time = "UNKNOWN"
                    if release_time and "before" in str(release_time).lower():
                        earnings_time = "BMO"
                    elif release_time and "after" in str(release_time).lower():
                        earnings_time = "AMC"

                    events.append(EarningsEvent(
                        symbol=symbol_raw,
                        company_name=company,
                        earnings_date=parsed_date,
                        earnings_time=earnings_time,
                        expected_eps=float(eps_est) if eps_est else None,
                        previous_eps=float(eps_prev) if eps_prev else None,
                        source="investing_com",
                    ))
                except Exception:
                    continue

            logger.debug(f"Investing.com: {len(events)} earnings events for next {days_ahead} days")

        except Exception as e:
            logger.debug(f"Investing.com earnings calendar failed: {e}")

        return events

    # ── Internal: Date parsing ─────────────────────────────────────────────

    def _parse_date_string(self, date_str: str) -> Optional[date]:
        """Parses a variety of date string formats into a date object."""
        if not date_str:
            return None

        date_str = date_str.strip()

        # Common formats
        formats = [
            "%Y-%m-%d",
            "%d %b %Y",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%B %d, %Y",
            "%d %B %Y",
            "%b %d, %Y",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        # Try extracting a date-like pattern from the string
        m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', date_str)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass

        return None

    # ── Public: get_upcoming_earnings ─────────────────────────────────────

    def get_upcoming_earnings(
        self,
        symbols: List[str],
        days_ahead: int = 7,
    ) -> Dict[str, EarningsEvent]:
        """
        Fetches upcoming earnings dates for all given symbols.

        Source waterfall per symbol:
          1. Database cache (if not expired)
          2. yfinance .earnings_dates or .calendar
          3. Screener.in (Indian stocks only)
          4. Investing.com calendar (bulk fetch, then filter)

        Args:
            symbols: List of stock symbols to check
            days_ahead: How many calendar days to look ahead

        Returns:
            Dict mapping symbol → EarningsEvent for the NEAREST upcoming earnings.
            Symbols with no upcoming earnings are absent from the dict.
        """
        results: Dict[str, EarningsEvent] = {}
        symbols_needing_fetch: List[str] = []

        # ── Check DB cache first ───────────────────────────────────────────
        for symbol in symbols:
            cached = self._load_earnings_from_db(symbol, days_ahead=days_ahead)
            if cached:
                # Use nearest upcoming event
                results[symbol] = cached[0]
                logger.debug(f"[{symbol}] Earnings from cache: {cached[0].earnings_date}")
            else:
                symbols_needing_fetch.append(symbol)

        if not symbols_needing_fetch:
            return results

        logger.info(f"Fetching earnings calendar for {len(symbols_needing_fetch)} symbols")

        # ── Bulk fetch from Investing.com (covers many symbols at once) ────
        investing_events: List[EarningsEvent] = []
        try:
            investing_events = self._fetch_investing_earnings_week(days_ahead=days_ahead)
        except Exception as e:
            logger.debug(f"Investing.com bulk fetch failed: {e}")

        # Build a lookup from Investing.com data
        # Map company name/symbol → EarningsEvent
        investing_lookup: Dict[str, EarningsEvent] = {}
        for event in investing_events:
            if event.symbol:
                investing_lookup[event.symbol.upper()] = event
            if event.company_name:
                investing_lookup[event.company_name.upper()] = event

        # ── Per-symbol fetch ───────────────────────────────────────────────
        today = datetime.utcnow().date()
        future_cutoff = today + timedelta(days=days_ahead)

        for symbol in symbols_needing_fetch:
            base = symbol.replace(".NS", "").replace(".BO", "")
            symbol_events: List[EarningsEvent] = []

            # Source 1: yfinance
            try:
                yf_events = self._fetch_yfinance_earnings(symbol)
                symbol_events.extend(yf_events)
            except Exception as e:
                logger.debug(f"[{symbol}] yfinance earnings failed: {e}")

            # Source 2: Screener.in (India only)
            if not symbol_events and symbol.endswith((".NS", ".BO")):
                try:
                    screener_events = self._fetch_screener_earnings(symbol)
                    symbol_events.extend(screener_events)
                except Exception as e:
                    logger.debug(f"[{symbol}] Screener.in failed: {e}")

            # Source 3: Check Investing.com lookup
            if not symbol_events:
                iv_event = (
                    investing_lookup.get(base.upper())
                    or investing_lookup.get(symbol.upper())
                )
                if iv_event:
                    # Re-tag the symbol correctly
                    iv_event.symbol = symbol
                    symbol_events.append(iv_event)

            # Filter to within days_ahead window
            symbol_events = [
                e for e in symbol_events
                if today <= e.earnings_date <= future_cutoff
            ]

            # Sort by date ascending — nearest first
            symbol_events.sort(key=lambda e: e.earnings_date)

            if symbol_events:
                nearest = symbol_events[0]
                results[symbol] = nearest
                self._save_earnings_event(nearest)
                logger.info(
                    f"[{symbol}] Upcoming earnings: {nearest.earnings_date} "
                    f"({nearest.days_until}d away, source={nearest.source})"
                )
            else:
                logger.debug(f"[{symbol}] No upcoming earnings in next {days_ahead} days")

            # Polite scraping delay
            time.sleep(0.5)

        return results

    # ── Public: has_earnings_risk ──────────────────────────────────────────

    def has_earnings_risk(self, symbol: str) -> EarningsRisk:
        """
        Determines the earnings-based risk level for a single symbol.

        This is the primary method called by EventRiskAgent before every trade.

        Risk levels and their effects:
          NONE  (>7 days away): Position size unchanged (multiplier = 1.0)
          LOW   (3-7 days):     Position size × 0.7 (30% reduction)
          HIGH  (<72 hours):    Position size × 0.5 (50% reduction)
          BLOCK (<24 hours):    Trade completely blocked (multiplier = 0.0)

        Returns:
            EarningsRisk object with full details and position_size_multiplier.
        """
        # Check DB cache for this specific risk assessment
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT data_json, expires_at FROM earnings_risk_cache WHERE symbol=?",
                    (symbol,),
                ).fetchone()
            if row:
                expires = datetime.fromisoformat(row[1])
                if datetime.utcnow() < expires:
                    cached_data = json.loads(row[0])
                    event_data = cached_data.pop("earnings_event", None)
                    event = None
                    if event_data:
                        try:
                            event = EarningsEvent(
                                symbol=event_data["symbol"],
                                company_name=event_data.get("company_name", symbol),
                                earnings_date=date.fromisoformat(event_data["earnings_date"]),
                                earnings_time=event_data.get("earnings_time", "UNKNOWN"),
                                expected_eps=event_data.get("expected_eps"),
                                previous_eps=event_data.get("previous_eps"),
                                source=event_data.get("source", "cache"),
                            )
                        except Exception:
                            pass
                    return EarningsRisk(earnings_event=event, **cached_data)
        except Exception as e:
            logger.debug(f"[{symbol}] Earnings risk cache read failed: {e}")

        # Fetch fresh earnings data
        upcoming = self.get_upcoming_earnings([symbol], days_ahead=30)
        event = upcoming.get(symbol)

        if event is None:
            risk = EarningsRisk(
                symbol=symbol,
                has_risk=False,
                days_until_earnings=None,
                hours_until_earnings=None,
                risk_level=EarningsRiskLevel.NONE.value,
                position_size_multiplier=1.0,
                earnings_event=None,
                reasoning=f"[{symbol}] No upcoming earnings in the next 30 days — trade freely.",
            )
        else:
            days = event.days_until
            hours = event.hours_until
            date_str = event.earnings_date.strftime("%d %b %Y")

            if hours <= EARNINGS_BLOCK_HOURS:
                risk_level = EarningsRiskLevel.BLOCK
                multiplier = 0.0
                reasoning = (
                    f"[{symbol}] EARNINGS IN {hours:.0f} HOURS ({date_str}). "
                    f"Trade BLOCKED — extreme event risk."
                )
            elif hours <= EARNINGS_HIGH_RISK_HOURS:
                risk_level = EarningsRiskLevel.HIGH
                multiplier = 0.5
                reasoning = (
                    f"[{symbol}] Earnings in {days} days ({date_str}). "
                    f"HIGH RISK — position size reduced to 50%."
                )
            elif days <= EARNINGS_LOW_RISK_DAYS:
                risk_level = EarningsRiskLevel.LOW
                multiplier = 0.7
                reasoning = (
                    f"[{symbol}] Earnings in {days} days ({date_str}). "
                    f"LOW RISK — position size reduced to 70%."
                )
            else:
                risk_level = EarningsRiskLevel.NONE
                multiplier = 1.0
                reasoning = (
                    f"[{symbol}] Earnings in {days} days ({date_str}). "
                    f"Far enough away — trade normally."
                )

            risk = EarningsRisk(
                symbol=symbol,
                has_risk=(risk_level != EarningsRiskLevel.NONE),
                days_until_earnings=days,
                hours_until_earnings=hours,
                risk_level=risk_level.value,
                position_size_multiplier=multiplier,
                earnings_event=event,
                reasoning=reasoning,
            )

        logger.info(risk.reasoning)

        # Cache the risk assessment
        try:
            now = datetime.utcnow()
            # Cache for 1 hour — re-check frequently when earnings are close
            ttl = 3600 if risk.days_until_earnings is None or risk.days_until_earnings > 3 else 600
            expires = now + timedelta(seconds=ttl)
            risk_dict = risk.to_dict()
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO earnings_risk_cache
                        (symbol, data_json, cached_at, expires_at)
                    VALUES (?, ?, ?, ?)
                """, (symbol, json.dumps(risk_dict), now.isoformat(), expires.isoformat()))
                conn.commit()
        except Exception as e:
            logger.debug(f"[{symbol}] Earnings risk cache write failed: {e}")

        return risk

    # ── Public: get_earnings_risk_for_watchlist ────────────────────────────

    def get_earnings_risk_for_watchlist(
        self,
        symbols: List[str],
    ) -> Dict[str, EarningsRisk]:
        """
        Checks earnings risk for all symbols in the watchlist in one pass.
        More efficient than calling has_earnings_risk() in a loop because it
        does a single Investing.com bulk fetch first.

        Returns:
            Dict mapping symbol → EarningsRisk
        """
        logger.info(f"Checking earnings risk for {len(symbols)} symbols")
        results = {}

        # Bulk fetch upcoming earnings for all symbols at once
        upcoming = self.get_upcoming_earnings(symbols, days_ahead=30)

        for symbol in symbols:
            event = upcoming.get(symbol)
            if event is None:
                results[symbol] = EarningsRisk(
                    symbol=symbol,
                    has_risk=False,
                    days_until_earnings=None,
                    hours_until_earnings=None,
                    risk_level=EarningsRiskLevel.NONE.value,
                    position_size_multiplier=1.0,
                    earnings_event=None,
                    reasoning=f"[{symbol}] No earnings in next 30 days.",
                )
            else:
                # Re-use has_earnings_risk logic (which will find cached result)
                results[symbol] = self.has_earnings_risk(symbol)

        blocked = [s for s, r in results.items() if r.risk_level == EarningsRiskLevel.BLOCK.value]
        high_risk = [s for s, r in results.items() if r.risk_level == EarningsRiskLevel.HIGH.value]

        if blocked:
            logger.warning(f"EARNINGS BLOCKED ({len(blocked)} symbols): {blocked}")
        if high_risk:
            logger.info(f"Earnings HIGH RISK ({len(high_risk)} symbols): {high_risk}")

        return results
