"""
agents/analysis_agents/fundamental_agent.py
=============================================
Fundamental Analysis Agent - scores a stock based on financial fundamentals.

Scoring methodology:
  - Uses FundamentalFeatureExtractor's built-in scoring (0-10)
  - Additional sector-specific adjustments
  - Macro regime adjustments

Fundamental score interpretation:
  - 8-10: High quality company (strong balance sheet, growth, profitability)
  - 6-8: Good quality company
  - 4-6: Average quality
  - 2-4: Below average quality
  - 0-2: Poor quality (avoid long-term holds)

Note: Fundamental score is less important for short-term swing trades
      (5-10 day holds) but critical for longer positions.

Usage:
    from agents.analysis_agents.fundamental_agent import FundamentalAgent
    agent = FundamentalAgent()
    result = agent.run(symbol="RELIANCE.NS")
    
    if result.success:
        score = result.data.fundamental_score
        print(f"Fundamental score: {score}/10")
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from dataclasses import dataclass

from agents.base_agent import BaseAgent, AgentResult
from ml.features.fundamental_features import (
    FundamentalFeatureExtractor,
    FundamentalFeatures,
)
from data.storage.cache import cache
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class FundamentalAgentOutput:
    """Structured output from FundamentalAgent."""
    symbol: str
    fundamental_score: float  # 0-10 (from FundamentalFeatureExtractor)
    adjusted_score: float     # After sector/macro adjustments
    
    # Key metrics
    pe_ratio: Optional[float]
    pb_ratio: Optional[float]
    debt_to_equity: Optional[float]
    revenue_growth: Optional[float]
    profit_margin: Optional[float]
    roe: Optional[float]
    dividend_yield: Optional[float]
    
    # Meta
    metrics_available: int
    scoring_breakdown: Dict[str, Any]
    recommendation: str
    full_features: FundamentalFeatures  # Complete data


# ═══════════════════════════════════════════════════════════════
# FUNDAMENTAL AGENT
# ═══════════════════════════════════════════════════════════════

class FundamentalAgent(BaseAgent):
    """
    Agent that scores stocks based on fundamental analysis.
    
    Analyzes financial metrics like P/E, debt/equity, growth rates,
    profitability, and returns to produce a 0-10 fundamental score.
    """
    
    def __init__(self):
        super().__init__(agent_name="FundamentalAgent")
        self.fundamental_extractor = FundamentalFeatureExtractor()
    
    def execute(
        self,
        symbol: str,
        sector: Optional[str] = None,
        **kwargs
    ) -> AgentResult:
        """
        Analyzes fundamental metrics and produces a score.
        
        Args:
            symbol: Stock symbol
            sector: Optional sector for sector-specific adjustments
            **kwargs: Additional parameters (currently unused)
        
        Returns:
            AgentResult with FundamentalAgentOutput in data field
        """
        self.logger.info(f"[{symbol}] Running fundamental analysis")
        
        # ── Check cache ────────────────────────────────────────────────────
        cached_output = cache.get_cached_agent_output("FundamentalAgent", symbol)
        if cached_output:
            self.logger.debug(f"[{symbol}] Using cached fundamental analysis")
            # Re-hydrate FundamentalFeatures
            full_features = FundamentalFeatures(**cached_output["full_features"])
            cached_output["full_features"] = full_features
            return self.success_result(
                data=FundamentalAgentOutput(**cached_output),
                metadata={"source": "cache"}
            )
        
        # ── Extract fundamental features ───────────────────────────────────
        try:
            features = self.fundamental_extractor.extract(symbol)
            self.logger.debug(
                f"[{symbol}] Extracted fundamentals: "
                f"{features.metrics_available} metrics available"
            )
        except Exception as e:
            self.logger.error(f"[{symbol}] Fundamental extraction failed: {e}")
            return self.failure_result(
                error=f"Fundamental extraction failed: {e}",
                metadata={"symbol": symbol}
            )
        
        # ── Apply adjustments ──────────────────────────────────────────────
        base_score = features.fundamental_score
        adjusted_score = self._apply_adjustments(base_score, features, sector)
        
        # ── Determine recommendation ───────────────────────────────────────
        if adjusted_score >= 8:
            recommendation = "STRONG_BUY"
        elif adjusted_score >= 6:
            recommendation = "BUY"
        elif adjusted_score >= 4:
            recommendation = "HOLD"
        elif adjusted_score >= 2:
            recommendation = "SELL"
        else:
            recommendation = "STRONG_SELL"
        
        # ── Build output ───────────────────────────────────────────────────
        output = FundamentalAgentOutput(
            symbol=symbol,
            fundamental_score=round(base_score, 2),
            adjusted_score=round(adjusted_score, 2),
            pe_ratio=features.pe_ratio,
            pb_ratio=features.pb_ratio,
            debt_to_equity=features.debt_to_equity,
            revenue_growth=features.revenue_growth,
            profit_margin=features.profit_margin,
            roe=features.roe,
            dividend_yield=features.dividend_yield,
            metrics_available=features.metrics_available,
            scoring_breakdown=features.scoring_breakdown,
            recommendation=recommendation,
            full_features=features,
        )
        
        self.logger.info(
            f"[{symbol}] Fundamental score: {base_score:.1f}/10 "
            f"(adjusted: {adjusted_score:.1f}) | "
            f"Recommendation: {recommendation} | "
            f"P/E: {features.pe_ratio}, ROE: {features.roe}"
        )
        
        # ── Cache the output ───────────────────────────────────────────────
        cache_data = output.__dict__.copy()
        cache_data["full_features"] = features.to_dict()
        
        cache.cache_agent_output(
            "FundamentalAgent",
            symbol,
            cache_data,
            ttl=3600  # 1 hour (fundamentals don't change intraday)
        )
        
        return self.success_result(
            data=output,
            metadata={
                "symbol": symbol,
                "score": base_score,
                "adjusted_score": adjusted_score,
                "recommendation": recommendation,
                "metrics_count": features.metrics_available,
            }
        )
    
    # ── Adjustments ────────────────────────────────────────────────────────
    
    def _apply_adjustments(
        self,
        base_score: float,
        features: FundamentalFeatures,
        sector: Optional[str],
    ) -> float:
        """
        Applies sector-specific and special case adjustments.
        
        Adjustments:
          - High-growth tech: P/E less important, growth more important
          - Dividend stocks: Yield becomes more important
          - Cyclical sectors: Debt levels more critical
        """
        adjusted = base_score
        
        # ── Sector adjustments ─────────────────────────────────────────────
        if sector:
            if sector.upper() in ["IT", "TECHNOLOGY", "SOFTWARE"]:
                # Tech companies: High P/E is acceptable if growth is strong
                if features.revenue_growth and features.revenue_growth > 20:
                    adjusted += 0.5
                    self.logger.debug(f"Tech growth adjustment: +0.5")
            
            elif sector.upper() in ["BANKING", "FINANCE", "NBFC"]:
                # Financial companies: Focus on asset quality and ROE
                if features.roe and features.roe > 15:
                    adjusted += 0.3
                    self.logger.debug(f"Banking ROE adjustment: +0.3")
            
            elif sector.upper() in ["UTILITIES", "INFRASTRUCTURE"]:
                # Utilities: Dividend yield and stability matter more
                if features.dividend_yield and features.dividend_yield > 3:
                    adjusted += 0.3
                    self.logger.debug(f"Utility dividend adjustment: +0.3")
        
        # ── Special case: Very low debt ────────────────────────────────────
        if features.debt_to_equity and features.debt_to_equity < 0.3:
            adjusted += 0.2
            self.logger.debug(f"Low debt bonus: +0.2")
        
        # ── Special case: Consistent dividend payer ────────────────────────
        if features.dividend_yield and features.dividend_yield > 2:
            if features.payout_ratio and features.payout_ratio < 0.6:
                # Sustainable dividend (payout < 60%)
                adjusted += 0.2
                self.logger.debug(f"Sustainable dividend bonus: +0.2")
        
        # ── Cap at 10 ──────────────────────────────────────────────────────
        return min(adjusted, 10.0)
