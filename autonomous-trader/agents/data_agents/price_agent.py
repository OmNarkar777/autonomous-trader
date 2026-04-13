"""
agents/data_agents/price_agent.py
===================================
Price Data Agent - fetches and validates current and historical price data.

Responsibilities:
  1. Fetch current price from PriceCollector
  2. Fetch historical OHLCV data
  3. Validate price data quality
  4. Cache results for this trading cycle

Output:
  - current_price: PriceData object
  - historical_data: DataFrame with OHLCV + technical features
  - validation_result: ValidationResult

Usage:
    from agents.data_agents.price_agent import PriceAgent
    agent = PriceAgent()
    result = agent.run(symbol="RELIANCE.NS")
    
    if result.success:
        price_data = result.data["current_price"]
        historical_df = result.data["historical_data"]
"""

from __future__ import annotations

from typing import Dict, Any
from dataclasses import dataclass

from agents.base_agent import BaseAgent, AgentResult
from data.collectors.price_collector import PriceCollector, PriceData
from data.validators.data_validator import DataValidator
from data.storage.cache import cache
from config.constants import ML_TRAINING_PERIOD
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class PriceAgentOutput:
    """Structured output from PriceAgent."""
    symbol: str
    current_price: PriceData
    historical_data: Any  # pd.DataFrame (avoiding import for type hint)
    is_valid: bool
    validation_issues: list
    data_quality_score: float


# ═══════════════════════════════════════════════════════════════
# PRICE AGENT
# ═══════════════════════════════════════════════════════════════

class PriceAgent(BaseAgent):
    """
    Agent responsible for fetching and validating price data.
    
    This is the first data agent in the pipeline - if price data
    is invalid, the entire symbol is skipped for this trading cycle.
    """
    
    def __init__(self):
        super().__init__(agent_name="PriceAgent")
        self.price_collector = PriceCollector()
        self.validator = DataValidator()
    
    def execute(self, symbol: str, **kwargs) -> AgentResult:
        """
        Fetches and validates price data for a symbol.
        
        Args:
            symbol: Stock symbol to fetch data for
            **kwargs: Additional parameters (currently unused)
        
        Returns:
            AgentResult with PriceAgentOutput in data field
        """
        self.logger.info(f"[{symbol}] Fetching price data")
        
        # ── Check cache first ──────────────────────────────────────────────
        cached_output = cache.get_cached_agent_output("PriceAgent", symbol)
        if cached_output:
            self.logger.debug(f"[{symbol}] Using cached price data")
            return self.success_result(
                data=cached_output,
                metadata={"source": "cache"}
            )
        
        # ── Fetch current price ────────────────────────────────────────────
        try:
            current_price = self.price_collector.get_current_price(symbol)
            self.logger.debug(
                f"[{symbol}] Current price: {current_price.current_price:.2f}, "
                f"Volume: {current_price.volume:,}"
            )
        except Exception as e:
            self.logger.error(f"[{symbol}] Failed to fetch current price: {e}")
            return self.failure_result(
                error=f"Current price fetch failed: {e}",
                metadata={"symbol": symbol}
            )
        
        # ── Fetch historical data ──────────────────────────────────────────
        try:
            historical_data = self.price_collector.get_historical_data(
                symbol,
                period=ML_TRAINING_PERIOD,
                interval="1d"
            )
            self.logger.debug(
                f"[{symbol}] Historical data: {len(historical_data)} days, "
                f"{historical_data.index.min().date()} to {historical_data.index.max().date()}"
            )
        except Exception as e:
            self.logger.error(f"[{symbol}] Failed to fetch historical data: {e}")
            return self.failure_result(
                error=f"Historical data fetch failed: {e}",
                metadata={"symbol": symbol}
            )
        
        # ── Quick validation (price-only) ──────────────────────────────────
        if not self.validator.quick_validate_price(symbol, current_price):
            self.logger.warning(f"[{symbol}] Price data failed quick validation")
            return self.failure_result(
                error="Price data quality check failed (stale or invalid)",
                metadata={
                    "symbol": symbol,
                    "price": current_price.current_price,
                    "age_minutes": (
                        (current_price.timestamp - current_price.timestamp).total_seconds() / 60
                    ),
                }
            )
        
        # ── Quick validation (history-only) ────────────────────────────────
        if not self.validator.quick_validate_history(historical_data):
            self.logger.warning(f"[{symbol}] Historical data failed quick validation")
            return self.failure_result(
                error="Historical data quality check failed (insufficient or invalid)",
                metadata={
                    "symbol": symbol,
                    "days_available": len(historical_data),
                }
            )
        
        # ── Create output ──────────────────────────────────────────────────
        output = PriceAgentOutput(
            symbol=symbol,
            current_price=current_price,
            historical_data=historical_data,
            is_valid=True,
            validation_issues=[],
            data_quality_score=1.0,  # Full validation happens in DataValidator
        )
        
        # ── Cache the output ───────────────────────────────────────────────
        cache.cache_agent_output(
            "PriceAgent",
            symbol,
            {
                "symbol": symbol,
                "current_price": current_price.__dict__,
                "historical_data_shape": historical_data.shape,
                "is_valid": output.is_valid,
            },
            ttl=300  # 5 minutes
        )
        
        return self.success_result(
            data=output,
            metadata={
                "symbol": symbol,
                "current_price": current_price.current_price,
                "historical_days": len(historical_data),
                "source": "fresh_fetch"
            }
        )
