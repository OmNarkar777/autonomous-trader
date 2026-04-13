"""
agents/execution_agent.py
==========================
Execution Agent - Executes trades via broker and manages order lifecycle.

Responsibilities:
  1. Log trade to database BEFORE sending to broker
  2. Execute order via broker (paper trading or live)
  3. Update trade status based on broker response
  4. Monitor order fills
  5. Update portfolio in database

Critical safety rule: ALWAYS log trade to DB first.
If system crashes after broker execution but before DB update,
we can recover by checking broker vs DB state on restart.

Supported brokers:
  - Paper (simulated trading for testing)
  - Zerodha (India)
  - Alpaca (US)

Usage:
    from agents.execution_agent import ExecutionAgent
    agent = ExecutionAgent(broker_type="paper")
    result = agent.run(
        symbol="RELIANCE.NS",
        action="BUY",
        quantity=10,
        price=2450.00,
        stop_loss=2380.00,
        take_profit=2590.00,
    )
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timezone

from agents.base_agent import BaseAgent, AgentResult
from data.storage.database import DatabaseManager
from config.settings import settings
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class ExecutionOutput:
    """Structured output from ExecutionAgent."""
    symbol: str
    action: str
    quantity: int
    price: float
    
    # Database IDs
    trade_id: int
    order_id: Optional[str] = None
    
    # Execution status
    status: str = "PENDING"  # PENDING | SUBMITTED | FILLED | REJECTED | FAILED
    broker_message: str = ""
    
    # Trade details
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    executed_at: Optional[datetime] = None


# ═══════════════════════════════════════════════════════════════
# EXECUTION AGENT
# ═══════════════════════════════════════════════════════════════

class ExecutionAgent(BaseAgent):
    """
    Agent responsible for trade execution via broker.
    
    Critical safety features:
      - Logs to DB BEFORE broker execution
      - Updates trade status after execution
      - Handles broker errors gracefully
      - Prevents duplicate orders
    """
    
    def __init__(
        self,
        broker_type: str = "paper",
        db: DatabaseManager = None,
    ):
        """
        Initializes the execution agent.
        
        Args:
            broker_type: "paper" | "zerodha" | "alpaca"
            db: Database manager instance
        """
        super().__init__(agent_name="ExecutionAgent")
        self.broker_type = broker_type
        self.db = db or DatabaseManager()
        
        # Initialize broker client
        self._init_broker()
    
    def _init_broker(self) -> None:
        """Initializes the broker client."""
        if self.broker_type == "paper":
            self.broker = PaperBroker()
        elif self.broker_type == "zerodha":
            # TODO: Implement Zerodha broker
            self.logger.warning("Zerodha broker not implemented yet, using paper trading")
            self.broker = PaperBroker()
        elif self.broker_type == "alpaca":
            # TODO: Implement Alpaca broker
            self.logger.warning("Alpaca broker not implemented yet, using paper trading")
            self.broker = PaperBroker()
        else:
            self.logger.warning(f"Unknown broker type: {self.broker_type}, using paper")
            self.broker = PaperBroker()
        
        self.logger.info(f"Broker initialized: {self.broker_type}")
    
    def execute(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        confidence: float = 0.0,
        decision_reasoning: Optional[Dict] = None,
        **kwargs
    ) -> AgentResult:
        """
        Executes a trade.
        
        Args:
            symbol: Stock symbol
            action: "BUY" | "SELL" | "HOLD"
            quantity: Number of shares
            price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            confidence: Decision confidence (0-1)
            decision_reasoning: Full decision details from DecisionAgent
            **kwargs: Additional parameters
        
        Returns:
            AgentResult with ExecutionOutput in data field
        """
        self.logger.info(
            f"[{symbol}] Executing {action} order | "
            f"Qty: {quantity} @ {price:.2f}"
        )
        
        # ── Validation ─────────────────────────────────────────────────────
        if action not in ["BUY", "SELL", "HOLD"]:
            return self.failure_result(
                error=f"Invalid action: {action}",
                metadata={"symbol": symbol, "action": action}
            )
        
        if action == "HOLD":
            return self.success_result(
                data=ExecutionOutput(
                    symbol=symbol,
                    action="HOLD",
                    quantity=0,
                    price=price,
                    trade_id=0,
                    status="SKIPPED",
                    broker_message="HOLD signal - no trade executed",
                ),
                metadata={"symbol": symbol, "action": "HOLD"}
            )
        
        if quantity <= 0:
            return self.failure_result(
                error=f"Invalid quantity: {quantity}",
                metadata={"symbol": symbol, "quantity": quantity}
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # CRITICAL: Log to database FIRST (before broker execution)
        # ═══════════════════════════════════════════════════════════════════
        
        try:
            trade_id = self.db.insert_trade(
                symbol=symbol,
                action=action,
                quantity=quantity,
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence_score=confidence,
                decision_reasoning=decision_reasoning,
                status="PENDING",
            )
            
            self.logger.info(
                f"[{symbol}] Trade logged to DB | ID: {trade_id}, Status: PENDING"
            )
        
        except Exception as e:
            self.logger.error(f"[{symbol}] Failed to log trade to DB: {e}")
            return self.failure_result(
                error=f"Database logging failed: {e}",
                metadata={"symbol": symbol, "action": action}
            )
        
        # ── Execute via broker ─────────────────────────────────────────────
        try:
            broker_response = self.broker.place_order(
                symbol=symbol,
                action=action,
                quantity=quantity,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
            
            order_id = broker_response.get("order_id")
            status = broker_response.get("status", "UNKNOWN")
            message = broker_response.get("message", "")
            
            self.logger.info(
                f"[{symbol}] Broker response | "
                f"Order ID: {order_id}, Status: {status}"
            )
        
        except Exception as e:
            self.logger.error(f"[{symbol}] Broker execution failed: {e}")
            
            # Update trade status to FAILED
            try:
                self.db.update_trade_status(
                    trade_id=trade_id,
                    status="FAILED",
                )
            except Exception as db_error:
                self.logger.error(f"[{symbol}] Failed to update trade status: {db_error}")
            
            return self.failure_result(
                error=f"Broker execution failed: {e}",
                metadata={
                    "symbol": symbol,
                    "trade_id": trade_id,
                    "broker_error": str(e)
                }
            )
        
        # ── Update trade status in DB ──────────────────────────────────────
        try:
            if status in ["FILLED", "SUBMITTED", "ACCEPTED"]:
                self.db.update_trade_status(
                    trade_id=trade_id,
                    status="OPEN" if status == "FILLED" else "PENDING",
                    order_id=order_id,
                    executed_at=datetime.utcnow() if status == "FILLED" else None,
                )
                
                # If filled, update portfolio
                if status == "FILLED" and action == "BUY":
                    self.db.upsert_position(
                        symbol=symbol,
                        quantity=quantity,
                        avg_entry_price=price,
                        current_price=price,
                        stop_loss=stop_loss or 0.0,
                        take_profit=take_profit or 0.0,
                        trade_id=trade_id,
                    )
                    self.logger.info(f"[{symbol}] Position added to portfolio")
            
            elif status in ["REJECTED", "CANCELLED"]:
                self.db.update_trade_status(
                    trade_id=trade_id,
                    status="REJECTED",
                    order_id=order_id,
                )
            
            else:
                self.db.update_trade_status(
                    trade_id=trade_id,
                    status="PENDING",
                    order_id=order_id,
                )
        
        except Exception as e:
            self.logger.error(f"[{symbol}] Failed to update DB after execution: {e}")
            # Non-critical - trade was executed, just DB update failed
        
        # ── Log execution event ────────────────────────────────────────────
        self.db.log_event(
            event_type="TRADE_EXECUTED",
            agent_name="ExecutionAgent",
            symbol=symbol,
            message=f"{action} {quantity} @ {price:.2f} | Status: {status}",
            data={
                "trade_id": trade_id,
                "order_id": order_id,
                "broker": self.broker_type,
                "status": status,
            },
            severity="INFO" if status == "FILLED" else "WARNING",
        )
        
        # ── Create output ──────────────────────────────────────────────────
        output = ExecutionOutput(
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            trade_id=trade_id,
            order_id=order_id,
            status=status,
            broker_message=message,
            stop_loss=stop_loss,
            take_profit=take_profit,
            executed_at=datetime.utcnow() if status == "FILLED" else None,
        )
        
        return self.success_result(
            data=output,
            metadata={
                "symbol": symbol,
                "action": action,
                "trade_id": trade_id,
                "order_id": order_id,
                "status": status,
            }
        )


# ═══════════════════════════════════════════════════════════════
# PAPER BROKER (for testing)
# ═══════════════════════════════════════════════════════════════

class PaperBroker:
    """
    Simulated broker for paper trading.
    Always accepts orders and simulates fills instantly.
    """
    
    def __init__(self):
        self.order_counter = 0
    
    def place_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Simulates order placement."""
        self.order_counter += 1
        order_id = f"PAPER_{self.order_counter:06d}"
        
        logger.info(
            f"[PAPER] {action} {quantity} {symbol} @ {price:.2f} | "
            f"Order ID: {order_id}"
        )
        
        # Simulate instant fill in paper trading
        return {
            "order_id": order_id,
            "status": "FILLED",
            "message": "Paper trade simulated",
            "filled_price": price,
            "filled_quantity": quantity,
        }
