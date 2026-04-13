"""
data/validators/data_validator.py
===================================
The gatekeeper. Validates all data quality before any analysis begins.

This is THE MOST CRITICAL FILE in the data layer.
A single bad data point can cause:
  - False BUY signals on stale prices
  - Crash in ML models due to NaN values
  - Division by zero in technical indicators
  - Missed trades due to volume filter on bad data

Every analysis cycle MUST call validate_all_data_for_symbol() first.
If validation fails, that symbol is skipped for this cycle.

Rules:
  - Price data must be fresh (within 15 min during market hours)
  - Historical data must have at least 252 trading days (1 year for ML)
  - No gaps > 5 consecutive days in OHLCV data
  - Volume must be present for >90% of rows
  - News must have valid timestamps (not future-dated)

Usage:
    from data.validators.data_validator import DataValidator
    validator = DataValidator()
    result = validator.validate_all_data_for_symbol(
        symbol="RELIANCE.NS",
        price_data=price_data,
        news_data=news_articles,
        historical_data=ohlcv_df,
    )
    if not result.is_valid:
        logger.warning(f"Validation failed: {result.reason}")
        # Skip this symbol in this analysis cycle
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Set

import pandas as pd
import numpy as np

from data.collectors.price_collector import PriceData
from data.collectors.news_collector import NewsArticle
from config.constants import (
    MIN_TRADING_DAYS_HISTORY,
    MAX_CONSECUTIVE_MISSING_DAYS,
    PRICE_MAX_AGE_MINUTES,
    PRICE_SPIKE_THRESHOLD,
    MIN_DAILY_VOLUME,
    MIN_DAILY_VOLUME_US,
    MIN_NEWS_ARTICLES,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class ValidationIssue:
    """A single validation problem found during data checks."""
    severity: str       # "ERROR" | "WARNING"
    category: str       # "PRICE" | "HISTORY" | "NEWS" | "VOLUME"
    message: str
    
    def __str__(self) -> str:
        return f"[{self.severity}] {self.category}: {self.message}"


@dataclass
class ValidationResult:
    """
    Complete validation result for a symbol.
    
    If is_valid == False, the symbol MUST be skipped in this trading cycle.
    Warnings are logged but don't block trading.
    """
    symbol: str
    is_valid: bool
    reason: str                              # Primary reason for failure (if not valid)
    issues_found: List[ValidationIssue] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    data_quality_score: float = 0.0          # 0-1, higher = better quality
    
    def add_error(self, category: str, message: str) -> None:
        """Adds a blocking error — marks validation as failed."""
        self.issues_found.append(ValidationIssue("ERROR", category, message))
        self.is_valid = False
        if not self.reason:
            self.reason = message
    
    def add_warning(self, category: str, message: str) -> None:
        """Adds a non-blocking warning — doesn't fail validation."""
        self.issues_found.append(ValidationIssue("WARNING", category, message))
        self.warnings.append(message)
    
    def summary(self) -> str:
        """Returns a human-readable summary for logging."""
        status = "✓ VALID" if self.is_valid else "✗ INVALID"
        errors = [i for i in self.issues_found if i.severity == "ERROR"]
        warnings = [i for i in self.issues_found if i.severity == "WARNING"]
        
        parts = [
            f"[{self.symbol}] Validation: {status}",
            f"Quality: {self.data_quality_score:.2f}",
        ]
        if errors:
            parts.append(f"Errors: {len(errors)}")
        if warnings:
            parts.append(f"Warnings: {len(warnings)}")
        if not self.is_valid:
            parts.append(f"Reason: {self.reason}")
        
        return " | ".join(parts)


# ═══════════════════════════════════════════════════════════════
# DATA VALIDATOR
# ═══════════════════════════════════════════════════════════════

