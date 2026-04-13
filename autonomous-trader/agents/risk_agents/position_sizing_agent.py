"""
agents/risk_agents/position_sizing_agent.py
============================================
Position Sizing Agent - calculates optimal position size based on risk parameters.

Methodology: Fixed fractional position sizing with ATR-based stop loss
  - Risk per trade: 2% of capital (configurable)
  - Stop loss distance: 2 × ATR (Average True Range)
  - Position size = (Capital × Risk%) / (Price × Stop Loss Distance%)

Risk multipliers applied:
  1. Market regime multiplier (0.0-1.0 from MacroAgent)
  2. Earnings risk multiplier (0.0-1.0 from EarningsAgent)
  3. Data quality multiplier (0.3-1.0 from validation)

Final position size = Base position × all multipliers

Output:
  - quantity: int (shares to buy)
  - position_value: float (total $ amount)
  - stop_loss_price: float
  - take_profit_price: float
  - risk_amount: float ($ at risk)
  - risk_reward_ratio: float

Usage:
    from agents.risk_agents.position_sizing_agent import PositionSizingAgent
    agent = PositionSizingAgent()
    result = agent.run(
        symbol="RELIANCE.NS",
        current_price=2450.50,
        atr=45.30,
        available_capital=100000,
        regime_multiplier=0.8,
        earnings_multiplier=1.0,
        data_quality_score=0.95
    )
"""

from __future__ import annotations

from typing import Dict, Any
from dataclasses import dataclass

