"""
agents/data_agents/macro_agent.py
===================================
Macro/Market Regime Agent - determines overall market conditions.

Responsibilities:
  1. Fetch macro data from MacroCollector
  2. Determine market regime (STRONG_BULL → STRONG_BEAR)
  3. Get sector rotation signals
  4. Cache results (shared across all symbols in this cycle)

Output:
  - regime: MarketRegime enum value
  - regime_position_multiplier: float (0.0-1.0)
  - vix_current: float
  - sector_rotation: Dict[sector, signal]
  - macro_snapshot: MacroSnapshot (complete data)

Usage:
    from agents.data_agents.macro_agent import MacroAgent
    agent = MacroAgent()
    result = agent.run()  # No symbol needed - macro is global
    
    if result.success:
        regime = result.data.regime
        multiplier = result.data.regime_position_multiplier
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from dataclasses import dataclass

from agents.base_agent import BaseAgent, AgentResult
from data.collectors.macro_collector import MacroCollector, MacroSnapshot
from data.storage.cache import cache
from config.constants import MarketRegime
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class MacroAgentOutput:
    """Structured output from MacroAgent."""
    regime: str  # MarketRegime value
    regime_position_multiplier: float
    vix_current: Optional[float]
    vix_signal: str
    interest_rate_trend: str
    recession_risk: str
    sector_rotation: Dict[str, str]
    macro_snapshot: MacroSnapshot  # Full data for detailed analysis
    
    def is_bullish_sector(self, sector: str) -> bool:
        """Returns True if the given sector is bullish."""
        return self.sector_rotation.get(sector, "NEUTRAL") == "BULLISH"
    
    def should_trade(self) -> bool:
        """Returns True if regime allows new trades (not STRONG_BEAR)."""
        return self.regime_position_multiplier > 0.0


# ═══════════════════════════════════════════════════════════════
# MACRO AGENT
# ═══════════════════════════════════════════════════════════════

class MacroAgent(BaseAgent):
    """
    Agent responsible for determining market regime and macro conditions.
    
    This agent's output affects ALL trades:
      - STRONG_BEAR regime → no new positions opened (multiplier = 0.0)
      - BEAR regime → position sizes reduced to 50%
      - NEUTRAL/BULL/STRONG_BULL → normal or increased sizing
    
    Market regime is the #1 override in the risk management system.
    """
    
    def __init__(self):
        super().__init__(agent_name="MacroAgent")
        self.macro_collector = MacroCollector()
    
    def execute(self, **kwargs) -> AgentResult:
        """
        Determines current market regime and macro conditions.
        
        Note: This agent doesn't need a symbol - macro data is global.
        
        Args:
            **kwargs: Additional parameters (currently unused)
        
        Returns:
            AgentResult with MacroAgentOutput in data field
        """
        self.logger.info("Determining market regime")
        
        # ── Check cache first ──────────────────────────────────────────────
        # Macro data is the same for all symbols, so we cache it globally
        cached_output = cache.get("macro_agent_output")
        if cached_output:
            self.logger.debug("Using cached macro data")
            # Re-hydrate MacroSnapshot from cached dict
            macro_snapshot = MacroSnapshot(**cached_output["macro_snapshot"])
            output = MacroAgentOutput(
                regime=cached_output["regime"],
                regime_position_multiplier=cached_output["regime_position_multiplier"],
                vix_current=cached_output["vix_current"],
                vix_signal=cached_output["vix_signal"],
                interest_rate_trend=cached_output["interest_rate_trend"],
                recession_risk=cached_output["recession_risk"],
                sector_rotation=cached_output["sector_rotation"],
                macro_snapshot=macro_snapshot,
            )
            return self.success_result(
                data=output,
                metadata={"source": "cache"}
            )
        
        # ── Fetch macro data ───────────────────────────────────────────────
        try:
            macro_snapshot = self.macro_collector.get_market_regime()
            
            self.logger.info(
                f"Market regime: {macro_snapshot.regime} | "
                f"Multiplier: {macro_snapshot.regime_position_multiplier}x | "
                f"VIX: {macro_snapshot.vix_current}"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to fetch market regime: {e}")
            return self.failure_result(
                error=f"Market regime fetch failed: {e}",
                metadata={"error_type": type(e).__name__}
            )
        
        # ── Fetch sector rotation ──────────────────────────────────────────
        try:
            sector_rotation = self.macro_collector.get_sector_rotation()
            
            bullish_sectors = [s for s, sig in sector_rotation.items() if sig == "BULLISH"]
            bearish_sectors = [s for s, sig in sector_rotation.items() if sig == "BEARISH"]
            
            self.logger.debug(
                f"Sector rotation | Bullish: {bullish_sectors} | Bearish: {bearish_sectors}"
            )
            
        except Exception as e:
            self.logger.warning(f"Failed to fetch sector rotation: {e}")
            # Non-critical - can continue with empty sector rotation
            sector_rotation = {}
        
        # ── Create output ──────────────────────────────────────────────────
        output = MacroAgentOutput(
            regime=macro_snapshot.regime,
            regime_position_multiplier=macro_snapshot.regime_position_multiplier,
            vix_current=macro_snapshot.vix_current,
            vix_signal=macro_snapshot.vix_signal,
            interest_rate_trend=macro_snapshot.interest_rate_trend,
            recession_risk=macro_snapshot.recession_risk,
            sector_rotation=sector_rotation,
            macro_snapshot=macro_snapshot,
        )
        
        # ── Check for regime warnings ──────────────────────────────────────
        if output.regime == MarketRegime.STRONG_BEAR.value:
            self.logger.warning(
                "⚠️ STRONG_BEAR regime detected! "
                "NO NEW POSITIONS will be opened. "
                f"Reason: {macro_snapshot.regime_reasoning}"
            )
        elif output.regime == MarketRegime.BEAR.value:
            self.logger.warning(
                "⚠️ BEAR regime detected! "
                "Position sizes reduced to 50%. "
                f"Reason: {macro_snapshot.regime_reasoning}"
            )
        
        # ── Cache the output ───────────────────────────────────────────────
        cache.set(
            "macro_agent_output",
            {
                "regime": output.regime,
                "regime_position_multiplier": output.regime_position_multiplier,
                "vix_current": output.vix_current,
                "vix_signal": output.vix_signal,
                "interest_rate_trend": output.interest_rate_trend,
                "recession_risk": output.recession_risk,
                "sector_rotation": output.sector_rotation,
                "macro_snapshot": macro_snapshot.to_dict(),
            },
            ttl=3600  # 1 hour (macro doesn't change that fast)
        )
        
        return self.success_result(
            data=output,
            metadata={
                "regime": output.regime,
                "multiplier": output.regime_position_multiplier,
                "vix": output.vix_current,
                "recession_risk": output.recession_risk,
            }
        )
