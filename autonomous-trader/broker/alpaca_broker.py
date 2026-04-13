"""
broker/alpaca_broker.py
========================
Alpaca API integration for US market trading.

Requires:
  - pip install alpaca-trade-api
  - Alpaca account (https://alpaca.markets)
  - API key and secret

Features:
  - Commission-free trading
  - Paper trading mode available
  - Market and limit orders
  - Real-time positions and account data

Configuration (in .env):
  ALPACA_API_KEY=your_api_key
  ALPACA_API_SECRET=your_api_secret
  ALPACA_BASE_URL=https://paper-api.alpaca.markets  # or https://api.alpaca.markets for live

Usage:
    from broker.alpaca_broker import AlpacaBroker
    broker = AlpacaBroker()
    broker.connect()
    
    response = broker.place_order("AAPL", "BUY", 10, "MARKET")
"""

from __future__ import annotations

from typing import Optional, List
from datetime import datetime, timezone

from broker.base_broker import (
    BaseBroker,
    OrderResponse,
    Position,
    AccountInfo,
    OrderStatus,
)
from config.settings import settings
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# ALPACA BROKER
# ═══════════════════════════════════════════════════════════════

class AlpacaBroker(BaseBroker):
    """
    Alpaca API integration for US market trading.
    
    Supports paper trading and live trading.
    """
    
    def __init__(self, paper_trading: bool = True):
        """
        Initializes Alpaca broker.
        
        Args:
            paper_trading: If True, uses paper trading endpoint
        """
        super().__init__(broker_name="Alpaca")
        
        self.api_key = settings.ALPACA_API_KEY
        self.api_secret = settings.ALPACA_API_SECRET
        
        # Set base URL based on paper/live mode
        if paper_trading:
            self.base_url = "https://paper-api.alpaca.markets"
        else:
            self.base_url = settings.ALPACA_BASE_URL or "https://api.alpaca.markets"
        
        self.api = None
    
    # ── Connection ─────────────────────────────────────────────────────────
    
    def connect(self) -> bool:
        """Connects to Alpaca API."""
        try:
            from alpaca_trade_api import REST
        except ImportError:
            logger.error(
                "alpaca-trade-api library not installed. "
                "Install with: pip install alpaca-trade-api"
            )
            return False
        
        if not self.api_key or not self.api_secret:
            logger.error(
                "Alpaca credentials not configured. "
                "Set ALPACA_API_KEY and ALPACA_API_SECRET in .env"
            )
            return False
        
        try:
            self.api = REST(
                key_id=self.api_key,
                secret_key=self.api_secret,
                base_url=self.base_url,
            )
            
            # Test connection
            account = self.api.get_account()
            
            self.is_connected = True
            logger.info(
                f"[{self.broker_name}] Connected | "
                f"Account: {account.account_number} | "
                f"Mode: {'Paper' if 'paper' in self.base_url else 'Live'}"
            )
            return True
        
        except Exception as e:
            logger.error(f"[{self.broker_name}] Connection failed: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnects from Alpaca API."""
        self.is_connected = False
        self.api = None
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
        """Places an order via Alpaca."""
        if not self.is_connected or not self.api:
            logger.error(f"[{self.broker_name}] Not connected")
            return OrderResponse(
                order_id="",
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                status=OrderStatus.REJECTED.value,
                message="Not connected to broker",
                timestamp=datetime.now(timezone.utc),
            )
        
        # Validate
        is_valid, error_msg = self.validate_order(symbol, side, quantity, order_type)
        if not is_valid:
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
        
        try:
            # Map order type
            alpaca_order_type = order_type.lower()
            if order_type == "STOP_LOSS":
                alpaca_order_type = "stop"
            
            # Build order params
            order_params = {
                "symbol": symbol,
                "qty": quantity,
                "side": side.lower(),
                "type": alpaca_order_type,
                "time_in_force": "day",  # Day order
            }
            
            # Add price parameters
            if order_type == "LIMIT" and limit_price:
                order_params["limit_price"] = limit_price
            elif order_type == "STOP_LOSS" and stop_price:
                order_params["stop_price"] = stop_price
            
            # Submit order
            order = self.api.submit_order(**order_params)
            
            logger.info(
                f"[{self.broker_name}] Order placed | "
                f"ID: {order.id}, {side} {quantity} {symbol}"
            )
            
            return OrderResponse(
                order_id=order.id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                status=self._map_order_status(order.status),
                message="Order submitted",
                timestamp=datetime.now(timezone.utc),
            )
        
        except Exception as e:
            logger.error(f"[{self.broker_name}] Order placement failed: {e}")
            return OrderResponse(
                order_id="",
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                status=OrderStatus.REJECTED.value,
                message=f"Order rejected: {e}",
                timestamp=datetime.now(timezone.utc),
            )
    
    def _map_order_status(self, alpaca_status: str) -> str:
        """Maps Alpaca order status to our OrderStatus."""
        mapping = {
            "new": OrderStatus.SUBMITTED.value,
            "accepted": OrderStatus.ACCEPTED.value,
            "filled": OrderStatus.FILLED.value,
            "partially_filled": OrderStatus.PARTIAL_FILL.value,
            "canceled": OrderStatus.CANCELLED.value,
            "rejected": OrderStatus.REJECTED.value,
            "expired": OrderStatus.EXPIRED.value,
        }
        return mapping.get(alpaca_status, OrderStatus.PENDING.value)
    
    # ── Order Status ───────────────────────────────────────────────────────
    
    def get_order_status(self, order_id: str) -> OrderResponse:
        """Gets order status from Alpaca."""
        if not self.is_connected or not self.api:
            return OrderResponse(
                order_id=order_id,
                symbol="",
                side="",
                quantity=0,
                order_type="",
                status=OrderStatus.REJECTED.value,
                message="Not connected",
                timestamp=datetime.now(timezone.utc),
            )
        
        try:
            order = self.api.get_order(order_id)
            
            return OrderResponse(
                order_id=order.id,
                symbol=order.symbol,
                side=order.side.upper(),
                quantity=int(order.qty),
                order_type=order.type.upper(),
                status=self._map_order_status(order.status),
                filled_quantity=int(order.filled_qty) if order.filled_qty else 0,
                filled_price=float(order.filled_avg_price) if order.filled_avg_price else 0.0,
                message="",
                timestamp=order.submitted_at,
            )
        
        except Exception as e:
            logger.error(f"[{self.broker_name}] Get order status failed: {e}")
            return OrderResponse(
                order_id=order_id,
                symbol="",
                side="",
                quantity=0,
                order_type="",
                status=OrderStatus.REJECTED.value,
                message=f"Error: {e}",
                timestamp=datetime.now(timezone.utc),
            )
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancels an order."""
        if not self.is_connected or not self.api:
            return False
        
        try:
            self.api.cancel_order(order_id)
            logger.info(f"[{self.broker_name}] Order cancelled: {order_id}")
            return True
        
        except Exception as e:
            logger.error(f"[{self.broker_name}] Cancel order failed: {e}")
            return False
    
    # ── Positions ──────────────────────────────────────────────────────────
    
    def get_positions(self) -> List[Position]:
        """Gets all positions from Alpaca."""
        if not self.is_connected or not self.api:
            return []
        
        try:
            positions_data = self.api.list_positions()
            
            positions = []
            for pos in positions_data:
                positions.append(Position(
                    symbol=pos.symbol,
                    quantity=int(pos.qty),
                    avg_entry_price=float(pos.avg_entry_price),
                    current_price=float(pos.current_price),
                    unrealized_pnl=float(pos.unrealized_pl),
                    realized_pnl=0.0,  # Not provided by Alpaca per position
                ))
            
            return positions
        
        except Exception as e:
            logger.error(f"[{self.broker_name}] Get positions failed: {e}")
            return []
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Gets a specific position."""
        if not self.is_connected or not self.api:
            return None
        
        try:
            pos = self.api.get_position(symbol)
            
            return Position(
                symbol=pos.symbol,
                quantity=int(pos.qty),
                avg_entry_price=float(pos.avg_entry_price),
                current_price=float(pos.current_price),
                unrealized_pnl=float(pos.unrealized_pl),
                realized_pnl=0.0,
            )
        
        except Exception as e:
            logger.debug(f"[{self.broker_name}] No position for {symbol}: {e}")
            return None
    
    # ── Account Info ───────────────────────────────────────────────────────
    
    def get_account_info(self) -> AccountInfo:
        """Gets account information from Alpaca."""
        if not self.is_connected or not self.api:
            return AccountInfo(
                buying_power=0.0,
                portfolio_value=0.0,
                cash=0.0,
                positions_value=0.0,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
            )
        
        try:
            account = self.api.get_account()
            
            return AccountInfo(
                buying_power=float(account.buying_power),
                portfolio_value=float(account.portfolio_value),
                cash=float(account.cash),
                positions_value=float(account.long_market_value),
                unrealized_pnl=float(account.unrealized_pl),
                realized_pnl=float(account.realized_pl),
            )
        
        except Exception as e:
            logger.error(f"[{self.broker_name}] Get account info failed: {e}")
            return AccountInfo(
                buying_power=0.0,
                portfolio_value=0.0,
                cash=0.0,
                positions_value=0.0,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
            )
