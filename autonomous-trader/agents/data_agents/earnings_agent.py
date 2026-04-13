"""
agents/data_agents/earnings_agent.py
======================================
Earnings Risk Agent - checks if a stock has upcoming earnings that block trading.

Responsibilities:
  1. Check for upcoming earnings announcements
  2. Calculate risk level (NONE, LOW, HIGH, BLOCK)
  3. Calculate position size multiplier based on proximity to earnings
  4. Cache results for this trading cycle

Risk levels and their effects:
  - BLOCK (<24h): No trades allowed (multiplier = 0.0)
  - HIGH (<72h): Position size × 0.5
  - LOW (<7 days): Position size × 0.7
  - NONE (>7 days): No adjustment (multiplier = 1.0)

Output:
  - has_risk: bool
  - risk_level: str (EarningsRiskLevel value)
  - position_size_multiplier: float
  - days_until_earnings: Optional[int]
  - earnings_date: Optional[date]
  - reasoning: str

Usage:
    from agents.data_agents.earnings_agent import EarningsAgent
    agent = EarningsAgent()
    result = agent.run(symbol="RELIANCE.NS")
    
    if result.success:
        if result.data.risk_level == "BLOCK":
            print("Cannot trade - earnings today!")
"""

from __future__ import annotations

from typing import Optional
from dataclasses import dataclass
from datetime import date

from agents.base_agent import BaseAgent, AgentResult
from data.collectors.earnings_calendar import (
    EarningsCalendarCollector,
    EarningsRisk,
    EarningsEvent,
)
from data.storage.cache import cache
from config.constants import EarningsRiskLevel
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class EarningsAgentOutput:
    """Structured output from EarningsAgent."""
    symbol: str
    has_risk: bool
    risk_level: str  # EarningsRiskLevel value
    position_size_multiplier: float
    days_until_earnings: Optional[int]
    hours_until_earnings: Optional[float]
    earnings_date: Optional[date]
    earnings_time: Optional[str]  # "BMO" | "AMC" | "UNKNOWN"
    reasoning: str
    earnings_event: Optional[EarningsEvent]
    
    def blocks_trading(self) -> bool:
        """Returns True if earnings risk blocks trading completely."""
        return self.risk_level == EarningsRiskLevel.BLOCK.value


# ═══════════════════════════════════════════════════════════════
# EARNINGS AGENT
# ═══════════════════════════════════════════════════════════════