class DataValidator:
    """
    Validates data quality before it enters the trading pipeline.
    
    Every validation check is independent and adds to either the
    error list (blocking) or warning list (non-blocking).
    
    The final data_quality_score is used by the Decision Agent to
    adjust confidence — lower quality data = lower confidence.
    """
    
    # Minimum volume presence required (as fraction of rows)
    _MIN_VOLUME_PRESENCE = 0.90
    
    # Minimum data quality score to pass (0-1)
    _MIN_QUALITY_SCORE = 0.30
    
    def __init__(self):
        self._market_hours_cache: dict = {}
    
    # ── Internal: Helpers ──────────────────────────────────────────────────
    
    def _is_market_hours(self, timestamp: datetime, symbol: str) -> bool:
        """
        Checks if the given timestamp falls within market trading hours.
        Used to determine if price data staleness is acceptable.
        
        Outside market hours (nights, weekends), 60-minute staleness is OK.
        During market hours, only 15-minute staleness is acceptable.
        """
        from config.constants import NSE_HOURS, NYSE_HOURS, TZ_INDIA, TZ_US_EAST
        
        # Determine which market
        if symbol.endswith((".NS", ".BO")):
            hours = NSE_HOURS
            tz = TZ_INDIA
        else:
            hours = NYSE_HOURS
            tz = TZ_US_EAST
        
        # Convert timestamp to market timezone
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        local_time = timestamp.astimezone(tz)
        
        # Check if it's a weekday
        if local_time.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        
        # Check if within trading hours
        current_time = local_time.time()
        return hours.open_time <= current_time <= hours.close_time
    
    def _check_for_consecutive_missing_days(
        self,
        df: pd.DataFrame,
        max_gap: int = MAX_CONSECUTIVE_MISSING_DAYS,
    ) -> Optional[int]:
        """
        Detects the longest gap in the DatetimeIndex of a DataFrame.
        
        Returns:
            The length of the longest gap in business days, or None if no issue.
            If return value > max_gap, that's a validation error.
        """
        if len(df) < 2:
            return None
        
        # Calculate day-to-day differences
        dates = pd.to_datetime(df.index)
        diffs = dates.to_series().diff().dt.days.dropna()
        
        # Business days typically have 1-3 day gaps (weekend = 3)
        # A 7+ day gap indicates missing data
        if diffs.empty:
            return None
        
        max_gap_found = int(diffs.max())
        if max_gap_found > max_gap:
            return max_gap_found
        return None
    
    def _calculate_data_quality_score(self, result: ValidationResult) -> float:
        """
        Computes a 0-1 quality score based on issues found.
        
        Scoring:
          - Start at 1.0
          - Each ERROR: -0.3
          - Each WARNING: -0.1
          - Floor at 0.0
        """
        score = 1.0
        for issue in result.issues_found:
            if issue.severity == "ERROR":
                score -= 0.3
            elif issue.severity == "WARNING":
                score -= 0.1
        return max(0.0, score)
    
    # ── Validation: Price Data ─────────────────────────────────────────────
    
    def _validate_price_data(
        self,
        symbol: str,
        price_data: PriceData,
        result: ValidationResult,
    ) -> None:
        """
        Validates real-time/current price data.
        
        Checks:
          ✓ Price > 0
          ✓ Timestamp is recent (within 15 min during market hours, 60 min otherwise)
          ✓ Price hasn't spiked >20% from previous close (bad data / circuit breaker)
          ✓ Volume meets minimum liquidity threshold
        """
        # ── Check 1: Price must be positive ────────────────────────────────
        if price_data.current_price <= 0:
            result.add_error(
                "PRICE",
                f"Invalid price: {price_data.current_price}. "
                f"Price must be positive."
            )
            return  # No point checking further if price is invalid
        
        # ── Check 2: Timestamp freshness ───────────────────────────────────
        now = datetime.now(timezone.utc)
        timestamp = price_data.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        age_minutes = (now - timestamp).total_seconds() / 60
        
        is_market_open = self._is_market_hours(now, symbol)
        max_age = PRICE_MAX_AGE_MINUTES if is_market_open else 60
        
        if age_minutes > max_age:
            result.add_error(
                "PRICE",
                f"Stale price data: {age_minutes:.0f} minutes old "
                f"(max allowed: {max_age} min {'during market hours' if is_market_open else 'outside market hours'}). "
                f"Timestamp: {timestamp.isoformat()}"
            )
        elif age_minutes > max_age * 0.7:
            # Warning if approaching staleness threshold
            result.add_warning(
                "PRICE",
                f"Price data approaching staleness: {age_minutes:.0f} min old "
                f"(threshold: {max_age} min)"
            )
        
        # ── Check 3: Suspicious price spike ────────────────────────────────
        if price_data.close and price_data.close > 0:
            change_pct = abs(
                (price_data.current_price - price_data.close) / price_data.close
            )
            if change_pct > PRICE_SPIKE_THRESHOLD:
                result.add_error(
                    "PRICE",
                    f"Suspicious price spike: {change_pct:.1%} change from previous close "
                    f"({price_data.close:.2f} → {price_data.current_price:.2f}). "
                    f"Possible bad data or circuit breaker — skipping for safety."
                )
        
        # ── Check 4: Minimum volume (liquidity check) ──────────────────────
        is_us = not symbol.endswith((".NS", ".BO"))
        min_vol = MIN_DAILY_VOLUME_US if is_us else MIN_DAILY_VOLUME
        
        # Only check if volume data is available (Alpha Vantage doesn't always provide it)
        if price_data.volume > 0 and price_data.volume < min_vol:
            result.add_error(
                "VOLUME",
                f"Insufficient liquidity: volume={price_data.volume:,} "
                f"< minimum {min_vol:,}. Stock may be too illiquid to trade safely."
            )
        elif price_data.volume == 0 and price_data.source != "alpha_vantage":
            # Zero volume during market hours is suspicious
            if is_market_open:
                result.add_warning(
                    "VOLUME",
                    f"Zero volume reported. Data source: {price_data.source}"
                )
    
    # ── Validation: Historical Data ────────────────────────────────────────
    
    def _validate_historical_data(
        self,
        symbol: str,
        historical_data: pd.DataFrame,
        result: ValidationResult,
    ) -> None:
        """
        Validates OHLCV historical DataFrame.
        
        Checks:
          ✓ At least 252 trading days (1 year minimum for ML models)
          ✓ No gaps > 5 consecutive days
          ✓ No zero or negative Close prices
          ✓ Volume present for >90% of rows
        """
        if historical_data is None or len(historical_data) == 0:
            result.add_error(
                "HISTORY",
                "Historical data is empty or None. Cannot proceed with analysis."
            )
            return
        
        df = historical_data
        
        # ── Check 1: Minimum row count ─────────────────────────────────────
        if len(df) < MIN_TRADING_DAYS_HISTORY:
            result.add_error(
                "HISTORY",
                f"Insufficient history: {len(df)} days < minimum {MIN_TRADING_DAYS_HISTORY} days. "
                f"Need at least 1 year of data for ML models."
            )
        elif len(df) < MIN_TRADING_DAYS_HISTORY * 1.2:
            # Warning if only barely meeting minimum
            result.add_warning(
                "HISTORY",
                f"Limited history: {len(df)} days (minimum is {MIN_TRADING_DAYS_HISTORY}). "
                f"ML model accuracy may be reduced."
            )
        
        # ── Check 2: Required columns exist ────────────────────────────────
        required_cols = ["Open", "High", "Low", "Close", "Volume"]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            result.add_error(
                "HISTORY",
                f"Missing required columns: {missing}. "
                f"Cannot calculate technical indicators."
            )
            return  # Can't continue validation without these columns
        
        # ── Check 3: No zero or negative prices ────────────────────────────
        for col in ["Open", "High", "Low", "Close"]:
            invalid_count = (df[col] <= 0).sum()
            if invalid_count > 0:
                result.add_error(
                    "HISTORY",
                    f"Found {invalid_count} rows with invalid {col} prices (≤ 0). "
                    f"Data quality is compromised."
                )
        
        # ── Check 4: Check for large gaps in dates ─────────────────────────
        max_gap = self._check_for_consecutive_missing_days(df)
        if max_gap:
            result.add_error(
                "HISTORY",
                f"Data gap detected: {max_gap} consecutive missing days "
                f"(max allowed: {MAX_CONSECUTIVE_MISSING_DAYS}). "
                f"Historical data is incomplete."
            )
        
        # ── Check 5: Volume presence ───────────────────────────────────────
        if "Volume" in df.columns:
            vol_present = (df["Volume"] > 0).sum()
            vol_presence_pct = vol_present / len(df)
            
            if vol_presence_pct < self._MIN_VOLUME_PRESENCE:
                result.add_error(
                    "VOLUME",
                    f"Volume data missing for {(1-vol_presence_pct)*100:.1f}% of rows "
                    f"(need at least {self._MIN_VOLUME_PRESENCE*100:.0f}%). "
                    f"Volume-based indicators will be unreliable."
                )
            elif vol_presence_pct < 0.95:
                result.add_warning(
                    "VOLUME",
                    f"Volume data missing for {(1-vol_presence_pct)*100:.1f}% of rows. "
                    f"Some volume indicators may be less accurate."
                )
        
        # ── Check 6: NaN/inf values ────────────────────────────────────────
        nan_count = df[required_cols].isna().sum().sum()
        if nan_count > 0:
            result.add_error(
                "HISTORY",
                f"Found {nan_count} NaN values across OHLCV columns. "
                f"Data cleaning failed — cannot use for analysis."
            )
        
        inf_count = np.isinf(df[required_cols].select_dtypes(include=[np.number])).sum().sum()
        if inf_count > 0:
            result.add_error(
                "HISTORY",
                f"Found {inf_count} infinite values across OHLCV columns. "
                f"Data is corrupted."
            )
        
        # ── Check 7: Date range sanity ─────────────────────────────────────
        try:
            earliest = df.index.min()
            latest = df.index.max()
            
            # Make sure dates are in the past (not future-dated)
            today = pd.Timestamp.now(tz=timezone.utc)
            if latest > today:
                result.add_error(
                    "HISTORY",
                    f"Historical data contains future dates: latest={latest.date()}. "
                    f"Data source error."
                )
            
            # Check date ordering
            if earliest >= latest:
                result.add_error(
                    "HISTORY",
                    f"Date index is not properly ordered: "
                    f"earliest={earliest.date()}, latest={latest.date()}"
                )
        except Exception as e:
            result.add_warning(
                "HISTORY",
                f"Could not validate date range: {e}"
            )
    
    # ── Validation: News Data ──────────────────────────────────────────────
    
    def _validate_news_data(
        self,
        symbol: str,
        news_data: List[NewsArticle],
        result: ValidationResult,
    ) -> None:
        """
        Validates news article data.
        
        Checks:
          ✓ At least 1 article in last 48 hours (WARNING if not met)
          ✓ No articles with future-dated timestamps
          ✓ Articles have valid titles and descriptions
        """
        if not news_data:
            result.add_warning(
                "NEWS",
                f"No news articles found. Sentiment analysis will default to NEUTRAL. "
                f"Consider this a low-information trade."
            )
            return
        
        # ── Check 1: Article count ─────────────────────────────────────────
        if len(news_data) < MIN_NEWS_ARTICLES:
            result.add_warning(
                "NEWS",
                f"Only {len(news_data)} news article(s) found "
                f"(recommend at least {MIN_NEWS_ARTICLES} for reliable sentiment). "
                f"Sentiment confidence will be reduced."
            )
        
        # ── Check 2: Check for future-dated articles ───────────────────────
        now = datetime.now(timezone.utc)
        future_dated = []
        
        for article in news_data:
            pub = article.published_at
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            
            if pub > now:
                future_dated.append(article.title[:50])
        
        if future_dated:
            result.add_warning(
                "NEWS",
                f"Found {len(future_dated)} article(s) with future publish dates. "
                f"Data source timestamps may be incorrect."
            )
        
        # ── Check 3: Article quality ───────────────────────────────────────
        empty_title = sum(1 for a in news_data if not a.title or len(a.title) < 5)
        empty_desc = sum(1 for a in news_data if not a.description or len(a.description) < 10)
        
        if empty_title > len(news_data) * 0.3:
            result.add_warning(
                "NEWS",
                f"{empty_title}/{len(news_data)} articles have empty/short titles. "
                f"Sentiment quality may be impacted."
            )
        
        if empty_desc > len(news_data) * 0.5:
            result.add_warning(
                "NEWS",
                f"{empty_desc}/{len(news_data)} articles have empty/short descriptions. "
                f"Sentiment analysis may be limited."
            )
        
        # ── Check 4: Recency distribution ──────────────────────────────────
        very_recent = sum(1 for a in news_data if a.age_hours <= 6)
        recent = sum(1 for a in news_data if 6 < a.age_hours <= 24)
        old = sum(1 for a in news_data if a.age_hours > 48)
        
        if very_recent == 0 and recent == 0:
            result.add_warning(
                "NEWS",
                f"All {len(news_data)} articles are older than 24 hours. "
                f"Sentiment may not reflect current market conditions."
            )
        
        if old > len(news_data) * 0.7:
            result.add_warning(
                "NEWS",
                f"{old}/{len(news_data)} articles are older than 48 hours. "
                f"Consider reducing weight of sentiment signal."
            )
    
    # ── Public: Master Validation Method ───────────────────────────────────
    
    def validate_all_data_for_symbol(
        self,
        symbol: str,
        price_data: PriceData,
        news_data: List[NewsArticle],
        historical_data: pd.DataFrame,
    ) -> ValidationResult:
        """
        **THE GATEKEEPER METHOD**
        
        This is called at the beginning of every analysis cycle for every symbol.
        If this returns is_valid=False, the entire symbol is skipped for this cycle.
        
        Runs all validation checks across all data types and returns a comprehensive
        ValidationResult with errors, warnings, and a data quality score.
        
        Args:
            symbol: Stock symbol being validated
            price_data: Current/recent price data from PriceCollector
            news_data: List of news articles from NewsCollector
            historical_data: OHLCV DataFrame from PriceCollector
        
        Returns:
            ValidationResult with is_valid flag, errors, warnings, and quality score.
            
        Example:
            result = validator.validate_all_data_for_symbol(...)
            if not result.is_valid:
                logger.warning(f"Skipping {symbol}: {result.reason}")
                return  # Skip this symbol in this cycle
            
            # Proceed with analysis using validated data
            confidence_penalty = 1.0 - (1.0 - result.data_quality_score) * 0.5
            final_confidence = base_confidence * confidence_penalty
        """
        logger.info(f"[{symbol}] Running data validation checks...")
        
        result = ValidationResult(
            symbol=symbol,
            is_valid=True,
            reason="",
        )
        
        # ── Run all validation checks ──────────────────────────────────────
        try:
            self._validate_price_data(symbol, price_data, result)
        except Exception as e:
            logger.error(f"[{symbol}] Price validation crashed: {e}", exc_info=True)
            result.add_error("PRICE", f"Price validation failed: {e}")
        
        try:
            self._validate_historical_data(symbol, historical_data, result)
        except Exception as e:
            logger.error(f"[{symbol}] Historical validation crashed: {e}", exc_info=True)
            result.add_error("HISTORY", f"Historical validation failed: {e}")
        
        try:
            self._validate_news_data(symbol, news_data, result)
        except Exception as e:
            logger.error(f"[{symbol}] News validation crashed: {e}", exc_info=True)
            result.add_warning("NEWS", f"News validation failed: {e}")
        
        # ── Calculate final quality score ──────────────────────────────────
        result.data_quality_score = self._calculate_data_quality_score(result)
        
        # ── Final quality threshold check ──────────────────────────────────
        if result.data_quality_score < self._MIN_QUALITY_SCORE:
            result.is_valid = False
            if not result.reason:
                result.reason = (
                    f"Data quality too low: {result.data_quality_score:.2f} "
                    f"< minimum {self._MIN_QUALITY_SCORE}"
                )
        
        # ── Log result ─────────────────────────────────────────────────────
        if result.is_valid:
            logger.info(result.summary())
            if result.warnings:
                for warning in result.warnings:
                    logger.warning(f"[{symbol}] {warning}")
        else:
            logger.error(result.summary())
            for issue in result.issues_found:
                if issue.severity == "ERROR":
                    logger.error(f"[{symbol}] {issue}")
        
        return result
    
    # ── Public: Quick validation methods ───────────────────────────────────
    
    def quick_validate_price(self, symbol: str, price_data: PriceData) -> bool:
        """
        Fast price-only validation for pre-screening.
        Returns True if price data looks usable, False otherwise.
        """
        if price_data.current_price <= 0:
            return False
        
        now = datetime.now(timezone.utc)
        ts = price_data.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        
        age_minutes = (now - ts).total_seconds() / 60
        is_market_open = self._is_market_hours(now, symbol)
        max_age = PRICE_MAX_AGE_MINUTES if is_market_open else 60
        
        return age_minutes <= max_age
    
    def quick_validate_history(self, historical_data: pd.DataFrame) -> bool:
        """
        Fast historical data validation for pre-screening.
        Returns True if history looks minimally usable.
        """
        if historical_data is None or len(historical_data) < MIN_TRADING_DAYS_HISTORY:
            return False
        
        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(c in historical_data.columns for c in required):
            return False
        
        if historical_data["Close"].isna().any():
            return False
        
        if (historical_data["Close"] <= 0).any():
            return False
        
        return True
