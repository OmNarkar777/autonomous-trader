"""
orchestrator/graph.py
======================
LangGraph state machine for autonomous trading.

Flow:
  START
    ↓
  Initialize (load watchlist, check market hours)
    ↓
  For each symbol:
    ↓
  Check Circuit Breaker
    ↓
  Make Decision (DecisionAgent)
    ↓
  Execute (ExecutionAgent if BUY/SELL)
    ↓
  Next symbol or END
    ↓
  Finalize (log summary, cleanup)
    ↓
  END

Usage:
    from orchestrator.graph import TradingGraph
    graph = TradingGraph()
    results = graph.run()
"""

from __future__ import annotations

from typing import Dict, Any
from datetime import datetime
import uuid

from langgraph.graph import StateGraph, END
from orchestrator.state import TradingState
from orchestrator.circuit_breaker import CircuitBreaker
from agents.decision_agent import DecisionAgent
from agents.execution_agent import ExecutionAgent
from data.storage.database import DatabaseManager
from data.collectors.macro_collector import MacroCollector
from config.settings import settings
from config.constants import INDIA_WATCHLIST, US_WATCHLIST, WATCHLIST_COMPANY_NAMES
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# TRADING GRAPH
# ═══════════════════════════════════════════════════════════════

class TradingGraph:
    """
    LangGraph-based orchestration of the autonomous trading system.
    
    Manages the entire trading cycle from data collection through execution.
    """
    
    def __init__(self, broker_type: str = "paper"):
        """
        Initializes the trading graph.
        
        Args:
            broker_type: "paper" | "zerodha" | "alpaca"
        """
        self.decision_agent = DecisionAgent()
        self.execution_agent = ExecutionAgent(broker_type=broker_type)
        self.circuit_breaker = CircuitBreaker()
        self.db = DatabaseManager()
        self.macro_collector = MacroCollector()
        
        # Build the graph
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """Builds the LangGraph state machine."""
        
        workflow = StateGraph(TradingState)
        
        # Add nodes
        workflow.add_node("initialize", self._initialize_node)
        workflow.add_node("check_circuit_breaker", self._check_circuit_breaker_node)
        workflow.add_node("make_decision", self._make_decision_node)
        workflow.add_node("execute_trade", self._execute_trade_node)
        workflow.add_node("next_symbol", self._next_symbol_node)
        workflow.add_node("finalize", self._finalize_node)
        
        # Set entry point
        workflow.set_entry_point("initialize")
        
        # Add edges
        workflow.add_edge("initialize", "check_circuit_breaker")
        
        # From circuit breaker: if open → finalize, else → make decision
        workflow.add_conditional_edges(
            "check_circuit_breaker",
            self._should_continue_trading,
            {
                "continue": "make_decision",
                "stop": "finalize",
            }
        )
        
        workflow.add_edge("make_decision", "execute_trade")
        workflow.add_edge("execute_trade", "next_symbol")
        
        # From next_symbol: if more symbols → circuit breaker, else → finalize
        workflow.add_conditional_edges(
            "next_symbol",
            self._has_more_symbols,
            {
                "continue": "check_circuit_breaker",
                "done": "finalize",
            }
        )
        
        workflow.add_edge("finalize", END)
        
        return workflow.compile()
    
    # ── Node Functions ─────────────────────────────────────────────────────
    
    def _initialize_node(self, state: TradingState) -> TradingState:
        """
        Initializes the trading cycle.
        
        - Generates cycle ID
        - Loads watchlist
        - Checks market hours
        - Sets up initial state
        """
        logger.info("═══════════════════════════════════════════════════════")
        logger.info("  AUTONOMOUS TRADING CYCLE STARTING")
        logger.info("═══════════════════════════════════════════════════════")
        
        # Generate cycle ID
        state.cycle_id = f"cycle_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        state.cycle_start_time = datetime.utcnow()
        
        logger.info(f"Cycle ID: {state.cycle_id}")
        
        # ── Load watchlist ─────────────────────────────────────────────────
        if settings.TARGET_MARKET == "india":
            state.symbols = INDIA_WATCHLIST.copy()
        elif settings.TARGET_MARKET == "us":
            state.symbols = US_WATCHLIST.copy()
        else:
            state.symbols = INDIA_WATCHLIST + US_WATCHLIST
        
        logger.info(f"Watchlist loaded: {len(state.symbols)} symbols")
        
        # ── Check market hours ─────────────────────────────────────────────
        # TODO: Implement market hours check
        # For now, always proceed
        
        # ── Initialize first symbol ───────────────────────────────────────
        if state.symbols:
            state.current_symbol = state.symbols[0]
            state.current_symbol_index = 0
            state.company_name = WATCHLIST_COMPANY_NAMES.get(state.current_symbol, "")
            logger.info(f"Starting with symbol: {state.current_symbol}")
        
        return state
    
    def _check_circuit_breaker_node(self, state: TradingState) -> TradingState:
        """
        Checks the circuit breaker status.
        
        If too many consecutive errors, opens the circuit and halts trading.
        """
        if self.circuit_breaker.is_open():
            logger.error(
                "⚠️ CIRCUIT BREAKER OPEN — Trading halted due to excessive errors"
            )
            state.circuit_open = True
            return state
        
        # Check if we should open the circuit
        if state.consecutive_errors >= self.circuit_breaker.error_threshold:
            self.circuit_breaker.open_circuit(
                reason=f"Consecutive errors: {state.consecutive_errors}"
            )
            state.circuit_open = True
            logger.error(
                f"⚠️ CIRCUIT BREAKER TRIGGERED — "
                f"{state.consecutive_errors} consecutive errors"
            )
        
        return state
    
    def _make_decision_node(self, state: TradingState) -> TradingState:
        """
        Runs the DecisionAgent to make a trading decision.
        """
        logger.info(f"[{state.current_symbol}] Running DecisionAgent")
        
        try:
            result = self.decision_agent.run(
                symbol=state.current_symbol,
                company_name=state.company_name,
            )
            
            if not result.success:
                logger.error(
                    f"[{state.current_symbol}] DecisionAgent failed: {result.error}"
                )
                state.add_error(f"{state.current_symbol}: {result.error}")
                state.decision = "HOLD"
                return state
            
            # Extract decision data
            decision_output = result.data
            
            state.decision = decision_output.decision
            state.confidence = decision_output.confidence
            state.quantity = decision_output.quantity
            state.entry_price = decision_output.entry_price
            state.stop_loss = decision_output.stop_loss
            state.take_profit = decision_output.take_profit
            state.decision_reasoning = decision_output.reasoning
            
            # Store full decision
            state.add_decision({
                "symbol": state.current_symbol,
                "decision": decision_output.decision,
                "confidence": decision_output.confidence,
                "quantity": decision_output.quantity,
                "entry_price": decision_output.entry_price,
                "reasoning": decision_output.reasoning,
            })
            
            # Reset error counter on success
            state.reset_error_counter()
            
            logger.info(
                f"[{state.current_symbol}] Decision: {state.decision} | "
                f"Confidence: {state.confidence:.1%}"
            )
        
        except Exception as e:
            logger.error(
                f"[{state.current_symbol}] DecisionAgent crashed: {e}",
                exc_info=True
            )
            state.add_error(f"{state.current_symbol}: Agent crashed - {e}")
            state.decision = "HOLD"
        
        return state
    
    def _execute_trade_node(self, state: TradingState) -> TradingState:
        """
        Executes the trade via ExecutionAgent if decision is BUY or SELL.
        """
        if state.decision == "HOLD":
            logger.debug(f"[{state.current_symbol}] HOLD decision — no execution")
            return state
        
        logger.info(
            f"[{state.current_symbol}] Executing {state.decision} order | "
            f"Qty: {state.quantity}"
        )
        
        try:
            result = self.execution_agent.run(
                symbol=state.current_symbol,
                action=state.decision,
                quantity=state.quantity,
                price=state.entry_price,
                stop_loss=state.stop_loss,
                take_profit=state.take_profit,
                confidence=state.confidence,
                decision_reasoning={
                    "reasoning": state.decision_reasoning,
                    "confidence": state.confidence,
                },
            )
            
            if not result.success:
                logger.error(
                    f"[{state.current_symbol}] Execution failed: {result.error}"
                )
                state.add_error(f"{state.current_symbol}: Execution failed - {result.error}")
                return state
            
            # Extract execution data
            execution_output = result.data
            
            state.trade_id = execution_output.trade_id
            state.order_id = execution_output.order_id
            state.execution_status = execution_output.status
            
            logger.info(
                f"[{state.current_symbol}] Execution complete | "
                f"Trade ID: {state.trade_id}, Status: {state.execution_status}"
            )
        
        except Exception as e:
            logger.error(
                f"[{state.current_symbol}] Execution crashed: {e}",
                exc_info=True
            )
            state.add_error(f"{state.current_symbol}: Execution crashed - {e}")
        
        return state
    
    def _next_symbol_node(self, state: TradingState) -> TradingState:
        """Moves to the next symbol in the watchlist."""
        has_next = state.next_symbol()
        
        if has_next:
            state.company_name = WATCHLIST_COMPANY_NAMES.get(state.current_symbol, "")
            logger.info(
                f"Moving to next symbol ({state.current_symbol_index + 1}/{len(state.symbols)}): "
                f"{state.current_symbol}"
            )
        else:
            logger.info("All symbols processed")
        
        return state
    
    def _finalize_node(self, state: TradingState) -> TradingState:
        """
        Finalizes the trading cycle.
        
        - Logs summary
        - Cleans up resources
        - Resets circuit breaker if successful
        """
        summary = state.get_summary()
        
        logger.info("═══════════════════════════════════════════════════════")
        logger.info("  TRADING CYCLE COMPLETE")
        logger.info("═══════════════════════════════════════════════════════")
        logger.info(f"Cycle ID: {summary['cycle_id']}")
        logger.info(f"Duration: {summary['duration_seconds']:.1f}s")
        logger.info(f"Symbols processed: {summary['processed']}/{summary['total_symbols']}")
        logger.info(f"Trades executed: {summary['trades_executed']}")
        logger.info(f"Errors: {summary['errors']}")
        if summary['circuit_open']:
            logger.warning("⚠️ Circuit breaker: OPEN")
        
        # Log cycle summary to database
        self.db.log_event(
            event_type="TRADING_CYCLE_COMPLETE",
            agent_name="TradingGraph",
            message=f"Cycle {summary['cycle_id']} complete",
            data=summary,
            severity="INFO" if not summary['circuit_open'] else "WARNING",
        )
        
        # Reset circuit breaker if cycle was successful
        if not summary['circuit_open'] and summary['errors'] == 0:
            self.circuit_breaker.reset()
        
        return state
    
    # ── Conditional Edge Functions ────────────────────────────────────────
    
    def _should_continue_trading(self, state: TradingState) -> str:
        """Determines if trading should continue or stop."""
        if state.circuit_open:
            return "stop"
        return "continue"
    
    def _has_more_symbols(self, state: TradingState) -> str:
        """Determines if there are more symbols to process."""
        if state.current_symbol_index >= len(state.symbols) - 1:
            return "done"
        return "continue"
    
    # ── Public API ─────────────────────────────────────────────────────────
    
    def run(self) -> Dict[str, Any]:
        """
        Runs the complete trading cycle.
        
        Returns:
            Summary of the trading cycle
        """
        # Initialize state
        initial_state = TradingState()
        
        # Run the graph
        final_state = self.graph.invoke(initial_state)
        
        # Return summary
        return final_state.get("summary", {"status": "completed"}) if isinstance(final_state, dict) else final_state.get_summary()