class EarningsAgent(BaseAgent):
    """
    Agent responsible for checking earnings-related trading risk.
    
    Earnings announcements create extreme volatility - a stock can gap
    up or down 10-20% overnight. The system avoids trading near earnings.
    
    This agent acts as a HARD GATE:
      - If risk_level == BLOCK → trade is completely rejected
      - If risk_level == HIGH/LOW → position size is reduced
    """
    
    def __init__(self):
        super().__init__(agent_name="EarningsAgent")
        self.earnings_collector = EarningsCalendarCollector()
    
    def execute(self, symbol: str, **kwargs) -> AgentResult:
        """
        Checks earnings risk for a symbol.
        
        Args:
            symbol: Stock symbol to check
            **kwargs: Additional parameters (currently unused)
        
        Returns:
            AgentResult with EarningsAgentOutput in data field
        """
        self.logger.info(f"[{symbol}] Checking earnings risk")
        
        # ── Check cache first ──────────────────────────────────────────────
        cached_output = cache.get_cached_agent_output("EarningsAgent", symbol)
        if cached_output:
            self.logger.debug(f"[{symbol}] Using cached earnings risk data")
            # Re-hydrate EarningsEvent if present
            earnings_event = None
            if cached_output.get("earnings_event"):
                earnings_event = EarningsEvent(**cached_output["earnings_event"])
            
            output = EarningsAgentOutput(
                symbol=symbol,
                has_risk=cached_output["has_risk"],
                risk_level=cached_output["risk_level"],
                position_size_multiplier=cached_output["position_size_multiplier"],
                days_until_earnings=cached_output["days_until_earnings"],
                hours_until_earnings=cached_output["hours_until_earnings"],
                earnings_date=cached_output["earnings_date"],
                earnings_time=cached_output["earnings_time"],
                reasoning=cached_output["reasoning"],
                earnings_event=earnings_event,
            )
            return self.success_result(
                data=output,
                metadata={"source": "cache"}
            )
        
        # ── Fetch earnings risk ────────────────────────────────────────────
        try:
            earnings_risk = self.earnings_collector.has_earnings_risk(symbol)
            
            self.logger.debug(
                f"[{symbol}] Earnings risk: {earnings_risk.risk_level} | "
                f"Multiplier: {earnings_risk.position_size_multiplier}x"
            )
            
        except Exception as e:
            self.logger.error(f"[{symbol}] Failed to fetch earnings risk: {e}")
            return self.failure_result(
                error=f"Earnings risk check failed: {e}",
                metadata={"symbol": symbol}
            )
        
        # ── Extract event details ──────────────────────────────────────────
        earnings_date = None
        earnings_time = None
        if earnings_risk.earnings_event:
            earnings_date = earnings_risk.earnings_event.earnings_date
            earnings_time = earnings_risk.earnings_event.earnings_time
        
        # ── Create output ──────────────────────────────────────────────────
        output = EarningsAgentOutput(
            symbol=symbol,
            has_risk=earnings_risk.has_risk,
            risk_level=earnings_risk.risk_level,
            position_size_multiplier=earnings_risk.position_size_multiplier,
            days_until_earnings=earnings_risk.days_until_earnings,
            hours_until_earnings=earnings_risk.hours_until_earnings,
            earnings_date=earnings_date,
            earnings_time=earnings_time,
            reasoning=earnings_risk.reasoning,
            earnings_event=earnings_risk.earnings_event,
        )
        
        # ── Log warnings for high risk ─────────────────────────────────────
        if output.risk_level == EarningsRiskLevel.BLOCK.value:
            self.logger.warning(
                f"[{symbol}] ⚠️ EARNINGS BLOCK | "
                f"Earnings in {earnings_risk.hours_until_earnings:.0f}h "
                f"({earnings_date}). Trade REJECTED."
            )
        elif output.risk_level == EarningsRiskLevel.HIGH.value:
            self.logger.warning(
                f"[{symbol}] ⚠️ HIGH EARNINGS RISK | "
                f"Earnings in {earnings_risk.days_until_earnings}d ({earnings_date}). "
                f"Position size reduced to 50%."
            )
        elif output.risk_level == EarningsRiskLevel.LOW.value:
            self.logger.info(
                f"[{symbol}] Low earnings risk | "
                f"Earnings in {earnings_risk.days_until_earnings}d ({earnings_date}). "
                f"Position size reduced to 70%."
            )
        
        # ── Cache the output ───────────────────────────────────────────────
        cache.cache_agent_output(
            "EarningsAgent",
            symbol,
            {
                "symbol": symbol,
                "has_risk": output.has_risk,
                "risk_level": output.risk_level,
                "position_size_multiplier": output.position_size_multiplier,
                "days_until_earnings": output.days_until_earnings,
                "hours_until_earnings": output.hours_until_earnings,
                "earnings_date": earnings_date.isoformat() if earnings_date else None,
                "earnings_time": earnings_time,
                "reasoning": output.reasoning,
                "earnings_event": (
                    earnings_risk.earnings_event.to_dict()
                    if earnings_risk.earnings_event else None
                ),
            },
            ttl=3600  # 1 hour (re-check as earnings approaches)
        )
        
        return self.success_result(
            data=output,
            metadata={
                "symbol": symbol,
                "risk_level": output.risk_level,
                "multiplier": output.position_size_multiplier,
                "days_until": output.days_until_earnings,
            }
        )
