"""
agents/risk_agents/event_risk_agent.py
========================================
Event Risk Agent - aggregates all event-based trading risks.

Combines:
  1. Market regime risk (from MacroAgent)
  2. Earnings announcement risk (from EarningsAgent)
  3. Sector rotation signals (from MacroAgent)

Returns:
  - blocks_trading: bool (if ANY event blocks trading)
  - combined_multiplier: float (product of all risk multipliers)
  - risk_factors: List[str] (human-readable list of active risks)
  - highest_risk: str (which event has highest impact)

Usage:
    from agents.risk_agents.event_risk_agent import EventRiskAgent
    agent = EventRiskAgent()
    result = agent.run(
        symbol="RELIANCE.NS",
        macro_output=macro_agent_result.data,
        earnings_output=earnings_agent_result.data,
    )
    
    if result.data.blocks_trading:
        print(f"Trade blocked: {result.data.risk_factors}")
"""

from __future__ import annotations

from typing import List, Dict, Any
from dataclasses import dataclass

from agents.base_agent import BaseAgent, AgentResult
from config.constants import MarketRegime, EarningsRiskLevel
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class EventRiskOutput:
    """Structured output from EventRiskAgent."""
    symbol: str
    blocks_trading: bool
    combined_multiplier: float
    risk_factors: List[str]
    highest_risk: str
    
    # Individual risk details
    regime_blocks: bool
    earnings_blocks: bool
    regime_multiplier: float
    earnings_multiplier: float
    sector_signal: str  # "BULLISH" | "NEUTRAL" | "BEARISH"


# ═══════════════════════════════════════════════════════════════
# EVENT RISK AGENT
# ═══════════════════════════════════════════════════════════════

class EventRiskAgent(BaseAgent):
    """
    Agent responsible for aggregating all event-based trading risks.
    
    This agent acts as a HARD GATE:
      - If ANY risk blocks trading → trade is rejected
      - Otherwise → returns combined risk multiplier for position sizing
    
    Event risks are external factors beyond the stock's control
    (market crashes, earnings volatility, etc.) that can override
    even the best technical/fundamental signals.
    """
    
    def __init__(self):
        super().__init__(agent_name="EventRiskAgent")
    
    def execute(
        self,
        symbol: str,
        macro_output: Any,  # MacroAgentOutput
        earnings_output: Any,  # EarningsAgentOutput
        **kwargs
    ) -> AgentResult:
        """
        Aggregates event-based risks.
        
        Args:
            symbol: Stock symbol
            macro_output: Output from MacroAgent
            earnings_output: Output from EarningsAgent
            **kwargs: Additional parameters (currently unused)
        
        Returns:
            AgentResult with EventRiskOutput in data field
        """
        self.logger.info(f"[{symbol}] Checking event-based risks")
        
        risk_factors = []
        blocks_trading = False
        
        # ── Check market regime risk ───────────────────────────────────────
        regime = macro_output.regime
        regime_multiplier = macro_output.regime_position_multiplier
        regime_blocks = (regime_multiplier == 0.0)
        
        if regime_blocks:
            risk_factors.append(
                f"STRONG_BEAR market regime (multiplier: 0.0) — NO NEW TRADES"
            )
            blocks_trading = True
        elif regime == MarketRegime.BEAR.value:
            risk_factors.append(
                f"BEAR market regime (multiplier: {regime_multiplier}) — reduced sizing"
            )
        elif regime == MarketRegime.NEUTRAL.value:
            risk_factors.append(
                f"NEUTRAL market regime (multiplier: {regime_multiplier})"
            )
        
        # ── Check earnings risk ────────────────────────────────────────────
        earnings_multiplier = earnings_output.position_size_multiplier
        earnings_blocks = earnings_output.blocks_trading()
        
        if earnings_blocks:
            risk_factors.append(
                f"Earnings in {earnings_output.hours_until_earnings:.0f}h "
                f"({earnings_output.earnings_date}) — TRADE BLOCKED"
            )
            blocks_trading = True
        elif earnings_output.risk_level == EarningsRiskLevel.HIGH.value:
            risk_factors.append(
                f"HIGH earnings risk in {earnings_output.days_until_earnings}d "
                f"(multiplier: {earnings_multiplier})"
            )
        elif earnings_output.risk_level == EarningsRiskLevel.LOW.value:
            risk_factors.append(
                f"Low earnings risk in {earnings_output.days_until_earnings}d "
                f"(multiplier: {earnings_multiplier})"
            )
        
        # ── Check sector rotation ──────────────────────────────────────────
        # Get sector for this symbol (if available)
        try:
            from data.collectors.macro_collector import MacroCollector
            collector = MacroCollector()
            sector = collector.get_sector_for_symbol(symbol)
            
            if sector and sector in macro_output.sector_rotation:
                sector_signal = macro_output.sector_rotation[sector]
                
                if sector_signal == "BEARISH":
                    risk_factors.append(
                        f"Sector {sector} is BEARISH (underperforming)"
                    )
                elif sector_signal == "BULLISH":
                    self.logger.debug(
                        f"[{symbol}] Sector {sector} is BULLISH (positive signal)"
                    )
            else:
                sector_signal = "NEUTRAL"
        except Exception as e:
            self.logger.warning(f"[{symbol}] Could not determine sector: {e}")
            sector_signal = "NEUTRAL"
        
        # ── Calculate combined multiplier ──────────────────────────────────
        if blocks_trading:
            combined_multiplier = 0.0
        else:
            combined_multiplier = regime_multiplier * earnings_multiplier
        
        # ── Determine highest risk factor ──────────────────────────────────
        if regime_blocks:
            highest_risk = "MARKET_REGIME"
        elif earnings_blocks:
            highest_risk = "EARNINGS"
        elif regime_multiplier < 1.0:
            highest_risk = "MARKET_REGIME"
        elif earnings_multiplier < 1.0:
            highest_risk = "EARNINGS"
        else:
            highest_risk = "NONE"
        
        # ── Create output ──────────────────────────────────────────────────
        output = EventRiskOutput(
            symbol=symbol,
            blocks_trading=blocks_trading,
            combined_multiplier=combined_multiplier,
            risk_factors=risk_factors,
            highest_risk=highest_risk,
            regime_blocks=regime_blocks,
            earnings_blocks=earnings_blocks,
            regime_multiplier=regime_multiplier,
            earnings_multiplier=earnings_multiplier,
            sector_signal=sector_signal,
        )
        
        # ── Log result ─────────────────────────────────────────────────────
        if blocks_trading:
            self.logger.warning(
                f"[{symbol}] ⚠️ EVENT RISK BLOCKS TRADING | "
                f"Risks: {', '.join(risk_factors)}"
            )
        elif combined_multiplier < 1.0:
            self.logger.info(
                f"[{symbol}] Event risk reduces position sizing | "
                f"Combined multiplier: {combined_multiplier:.2f} | "
                f"Risks: {', '.join(risk_factors)}"
            )
        else:
            self.logger.debug(
                f"[{symbol}] No significant event risks | "
                f"Multiplier: {combined_multiplier:.2f}"
            )
        
        return self.success_result(
            data=output,
            metadata={
                "symbol": symbol,
                "blocks_trading": blocks_trading,
                "combined_multiplier": combined_multiplier,
                "risk_count": len(risk_factors),
            }
        )
