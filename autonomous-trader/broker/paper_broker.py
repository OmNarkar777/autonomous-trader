"""
broker/paper_broker.py
=======================
Paper trading broker - simulates real broker without real money.

Features:
  - Instant fills for market orders
  - Simulated slippage (0.1%)
  - Commission simulation ($0.01 per share)
  - Position tracking
  - Account balance tracking
  - Order history

Perfect for:
  - Testing strategies
  - Backtesting
  - Demo mode
  - Development

Usage:
    from broker.paper_broker import PaperBroker
    broker = PaperBroker(initial_capital=100000)
    broker.connect()
    
    response = broker.place_order("AAPL", "BUY", 10, "MARKET")
    print(f"Order ID: {response.order_id}, Status: {response.status}")
"""

from __future__ import annotations

from typing import Optional, List, Dict
from datetime import datetime, timezone
from dataclasses import asdict
import uuid

from broker.base_broker import (
    BaseBroker,
    OrderResponse,
    Position,
    AccountInfo,
    OrderStatus,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# PAPER BROKER
# ═══════════════════════════════════════════════════════════════

class PaperBroker(BaseBroker):
    """
    Simulated broker for paper trading.
    
    Tracks positions, cash, and orders in memory.
    Simulates realistic behavior (slippage, commissions).
    """
    
    def __init__(
        self,
        initial_capital: float = 100000.0,
        commission_per_share: float = 0.01,
        slippage_pct: float = 0.1,
    ):
        """
        Initializes paper broker.
        
        Args:
            initial_capital: Starting cash
            commission_per_share: Commission per share traded
            slippage_pct: Slippage as % (0.1 = 0.1%)
        """
        super().__init__(broker_name="Paper")
        
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_per_share = commission_per_share
        self.slippage_pct = slippage_pct
        
        # Storage
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Dict] = {}
        self.order_counter = 0
        
        # P&L tracking
        self.total_commissions = 0.0
        self.realized_pnl = 0.0
    
    # ── Connection ─────────────────────────────────────────────────────────
    
    def connect(self) -> bool:
        """Connects to paper broker (always succeeds)."""
        self.is_connected = True
        logger.info(
            f"[{self.broker_name}] Connected | "
            f"Initial capital: ${self.initial_capital:,.2f}"
        )
        return True
    
    def disconnect(self) -> None:
        """Disconnects from paper broker."""
        self.is_connected = False
        logger.info(f"[{self.broker_name}] Disconnected")
    
    # ── Order Placement ────────────────────────────────────────────────────
    
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> OrderResponse:
        """
        Places a paper trade order.
        
        Market orders are filled instantly.
        Limit/stop orders are stored but not auto-filled (would need price feed).
        """
        # Validate
        is_valid, error_msg = self.validate_order(symbol, side, quantity, order_type)
        if not is_valid:
            logger.error(f"[{self.broker_name}] Order validation failed: {error_msg}")
            return OrderResponse(
                order_id="",
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                status=OrderStatus.REJECTED.value,
                message=error_msg,
                timestamp=datetime.now(timezone.utc),
            )
        
        # Generate order ID
        self.order_counter += 1
        order_id = f"PAPER_{self.order_counter:06d}"
        
        # For paper trading, we need a price
        # In real usage, this comes from PriceCollector
        # For now, use limit_price if provided, else reject
        if order_type == "MARKET":
            if limit_price is None:
                return OrderResponse(
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    order_type=order_type,
                    status=OrderStatus.REJECTED.value,
                    message="Paper broker needs price for market orders (pass via limit_price)",
                    timestamp=datetime.now(timezone.utc),
                )
            
            # Instant fill for market orders
            return self._fill_market_order(
                order_id, symbol, side, quantity, limit_price
            )
        
        else:
            # Store limit/stop orders
            # In production, would need price monitoring to auto-fill
            self.orders[order_id] = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "limit_price": limit_price,
                "stop_price": stop_price,
                "status": OrderStatus.PENDING.value,
                "created_at": datetime.now(timezone.utc),
            }
            
            logger.info(
                f"[{self.broker_name}] {order_type} order placed | "
                f"ID: {order_id}, {side} {quantity} {symbol}"
            )
            
            return OrderResponse(
                order_id=order_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                status=OrderStatus.PENDING.value,
                message="Order pending (paper broker doesn't auto-fill limit/stop orders)",
                timestamp=datetime.now(timezone.utc),
            )
    
    def _fill_market_order(
        self,
        order_id: str,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
    ) -> OrderResponse:
        """Fills a market order instantly."""
        
        # Apply slippage
        if side == "BUY":
            fill_price = price * (1 + self.slippage_pct / 100)
        else:
            fill_price = price * (1 - self.slippage_pct / 100)
        
        # Calculate costs
        notional = fill_price * quantity
        commission = self.commission_per_share * quantity
        total_cost = notional + commission if side == "BUY" else notional - commission
        
        # Check buying power
        if side == "BUY" and total_cost > self.cash:
            logger.warning(
                f"[{self.broker_name}] Insufficient funds | "
                f"Need: ${total_cost:,.2f}, Have: ${self.cash:,.2f}"
            )
            return OrderResponse(
                order_id=order_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type="MARKET",
                status=OrderStatus.REJECTED.value,
                message=f"Insufficient funds (need ${total_cost:,.2f})",
                timestamp=datetime.now(timezone.utc),
            )
        
        # Execute trade
        if side == "BUY":
            self._execute_buy(symbol, quantity, fill_price, commission)
        else:
            self._execute_sell(symbol, quantity, fill_price, commission)
        
        # Store order
        self.orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": "MARKET",
            "fill_price": fill_price,
            "commission": commission,
            "status": OrderStatus.FILLED.value,
            "filled_at": datetime.now(timezone.utc),
        }
        
        logger.info(
            f"[{self.broker_name}] Order filled | "
            f"ID: {order_id}, {side} {quantity} {symbol} @ ${fill_price:.2f} | "
            f"Commission: ${commission:.2f}"
        )
        
        return OrderResponse(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type="MARKET",
            status=OrderStatus.FILLED.value,
            filled_quantity=quantity,
            filled_price=fill_price,
            message=f"Filled @ ${fill_price:.2f}",
            timestamp=datetime.now(timezone.utc),
        )
    
    def _execute_buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
        commission: float,
    ) -> None:
        """Executes a buy order."""
        cost = (price * quantity) + commission
        self.cash -= cost
        self.total_commissions += commission
        
        # Update position
        if symbol in self.positions:
            # Add to existing position
            pos = self.positions[symbol]
            total_quantity = pos.quantity + quantity
            total_cost = (pos.avg_entry_price * pos.quantity) + (price * quantity)
            new_avg_price = total_cost / total_quantity
            
            pos.quantity = total_quantity
            pos.avg_entry_price = new_avg_price
        else:
            # New position
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                avg_entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
            )
    
    def _execute_sell(
        self,
        symbol: str,
        quantity: int,
        price: float,
        commission: float,
    ) -> None:
        """Executes a sell order."""
        if symbol not in self.positions:
            logger.error(f"[{self.broker_name}] Cannot sell {symbol}: No position")
            return
        
        pos = self.positions[symbol]
        
        if quantity > pos.quantity:
            logger.error(
                f"[{self.broker_name}] Cannot sell {quantity} {symbol}: "
                f"Only have {pos.quantity}"
            )
            return
        
        # Calculate P&L
        pnl = (price - pos.avg_entry_price) * quantity
        proceeds = (price * quantity) - commission
        
        self.cash += proceeds
        self.total_commissions += commission
        self.realized_pnl += pnl
        
        # Update position
        pos.quantity -= quantity
        pos.realized_pnl = pos.realized_pnl + pnl if hasattr(pos, 'realized_pnl') else pnl
        
        # Remove position if fully closed
        if pos.quantity == 0:
            del self.positions[symbol]
    
    # ── Order Status ───────────────────────────────────────────────────────
    
    def get_order_status(self, order_id: str) -> OrderResponse:
        """Gets order status."""
        if order_id not in self.orders:
            return OrderResponse(
                order_id=order_id,
                symbol="",
                side="",
                quantity=0,
                order_type="",
                status=OrderStatus.REJECTED.value,
                message="Order not found",
                timestamp=datetime.now(timezone.utc),
            )
        
        order = self.orders[order_id]
        
        return OrderResponse(
            order_id=order_id,
            symbol=order["symbol"],
            side=order["side"],
            quantity=order["quantity"],
            order_type=order["order_type"],
            status=order["status"],
            filled_quantity=order.get("quantity", 0) if order["status"] == OrderStatus.FILLED.value else 0,
            filled_price=order.get("fill_price", 0.0),
            message="",
            timestamp=order.get("filled_at", order.get("created_at")),
        )
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancels an order."""
        if order_id not in self.orders:
            return False
        
        order = self.orders[order_id]
        
        if order["status"] == OrderStatus.FILLED.value:
            logger.warning(f"[{self.broker_name}] Cannot cancel filled order: {order_id}")
            return False
        
        order["status"] = OrderStatus.CANCELLED.value
        logger.info(f"[{self.broker_name}] Order cancelled: {order_id}")
        return True
    
    # ── Positions ──────────────────────────────────────────────────────────
    
    def get_positions(self) -> List[Position]:
        """Gets all positions."""
        return list(self.positions.values())
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Gets a specific position."""
        return self.positions.get(symbol)
    
    def update_position_prices(self, prices: Dict[str, float]) -> None:
        """
        Updates current prices for all positions.
        
        Args:
            prices: Dict mapping symbol → current_price
        """
        for symbol, pos in self.positions.items():
            if symbol in prices:
                pos.current_price = prices[symbol]
                pos.unrealized_pnl = (pos.current_price - pos.avg_entry_price) * pos.quantity
    
    # ── Account Info ───────────────────────────────────────────────────────
    
    def get_account_info(self) -> AccountInfo:
        """Gets account information."""
        # Calculate positions value
        positions_value = sum(
            pos.current_price * pos.quantity
            for pos in self.positions.values()
        )
        
        # Calculate unrealized P&L
        unrealized_pnl = sum(
            pos.unrealized_pnl
            for pos in self.positions.values()
        )
        
        portfolio_value = self.cash + positions_value
        
        return AccountInfo(
            buying_power=self.cash,
            portfolio_value=portfolio_value,
            cash=self.cash,
            positions_value=positions_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=self.realized_pnl,
        )
    
    # ── Utility ────────────────────────────────────────────────────────────
    
    def reset(self) -> None:
        """Resets paper broker to initial state."""
        self.cash = self.initial_capital
        self.positions.clear()
        self.orders.clear()
        self.order_counter = 0
        self.total_commissions = 0.0
        self.realized_pnl = 0.0
        logger.info(f"[{self.broker_name}] Reset to initial state")