from agents.base_agent import BaseAgent, AgentResult
from config.constants import (
    POSITION_RISK_PCT,
    STOP_LOSS_ATR_MULTIPLIER,
    TAKE_PROFIT_ATR_MULTIPLIER,
    MIN_POSITION_VALUE,
    MAX_POSITION_VALUE,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class PositionSizingOutput:
    """Structured output from PositionSizingAgent."""
    symbol: str
    quantity: int
    position_value: float
    stop_loss_price: float
    take_profit_price: float
    risk_amount: float
    risk_reward_ratio: float
    
    # Calculation details
    base_quantity: int
    regime_multiplier: float
    earnings_multiplier: float
    data_quality_multiplier: float
    final_multiplier: float
    
    # Validation
    is_valid: bool
    rejection_reason: str = ""


# ═══════════════════════════════════════════════════════════════
# POSITION SIZING AGENT
# ═══════════════════════════════════════════════════════════════

class PositionSizingAgent(BaseAgent):
    """
    Agent responsible for calculating position size and risk parameters.
    
    Uses the industry-standard fixed fractional position sizing method:
      - Risk a fixed % of capital per trade (default: 2%)
      - Set stop loss based on technical volatility (ATR)
      - Calculate position size that caps risk at the fixed %
    
    All risk multipliers are applied to reduce position size in
    unfavorable conditions (bearish regime, approaching earnings, poor data).
    """
    
    def __init__(self):
        super().__init__(agent_name="PositionSizingAgent")
    
    def execute(
        self,
        symbol: str,
        current_price: float,
        atr: float,
        available_capital: float,
        regime_multiplier: float = 1.0,
        earnings_multiplier: float = 1.0,
        data_quality_score: float = 1.0,
        **kwargs
    ) -> AgentResult:
        """
        Calculates position size based on risk parameters.
        
        Args:
            symbol: Stock symbol
            current_price: Current stock price
            atr: Average True Range (14-period)
            available_capital: Available capital for this trade
            regime_multiplier: Market regime multiplier (0.0-1.0)
            earnings_multiplier: Earnings risk multiplier (0.0-1.0)
            data_quality_score: Data quality score (0.0-1.0)
            **kwargs: Additional parameters (currently unused)
        
        Returns:
            AgentResult with PositionSizingOutput in data field
        """
        self.logger.info(
            f"[{symbol}] Calculating position size | "
            f"Price: {current_price:.2f}, ATR: {atr:.2f}, "
            f"Capital: {available_capital:,.0f}"
        )
        
        # ── Validation ─────────────────────────────────────────────────────
        if current_price <= 0:
            return self.failure_result(
                error=f"Invalid price: {current_price}",
                metadata={"symbol": symbol}
            )
        
        if atr <= 0:
            self.logger.warning(
                f"[{symbol}] Invalid ATR: {atr}. Using 2% of price as fallback."
            )
            atr = current_price * 0.02
        
        if available_capital <= 0:
            return self.failure_result(
                error=f"No capital available: {available_capital}",
                metadata={"symbol": symbol}
            )
        
        # ── Calculate stop loss and take profit ────────────────────────────
        stop_loss_distance = STOP_LOSS_ATR_MULTIPLIER * atr
        stop_loss_price = current_price - stop_loss_distance
        
        take_profit_distance = TAKE_PROFIT_ATR_MULTIPLIER * atr
        take_profit_price = current_price + take_profit_distance
        
        # Stop loss can't be negative
        if stop_loss_price < 0:
            stop_loss_price = current_price * 0.95  # Fallback: 5% stop
            stop_loss_distance = current_price - stop_loss_price
        
        # ── Calculate base position size ───────────────────────────────────
        # Risk per trade
        risk_amount = available_capital * POSITION_RISK_PCT
        
        # Stop loss distance as %
        stop_loss_pct = stop_loss_distance / current_price
        
        # Position size = risk amount / (price × stop loss %)
        if stop_loss_pct > 0:
            base_position_value = risk_amount / stop_loss_pct
        else:
            base_position_value = available_capital * 0.1  # Fallback: 10% of capital
        
        base_quantity = int(base_position_value / current_price)
        
        # ── Apply risk multipliers ─────────────────────────────────────────
        # Data quality multiplier: poor data → reduce position
        # Quality <0.5 → reduce to 50%, <0.3 → reduce to 30%
        data_quality_multiplier = max(0.3, data_quality_score)
        
        # Combined multiplier
        final_multiplier = (
            regime_multiplier *
            earnings_multiplier *
            data_quality_multiplier
        )
        
        # Apply multiplier
        final_quantity = int(base_quantity * final_multiplier)
        final_position_value = final_quantity * current_price
        
        self.logger.debug(
            f"[{symbol}] Position sizing | "
            f"Base qty: {base_quantity} → Final qty: {final_quantity} | "
            f"Multipliers: regime={regime_multiplier:.2f}, "
            f"earnings={earnings_multiplier:.2f}, "
            f"data_quality={data_quality_multiplier:.2f} → "
            f"final={final_multiplier:.2f}"
        )
        
        # ── Validate position size ─────────────────────────────────────────
        is_valid = True
        rejection_reason = ""
        
        # Check minimum position value
        if final_position_value < MIN_POSITION_VALUE:
            is_valid = False
            rejection_reason = (
                f"Position value {final_position_value:,.0f} < "
                f"minimum {MIN_POSITION_VALUE:,.0f}"
            )
        
        # Check maximum position value
        if final_position_value > MAX_POSITION_VALUE:
            is_valid = False
            rejection_reason = (
                f"Position value {final_position_value:,.0f} > "
                f"maximum {MAX_POSITION_VALUE:,.0f}"
            )
        
        # Check if quantity is zero (all multipliers brought it to zero)
        if final_quantity == 0:
            is_valid = False
            rejection_reason = "Position size calculated to zero shares"
        
        # ── Calculate final risk metrics ───────────────────────────────────
        final_risk_amount = final_quantity * stop_loss_distance
        potential_profit = final_quantity * take_profit_distance
        risk_reward_ratio = (
            potential_profit / final_risk_amount
            if final_risk_amount > 0 else 0.0
        )
        
        # ── Create output ──────────────────────────────────────────────────
        output = PositionSizingOutput(
            symbol=symbol,
            quantity=final_quantity,
            position_value=final_position_value,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            risk_amount=final_risk_amount,
            risk_reward_ratio=risk_reward_ratio,
            base_quantity=base_quantity,
            regime_multiplier=regime_multiplier,
            earnings_multiplier=earnings_multiplier,
            data_quality_multiplier=data_quality_multiplier,
            final_multiplier=final_multiplier,
            is_valid=is_valid,
            rejection_reason=rejection_reason,
        )
        
        # ── Log result ─────────────────────────────────────────────────────
        if is_valid:
            self.logger.info(
                f"[{symbol}] Position sizing complete | "
                f"Qty: {final_quantity} @ {current_price:.2f} = {final_position_value:,.0f} | "
                f"SL: {stop_loss_price:.2f} | TP: {take_profit_price:.2f} | "
                f"Risk: {final_risk_amount:,.0f} | R/R: {risk_reward_ratio:.2f}"
            )
        else:
            self.logger.warning(
                f"[{symbol}] Position sizing REJECTED: {rejection_reason}"
            )
        
        return self.success_result(
            data=output,
            metadata={
                "symbol": symbol,
                "quantity": final_quantity,
                "position_value": final_position_value,
                "is_valid": is_valid,
            }
        )
