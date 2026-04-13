"""
agents/risk_agents/portfolio_risk_agent.py
============================================
Portfolio Risk Agent - enforces portfolio-level risk constraints.

Checks:
  1. Maximum open positions (default: 10)
  2. Sector concentration (max 30% in one sector)
  3. Portfolio heat (total $ at risk across all positions)
  4. Single position size (max 20% of portfolio)

Returns:
  - can_open_position: bool
  - rejection_reason: str (if can't open)
  - current_position_count: int
  - portfolio_heat: float (% of capital at risk)
  - sector_exposure: Dict[sector, %]

Usage:
    from agents.risk_agents.portfolio_risk_agent import PortfolioRiskAgent
    agent = PortfolioRiskAgent()
    result = agent.run(
        symbol="RELIANCE.NS",
        sector="Energy",
        position_value=50000,
        portfolio_value=200000,
    )
    
    if not result.data.can_open_position:
        print(f"Cannot open: {result.data.rejection_reason}")
"""

from __future__ import annotations

from typing import List, Dict, Any
from dataclasses import dataclass

from agents.base_agent import BaseAgent, AgentResult
from data.storage.database import DatabaseManager
from config.constants import (
    MAX_OPEN_POSITIONS,
    MAX_SECTOR_CONCENTRATION,
    MAX_POSITION_SIZE_PCT,
    MAX_PORTFOLIO_HEAT,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class PortfolioRiskOutput:
    """Structured output from PortfolioRiskAgent."""
    symbol: str
    can_open_position: bool
    rejection_reason: str
    
    # Portfolio stats
    current_position_count: int
    portfolio_value: float
    portfolio_heat: float  # % of capital at risk
    
    # Sector analysis
    sector: str
    sector_exposure_pct: float  # Current exposure to this sector
    sector_exposure_after_pct: float  # Exposure after adding this position
    
    # Position analysis
    proposed_position_value: float
    proposed_position_pct: float  # % of portfolio


# ═══════════════════════════════════════════════════════════════
# PORTFOLIO RISK AGENT
# ═══════════════════════════════════════════════════════════════

class PortfolioRiskAgent(BaseAgent):
    """
    Agent responsible for portfolio-level risk management.
    
    Prevents:
      - Over-diversification (too many positions to track)
      - Sector concentration (one sector crash wipes out portfolio)
      - Excessive leverage (too much capital at risk)
      - Oversized positions (one position dominates portfolio)
    
    These checks ensure the portfolio stays balanced and manageable.
    """
    
    def __init__(self, db: DatabaseManager = None):
        super().__init__(agent_name="PortfolioRiskAgent")
        self.db = db or DatabaseManager()
    
    def execute(
        self,
        symbol: str,
        sector: str,
        position_value: float,
        portfolio_value: float,
        **kwargs
    ) -> AgentResult:
        """
        Checks if a new position can be opened given portfolio constraints.
        
        Args:
            symbol: Stock symbol for the proposed position
            sector: Sector this stock belongs to
            position_value: Proposed position value ($)
            portfolio_value: Total portfolio value ($)
            **kwargs: Additional parameters (currently unused)
        
        Returns:
            AgentResult with PortfolioRiskOutput in data field
        """
        self.logger.info(
            f"[{symbol}] Checking portfolio constraints | "
            f"Proposed: {position_value:,.0f} ({position_value/portfolio_value*100:.1f}%)"
        )
        
        can_open = True
        rejection_reason = ""
        
        # ── Get current portfolio ──────────────────────────────────────────
        try:
            current_positions = self.db.get_portfolio()
        except Exception as e:
            self.logger.error(f"Failed to get portfolio: {e}")
            return self.failure_result(
                error=f"Portfolio fetch failed: {e}",
                metadata={"symbol": symbol}
            )
        
        current_position_count = len(current_positions)
        
        # ── Check 1: Maximum positions ─────────────────────────────────────
        if current_position_count >= MAX_OPEN_POSITIONS:
            can_open = False
            rejection_reason = (
                f"Maximum positions reached: {current_position_count}/{MAX_OPEN_POSITIONS}"
            )
            self.logger.warning(
                f"[{symbol}] {rejection_reason}"
            )
        
        # ── Check 2: Position size limit ───────────────────────────────────
        position_pct = (position_value / portfolio_value) * 100
        
        if position_pct > MAX_POSITION_SIZE_PCT:
            can_open = False
            rejection_reason = (
                f"Position too large: {position_pct:.1f}% > max {MAX_POSITION_SIZE_PCT}%"
            )
            self.logger.warning(
                f"[{symbol}] {rejection_reason}"
            )
        
        # ── Check 3: Sector concentration ──────────────────────────────────
        sector_exposure = self._calculate_sector_exposure(
            current_positions, portfolio_value
        )
        
        current_sector_pct = sector_exposure.get(sector, 0.0)
        
        # After adding this position
        sector_value_after = (
            sector_exposure.get(sector, 0.0) / 100 * portfolio_value
        ) + position_value
        sector_pct_after = (sector_value_after / portfolio_value) * 100
        
        if sector_pct_after > MAX_SECTOR_CONCENTRATION:
            can_open = False
            rejection_reason = (
                f"Sector concentration too high: {sector} would be "
                f"{sector_pct_after:.1f}% > max {MAX_SECTOR_CONCENTRATION}%"
            )
            self.logger.warning(
                f"[{symbol}] {rejection_reason}"
            )
        
        # ── Check 4: Portfolio heat ────────────────────────────────────────
        portfolio_heat = self._calculate_portfolio_heat(
            current_positions, portfolio_value
        )
        
        # Estimate risk for new position (assume 2% risk per trade)
        new_position_risk = position_value * 0.02
        portfolio_heat_after = portfolio_heat + (new_position_risk / portfolio_value * 100)
        
        if portfolio_heat_after > MAX_PORTFOLIO_HEAT:
            can_open = False
            rejection_reason = (
                f"Portfolio heat too high: {portfolio_heat_after:.1f}% > "
                f"max {MAX_PORTFOLIO_HEAT}%"
            )
            self.logger.warning(
                f"[{symbol}] {rejection_reason}"
            )
        
        # ── Create output ──────────────────────────────────────────────────
        output = PortfolioRiskOutput(
            symbol=symbol,
            can_open_position=can_open,
            rejection_reason=rejection_reason,
            current_position_count=current_position_count,
            portfolio_value=portfolio_value,
            portfolio_heat=portfolio_heat,
            sector=sector,
            sector_exposure_pct=current_sector_pct,
            sector_exposure_after_pct=sector_pct_after,
            proposed_position_value=position_value,
            proposed_position_pct=position_pct,
        )
        
        # ── Log result ─────────────────────────────────────────────────────
        if can_open:
            self.logger.info(
                f"[{symbol}] Portfolio constraints passed | "
                f"Positions: {current_position_count}/{MAX_OPEN_POSITIONS} | "
                f"Sector {sector}: {current_sector_pct:.1f}% → {sector_pct_after:.1f}% | "
                f"Portfolio heat: {portfolio_heat:.1f}%"
            )
        else:
            self.logger.warning(
                f"[{symbol}] ⚠️ PORTFOLIO CONSTRAINT VIOLATION | "
                f"{rejection_reason}"
            )
        
        return self.success_result(
            data=output,
            metadata={
                "symbol": symbol,
                "can_open": can_open,
                "position_count": current_position_count,
                "sector_exposure": current_sector_pct,
            }
        )
    
    # ── Helper Methods ─────────────────────────────────────────────────────
    
    def _calculate_sector_exposure(
        self,
        positions: List,
        portfolio_value: float,
    ) -> Dict[str, float]:
        """
        Calculates current sector exposure as % of portfolio.
        
        Returns:
            Dict mapping sector → exposure %
        """
        from data.collectors.macro_collector import MacroCollector
        
        sector_values = {}
        collector = MacroCollector()
        
        for position in positions:
            # Get sector for this symbol
            try:
                sector = collector.get_sector_for_symbol(position.symbol)
                if not sector:
                    sector = "UNKNOWN"
            except Exception:
                sector = "UNKNOWN"
            
            # Add position value to sector total
            position_value = position.current_price * position.quantity
            sector_values[sector] = sector_values.get(sector, 0.0) + position_value
        
        # Convert to percentages
        sector_exposure = {
            sector: (value / portfolio_value * 100)
            for sector, value in sector_values.items()
        }
        
        return sector_exposure
    
    def _calculate_portfolio_heat(
        self,
        positions: List,
        portfolio_value: float,
    ) -> float:
        """
        Calculates portfolio heat (total $ at risk / portfolio value).
        
        Heat = sum of (position_value × distance_to_stop_loss)
        
        Returns:
            Portfolio heat as %
        """
        total_risk = 0.0
        
        for position in positions:
            # Calculate current risk
            position_value = position.current_price * position.quantity
            
            # Distance to stop loss
            if position.stop_loss and position.current_price > position.stop_loss:
                stop_distance_pct = (
                    (position.current_price - position.stop_loss) / position.current_price
                )
                position_risk = position_value * stop_distance_pct
            else:
                # Assume 2% risk if stop loss not set properly
                position_risk = position_value * 0.02
            
            total_risk += position_risk
        
        # Return as percentage
        portfolio_heat = (total_risk / portfolio_value) * 100 if portfolio_value > 0 else 0.0
        
        return portfolio_heat
