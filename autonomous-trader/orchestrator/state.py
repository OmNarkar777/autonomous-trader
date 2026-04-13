"""
orchestrator/state.py
======================
Trading state dataclass for LangGraph state machine.

The state flows through the entire trading pipeline:
  1. Start with symbol list
  2. Collect data for each symbol
  3. Make decision
  4. Execute trades
  5. Track results

State is updated at each step and passed to the next node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


@dataclass
class TradingState:
    """
    Complete state for the trading pipeline.
    
    This state is passed through all LangGraph nodes and
    accumulates data at each step.
    """
    
    # ── Input ──────────────────────────────────────────────────────────────
    symbols: List[str] = field(default_factory=list)
    current_symbol_index: int = 0
    
    # ── Current symbol being processed ─────────────────────────────────────
    current_symbol: str = ""
    company_name: str = ""
    
    # ── Data collection results ────────────────────────────────────────────
    price_data: Optional[Any] = None
    news_data: Optional[Any] = None
    macro_data: Optional[Any] = None
    earnings_data: Optional[Any] = None
    
    # ── Validation results ─────────────────────────────────────────────────
    validation_passed: bool = False
    data_quality_score: float = 0.0
    
    # ── Analysis results (TODO: implement analysis agents) ────────────────
    technical_score: float = 5.0
    fundamental_score: float = 5.0
    sentiment_score: float = 5.0
    ml_score: float = 0.5
    
    # ── Decision results ───────────────────────────────────────────────────
    decision: str = "HOLD"  # BUY | SELL | HOLD
    confidence: float = 0.0
    quantity: int = 0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    decision_reasoning: str = ""
    
    # ── Execution results ──────────────────────────────────────────────────
    trade_id: int = 0
    order_id: Optional[str] = None
    execution_status: str = ""
    
    # ── Cycle tracking ─────────────────────────────────────────────────────
    cycle_id: str = ""
    cycle_start_time: datetime = field(default_factory=datetime.utcnow)
    symbols_processed: int = 0
    symbols_skipped: int = 0
    trades_executed: int = 0
    
    # ── Results aggregation ────────────────────────────────────────────────
    all_decisions: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    # ── Circuit breaker ────────────────────────────────────────────────────
    consecutive_errors: int = 0
    circuit_open: bool = False
    
    def add_decision(self, decision_data: Dict[str, Any]) -> None:
        """Adds a decision to the results."""
        self.all_decisions.append(decision_data)
        self.symbols_processed += 1
        
        if decision_data.get("decision") in ["BUY", "SELL"]:
            self.trades_executed += 1
    
    def add_error(self, error: str) -> None:
        """Adds an error to the error list."""
        self.errors.append(error)
        self.consecutive_errors += 1
        self.symbols_skipped += 1
    
    def reset_error_counter(self) -> None:
        """Resets consecutive error counter (called after successful processing)."""
        self.consecutive_errors = 0
    
    def next_symbol(self) -> bool:
        """
        Moves to the next symbol in the list.
        
        Returns:
            True if there's another symbol to process, False if done
        """
        self.current_symbol_index += 1
        
        if self.current_symbol_index >= len(self.symbols):
            return False
        
        self.current_symbol = self.symbols[self.current_symbol_index]
        return True
    
    def get_summary(self) -> Dict[str, Any]:
        """Returns a summary of the trading cycle."""
        return {
            "cycle_id": self.cycle_id,
            "total_symbols": len(self.symbols),
            "processed": self.symbols_processed,
            "skipped": self.symbols_skipped,
            "trades_executed": self.trades_executed,
            "errors": len(self.errors),
            "duration_seconds": (datetime.utcnow() - self.cycle_start_time).total_seconds(),
            "circuit_open": self.circuit_open,
        }
