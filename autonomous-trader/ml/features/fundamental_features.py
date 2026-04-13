"""
ml/features/fundamental_features.py
=====================================
Extracts fundamental financial metrics for stocks.

Why fundamentals matter:
  - Technical analysis tells you WHEN to buy/sell (timing)
  - Fundamental analysis tells you WHAT to buy (value/quality)
  
A stock with great technicals but terrible fundamentals = short-term trade only.
A stock with great fundamentals but poor technicals = wait for better entry.

Data source: yfinance ticker.info (free, no API key)

Features extracted:
  - Valuation: P/E, P/B, P/S ratios
  - Financial health: Debt/Equity, Current Ratio
  - Growth: Revenue growth, Earnings growth
  - Profitability: Profit margin, ROE, ROA
  - Income: Dividend yield

Output: FundamentalFeatures dataclass + fundamental_score (0-10)

Usage:
    from ml.features.fundamental_features import FundamentalFeatureExtractor
    extractor = FundamentalFeatureExtractor()
    features = extractor.extract("RELIANCE.NS")
    print(f"Fundamental score: {features.fundamental_score}/10")
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any
import yfinance as yf
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
import logging

from config.constants import (
    FUNDAMENTAL_PE_MAX,
    FUNDAMENTAL_DEBT_EQUITY_MAX,
    FUNDAMENTAL_REVENUE_GROWTH_MIN,
    FUNDAMENTAL_PROFIT_MARGIN_MIN,
    FUNDAMENTAL_ROE_MIN,
    FUNDAMENTAL_MIN_METRICS,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class FundamentalFeatures:
    """
    Complete fundamental metrics for a stock.
    
    All fields are Optional because not all stocks have all data
    (especially Indian mid/small caps may be missing some metrics).
    """
    symbol: str
    
    # Valuation ratios
    pe_ratio: Optional[float] = None           # Price-to-Earnings
    pb_ratio: Optional[float] = None           # Price-to-Book
    ps_ratio: Optional[float] = None           # Price-to-Sales
    
    # Financial health
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None      # Current Assets / Current Liabilities
    quick_ratio: Optional[float] = None        # (Current Assets - Inventory) / Current Liabilities
    
    # Growth metrics (YoY %)
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    
    # Profitability (%)
    profit_margin: Optional[float] = None      # Net profit / Revenue
    operating_margin: Optional[float] = None   # Operating profit / Revenue
    gross_margin: Optional[float] = None       # Gross profit / Revenue
    
    # Returns (%)
    roe: Optional[float] = None                # Return on Equity
    roa: Optional[float] = None                # Return on Assets
    roic: Optional[float] = None               # Return on Invested Capital
    
    # Dividend
    dividend_yield: Optional[float] = None     # Annual dividend / Price (%)
    payout_ratio: Optional[float] = None       # Dividend / Earnings
    
    # Market data
    market_cap: Optional[float] = None
    enterprise_value: Optional[float] = None
    
    # Scoring
    fundamental_score: float = 5.0             # 0-10 composite score
    metrics_available: int = 0                 # How many metrics had data
    scoring_breakdown: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def to_feature_vector(self) -> Dict[str, float]:
        """
        Returns a flat dict suitable for ML model input.
        All None values are replaced with sensible defaults.
        """
        return {
            "pe_ratio": self.pe_ratio or 20.0,  # Median market P/E
            "pb_ratio": self.pb_ratio or 3.0,
            "ps_ratio": self.ps_ratio or 2.0,
            "debt_to_equity": self.debt_to_equity or 1.0,
            "current_ratio": self.current_ratio or 1.5,
            "revenue_growth": self.revenue_growth or 0.0,
            "earnings_growth": self.earnings_growth or 0.0,
            "profit_margin": self.profit_margin or 10.0,
            "operating_margin": self.operating_margin or 15.0,
            "roe": self.roe or 15.0,
            "roa": self.roa or 5.0,
            "dividend_yield": self.dividend_yield or 0.0,
            "fundamental_score": self.fundamental_score,
        }


# ═══════════════════════════════════════════════════════════════
# FUNDAMENTAL FEATURE EXTRACTOR
# ═══════════════════════════════════════════════════════════════

class FundamentalFeatureExtractor:
    """
    Fetches and processes fundamental financial data for stocks.
    
    Handles missing data gracefully — Indian stocks often lack complete
    fundamental data, especially mid/small caps.
    """
    
    # Cache to avoid repeated yfinance calls in the same session
    _cache: Dict[str, FundamentalFeatures] = {}
    
    def __init__(self):
        """Initialises the extractor."""
        pass
    
    # ── Internal: yfinance fetching ────────────────────────────────────────
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        reraise=False,
    )
    def _fetch_yfinance_info(self, symbol: str) -> Dict[str, Any]:
        """
        Fetches ticker.info from yfinance with retry logic.
        ticker.info is heavy (scrapes Yahoo Finance page) so we cache it.
        """
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if info is None or len(info) == 0:
                logger.warning(f"[{symbol}] yfinance returned empty info dict")
                return {}
            return info
        except Exception as e:
            logger.warning(f"[{symbol}] yfinance info fetch failed: {e}")
            return {}
    
    def _safe_get(self, info: Dict, *keys: str) -> Optional[float]:
        """
        Safely extracts a numeric value from yfinance info dict.
        Tries multiple key names (yfinance naming is inconsistent).
        """
        for key in keys:
            val = info.get(key)
            if val is not None:
                try:
                    # Handle string numbers, inf, nan
                    num = float(val)
                    if not (num == float('inf') or num == float('-inf') or num != num):
                        return num
                except (ValueError, TypeError):
                    continue
        return None
    
    def _safe_percentage(self, info: Dict, *keys: str) -> Optional[float]:
        """
        Extracts a percentage value, handling both decimal (0.15) and percent (15.0) formats.
        Returns in percentage form (15.0 = 15%).
        """
        val = self._safe_get(info, *keys)
        if val is None:
            return None
        
        # yfinance sometimes returns 0.15 (15%), sometimes 15.0 (15%)
        # Heuristic: If value is between -1 and 1, assume it's decimal form
        if -1.0 < val < 1.0:
            return val * 100
        return val
    
    # ── Main Extraction Method ─────────────────────────────────────────────
    
    def extract(self, symbol: str, use_cache: bool = True) -> FundamentalFeatures:
        """
        Extracts all fundamental features for a symbol.
        
        Args:
            symbol: Stock symbol (e.g., "RELIANCE.NS", "AAPL")
            use_cache: If True, returns cached result if available (within session)
        
        Returns:
            FundamentalFeatures with all available metrics and computed score.
        """
        # Check cache
        if use_cache and symbol in self._cache:
            logger.debug(f"[{symbol}] Fundamental features from cache")
            return self._cache[symbol]
        
        logger.info(f"[{symbol}] Fetching fundamental data...")
        
        # Fetch yfinance info
        info = self._fetch_yfinance_info(symbol)
        if not info:
            logger.warning(f"[{symbol}] No fundamental data available")
            return self._create_empty_features(symbol)
        
        # Extract all metrics
        features = FundamentalFeatures(symbol=symbol)
        
        # ── Valuation ──────────────────────────────────────────────────────
        features.pe_ratio = self._safe_get(
            info, "trailingPE", "forwardPE", "priceToEarningsRatio"
        )
        features.pb_ratio = self._safe_get(
            info, "priceToBook", "priceBookRatio"
        )
        features.ps_ratio = self._safe_get(
            info, "priceToSalesTrailing12Months", "priceToSales"
        )
        
        # ── Financial Health ───────────────────────────────────────────────
        features.debt_to_equity = self._safe_get(
            info, "debtToEquity", "totalDebtToEquity"
        )
        features.current_ratio = self._safe_get(
            info, "currentRatio"
        )
        features.quick_ratio = self._safe_get(
            info, "quickRatio"
        )
        
        # ── Growth ─────────────────────────────────────────────────────────
        features.revenue_growth = self._safe_percentage(
            info, "revenueGrowth", "revenueQuarterlyGrowth"
        )
        features.earnings_growth = self._safe_percentage(
            info, "earningsGrowth", "earningsQuarterlyGrowth"
        )
        
        # ── Profitability ──────────────────────────────────────────────────
        features.profit_margin = self._safe_percentage(
            info, "profitMargins", "netProfitMargin"
        )
        features.operating_margin = self._safe_percentage(
            info, "operatingMargins"
        )
        features.gross_margin = self._safe_percentage(
            info, "grossMargins"
        )
        
        # ── Returns ────────────────────────────────────────────────────────
        features.roe = self._safe_percentage(
            info, "returnOnEquity"
        )
        features.roa = self._safe_percentage(
            info, "returnOnAssets"
        )
        features.roic = self._safe_percentage(
            info, "returnOnCapital", "returnOnInvestedCapital"
        )
        
        # ── Dividend ───────────────────────────────────────────────────────
        features.dividend_yield = self._safe_percentage(
            info, "dividendYield", "trailingAnnualDividendYield"
        )
        features.payout_ratio = self._safe_percentage(
            info, "payoutRatio"
        )
        
        # ── Market Data ────────────────────────────────────────────────────
        features.market_cap = self._safe_get(
            info, "marketCap"
        )
        features.enterprise_value = self._safe_get(
            info, "enterpriseValue"
        )
        
        # ── Count available metrics ────────────────────────────────────────
        features.metrics_available = sum([
            features.pe_ratio is not None,
            features.pb_ratio is not None,
            features.ps_ratio is not None,
            features.debt_to_equity is not None,
            features.current_ratio is not None,
            features.revenue_growth is not None,
            features.earnings_growth is not None,
            features.profit_margin is not None,
            features.roe is not None,
            features.roa is not None,
            features.dividend_yield is not None,
        ])
        
        # ── Compute fundamental score ──────────────────────────────────────
        features.fundamental_score, features.scoring_breakdown = self._compute_score(features)
        
        # Cache
        self._cache[symbol] = features
        
        logger.info(
            f"[{symbol}] Fundamental score: {features.fundamental_score:.1f}/10 "
            f"({features.metrics_available} metrics available)"
        )
        
        return features
    
    # ── Scoring Logic ──────────────────────────────────────────────────────
    
    def _compute_score(
        self,
        features: FundamentalFeatures,
    ) -> tuple[float, Dict[str, Any]]:
        """
        Computes a 0-10 fundamental quality score.
        
        Scoring criteria (each worth 2 points):
          ✓ P/E ratio < 25 and > 0 (reasonably valued)
          ✓ Debt/Equity < 1.0 (conservatively financed)
          ✓ Revenue growth > 10% YoY (healthy growth)
          ✓ Profit margin > 15% (efficient operations)
          ✓ ROE > 15% (good use of shareholder capital)
        
        If fewer than 3 metrics are available, return neutral score (5.0).
        Otherwise, score based only on available data and scale to 0-10.
        """
        if features.metrics_available < FUNDAMENTAL_MIN_METRICS:
            return 5.0, {"reason": "Insufficient data", "metrics_count": features.metrics_available}
        
        score = 0
        max_possible = 0
        breakdown = {}
        
        # ── Criterion 1: P/E Ratio ─────────────────────────────────────────
        if features.pe_ratio is not None:
            max_possible += 2
            if 0 < features.pe_ratio < FUNDAMENTAL_PE_MAX:
                score += 2
                breakdown["pe_ratio"] = f"✓ {features.pe_ratio:.1f} (< {FUNDAMENTAL_PE_MAX})"
            elif features.pe_ratio > 0:
                score += 1  # At least it's positive
                breakdown["pe_ratio"] = f"~ {features.pe_ratio:.1f} (high valuation)"
            else:
                breakdown["pe_ratio"] = f"✗ {features.pe_ratio:.1f} (negative earnings)"
        
        # ── Criterion 2: Debt/Equity ───────────────────────────────────────
        if features.debt_to_equity is not None:
            max_possible += 2
            if features.debt_to_equity < FUNDAMENTAL_DEBT_EQUITY_MAX:
                score += 2
                breakdown["debt_to_equity"] = f"✓ {features.debt_to_equity:.2f} (< {FUNDAMENTAL_DEBT_EQUITY_MAX})"
            elif features.debt_to_equity < 2.0:
                score += 1  # Acceptable leverage
                breakdown["debt_to_equity"] = f"~ {features.debt_to_equity:.2f} (moderate debt)"
            else:
                breakdown["debt_to_equity"] = f"✗ {features.debt_to_equity:.2f} (high debt)"
        
        # ── Criterion 3: Revenue Growth ────────────────────────────────────
        if features.revenue_growth is not None:
            max_possible += 2
            if features.revenue_growth > FUNDAMENTAL_REVENUE_GROWTH_MIN:
                score += 2
                breakdown["revenue_growth"] = f"✓ {features.revenue_growth:.1f}% (> {FUNDAMENTAL_REVENUE_GROWTH_MIN}%)"
            elif features.revenue_growth > 0:
                score += 1  # At least growing
                breakdown["revenue_growth"] = f"~ {features.revenue_growth:.1f}% (slow growth)"
            else:
                breakdown["revenue_growth"] = f"✗ {features.revenue_growth:.1f}% (declining)"
        
        # ── Criterion 4: Profit Margin ─────────────────────────────────────
        if features.profit_margin is not None:
            max_possible += 2
            if features.profit_margin > FUNDAMENTAL_PROFIT_MARGIN_MIN:
                score += 2
                breakdown["profit_margin"] = f"✓ {features.profit_margin:.1f}% (> {FUNDAMENTAL_PROFIT_MARGIN_MIN}%)"
            elif features.profit_margin > 5.0:
                score += 1  # Marginally profitable
                breakdown["profit_margin"] = f"~ {features.profit_margin:.1f}% (thin margin)"
            else:
                breakdown["profit_margin"] = f"✗ {features.profit_margin:.1f}% (low/negative)"
        
        # ── Criterion 5: ROE ───────────────────────────────────────────────
        if features.roe is not None:
            max_possible += 2
            if features.roe > FUNDAMENTAL_ROE_MIN:
                score += 2
                breakdown["roe"] = f"✓ {features.roe:.1f}% (> {FUNDAMENTAL_ROE_MIN}%)"
            elif features.roe > 10.0:
                score += 1  # Decent return
                breakdown["roe"] = f"~ {features.roe:.1f}% (acceptable)"
            else:
                breakdown["roe"] = f"✗ {features.roe:.1f}% (poor return)"
        
        # ── Normalize to 0-10 scale ────────────────────────────────────────
        if max_possible == 0:
            final_score = 5.0
            breakdown["note"] = "No scorable metrics available — defaulting to neutral"
        else:
            final_score = (score / max_possible) * 10
            breakdown["raw_score"] = f"{score}/{max_possible}"
        
        return round(final_score, 1), breakdown
    
    # ── Utility Methods ────────────────────────────────────────────────────
    
    def _create_empty_features(self, symbol: str) -> FundamentalFeatures:
        """Returns a neutral FundamentalFeatures when no data is available."""
        return FundamentalFeatures(
            symbol=symbol,
            fundamental_score=5.0,
            metrics_available=0,
            scoring_breakdown={"note": "No fundamental data available"},
        )
    
    def clear_cache(self) -> None:
        """Clears the in-memory feature cache."""
        self._cache.clear()
        logger.debug("Fundamental feature cache cleared")
    
    def get_cached_symbols(self) -> list[str]:
        """Returns list of symbols currently in cache."""
        return list(self._cache.keys())
    
    # ── Public: Batch Extraction ───────────────────────────────────────────
    
    def extract_batch(
        self,
        symbols: list[str],
        use_cache: bool = True,
    ) -> Dict[str, FundamentalFeatures]:
        """
        Extracts fundamentals for multiple symbols.
        
        Args:
            symbols: List of stock symbols
            use_cache: Use cached data if available
        
        Returns:
            Dict mapping symbol → FundamentalFeatures
        """
        results = {}
        total = len(symbols)
        
        for i, symbol in enumerate(symbols, 1):
            logger.info(f"Extracting fundamentals [{i}/{total}]: {symbol}")
            try:
                results[symbol] = self.extract(symbol, use_cache=use_cache)
            except Exception as e:
                logger.error(f"[{symbol}] Fundamental extraction failed: {e}")
                results[symbol] = self._create_empty_features(symbol)
            
            # Polite delay to avoid hammering yfinance
            if i < total:
                import time
                time.sleep(0.5)
        
        return results
    
    # ── Public: Get specific metric ────────────────────────────────────────
    
    def get_pe_ratio(self, symbol: str) -> Optional[float]:
        """Quick accessor for P/E ratio only."""
        features = self.extract(symbol)
        return features.pe_ratio
    
    def get_score(self, symbol: str) -> float:
        """Quick accessor for fundamental score only."""
        features = self.extract(symbol)
        return features.fundamental_score
    
    def is_fundamentally_strong(
        self,
        symbol: str,
        min_score: float = 7.0,
    ) -> bool:
        """
        Returns True if the stock has strong fundamentals.
        
        Args:
            symbol: Stock symbol
            min_score: Minimum fundamental score (0-10) to be considered strong
        
        Returns:
            True if fundamental_score >= min_score
        """
        features = self.extract(symbol)
        return features.fundamental_score >= min_score
