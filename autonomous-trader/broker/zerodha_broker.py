"""
broker/zerodha_broker.py
=========================
Zerodha Kite Connect API integration for Indian market trading.

Requires:
  - pip install kiteconnect
  - Zerodha trading account
  - API key from https://kite.trade/

Authentication:
  1. Get API key and secret from Zerodha
  2. Login via browser to get request token
  3. Exchange request token for access token
  4. Access token valid for 1 day

Configuration (in .env):
  ZERODHA_API_KEY=your_api_key
  ZERODHA_API_SECRET=your_api_secret
  ZERODHA_ACCESS_TOKEN=your_access_token

Usage:
    from broker.zerodha_broker import ZerodhaBroker
    broker = ZerodhaBroker()
    broker.connect()  # Uses credentials from settings
    
    response = broker.place_order("RELIANCE", "BUY", 10, "MARKET")
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
# ZERODHA BROKER
# ═══════════════════════════════════════════════════════════════

class ZerodhaBroker(BaseBroker):
    """
    Zerodha Kite Connect API integration.
    
    Supports NSE and BSE trading (Indian markets).
    """
    
    def __init__(self):
        """Initializes Zerodha broker."""
        super().__init__(broker_name="Zerodha")
        
        self.api_key = settings.ZERODHA_API_KEY
        self.api_secret = settings.ZERODHA_API_SECRET
        self.access_token = settings.ZERODHA_ACCESS_TOKEN
        
        self.kite = None
    
    # ── Connection ─────────────────────────────────────────────────────────
    
    def connect(self) -> bool:
        """Connects to Zerodha Kite API."""
        try:
            from kiteconnect import KiteConnect
        except ImportError:
            logger.error(
                "kiteconnect library not installed. "
                "Install with: pip install kiteconnect"
            )
            return False
        
        if not self.api_key or not self.access_token:
            logger.error(
                "Zerodha credentials not configured. "
                "Set ZERODHA_API_KEY and ZERODHA_ACCESS_TOKEN in .env"
            )
            return False
        
        try:
            self.kite = KiteConnect(api_key=self.api_key)
            self.kite.set_access_token(self.access_token)
            
            # Test connection
            profile = self.kite.profile()
            
            self.is_connected = True
            logger.info(
                f"[{self.broker_name}] Connected | "
                f"User: {profile['user_name']} ({profile['email']})"
            )
            return True
        
        except Exception as e:
            logger.error(f"[{self.broker_name}] Connection failed: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnects from Zerodha API."""
        self.is_connected = False
        self.kite = None
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
        """Places an order via Zerodha."""
        if not self.is_connected or not self.kite:
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
        
        # Map to Kite parameters
        kite_order_type = self._map_order_type(order_type)
        kite_transaction_type = "BUY" if side == "BUY" else "SELL"
        
        try:
            # Place order
            order_params = {
                "tradingsymbol": symbol,
                "exchange": self._get_exchange(symbol),
                "transaction_type": kite_transaction_type,
                "quantity": quantity,
                "order_type": kite_order_type,
                "product": "CNC",  # Delivery trading (cash and carry)
                "variety": "regular",
            }
            
            # Add price parameters if needed
            if order_type == "LIMIT" and limit_price:
                order_params["price"] = limit_price
            elif order_type == "STOP_LOSS" and stop_price:
                order_params["trigger_price"] = stop_price
                order_params["order_type"] = "SL-M"  # Stop loss market
            
            order_id = self.kite.place_order(**order_params)
            
            logger.info(
                f"[{self.broker_name}] Order placed | "
                f"ID: {order_id}, {side} {quantity} {symbol}"
            )
            
            return OrderResponse(
                order_id=str(order_id),
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                status=OrderStatus.SUBMITTED.value,
                message="Order submitted to exchange",
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
    
    def _map_order_type(self, order_type: str) -> str:
        """Maps our order type to Kite order type."""
        mapping = {
            "MARKET": "MARKET",
            "LIMIT": "LIMIT",
            "STOP_LOSS": "SL",
            "STOP_LOSS_LIMIT": "SL",
        }
        return mapping.get(order_type, "MARKET")
    
    def _get_exchange(self, symbol: str) -> str:
        """Determines exchange (NSE/BSE) from symbol."""
        # NSE symbols typically end with .NS or no suffix
        # BSE symbols end with .BO
        if symbol.endswith(".BO"):
            return "BSE"
        return "NSE"
    
    # ── Order Status ───────────────────────────────────────────────────────
    
    def get_order_status(self, order_id: str) -> OrderResponse:
        """Gets order status from Zerodha."""
        if not self.is_connected or not self.kite:
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
            # Get order history
            orders = self.kite.orders()
            
            # Find our order
            for order in orders:
                if str(order["order_id"]) == order_id:
                    return self._parse_order_response(order)
            
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
    
    def _parse_order_response(self, order: dict) -> OrderResponse:
        """Parses Kite order dict to OrderResponse."""
        status_map = {
            "COMPLETE": OrderStatus.FILLED.value,
            "REJECTED": OrderStatus.REJECTED.value,
            "CANCELLED": OrderStatus.CANCELLED.value,
            "OPEN": OrderStatus.SUBMITTED.value,
            "TRIGGER PENDING": OrderStatus.PENDING.value,
        }
        
        return OrderResponse(
            order_id=str(order["order_id"]),
            symbol=order["tradingsymbol"],
            side=order["transaction_type"],
            quantity=order["quantity"],
            order_type=order["order_type"],
            status=status_map.get(order["status"], OrderStatus.PENDING.value),
            filled_quantity=order.get("filled_quantity", 0),
            filled_price=order.get("average_price", 0.0),
            message=order.get("status_message", ""),
            timestamp=order.get("order_timestamp", datetime.now(timezone.utc)),
        )
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancels an order."""
        if not self.is_connected or not self.kite:
            return False
        
        try:
            self.kite.cancel_order(
                variety="regular",
                order_id=order_id,
            )
            logger.info(f"[{self.broker_name}] Order cancelled: {order_id}")
            return True
        
        except Exception as e:
            logger.error(f"[{self.broker_name}] Cancel order failed: {e}")
            return False
    
    # ── Positions ──────────────────────────────────────────────────────────
    
    def get_positions(self) -> List[Position]:
        """Gets all positions from Zerodha."""
        if not self.is_connected or not self.kite:
            return []
        
        try:
            positions_data = self.kite.positions()
            
            positions = []
            for pos in positions_data.get("net", []):
                if pos["quantity"] != 0:  # Only open positions
                    positions.append(Position(
                        symbol=pos["tradingsymbol"],
                        quantity=pos["quantity"],
                        avg_entry_price=pos["average_price"],
                        current_price=pos["last_price"],
                        unrealized_pnl=pos["pnl"],
                        realized_pnl=pos.get("realised", 0.0),
                    ))
            
            return positions
        
        except Exception as e:
            logger.error(f"[{self.broker_name}] Get positions failed: {e}")
            return []
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Gets a specific position."""
        positions = self.get_positions()
        for pos in positions:
            if pos.symbol == symbol:
                return pos
        return None
    
    # ── Account Info ───────────────────────────────────────────────────────
    
    def get_account_info(self) -> AccountInfo:
        """Gets account information from Zerodha."""
        if not self.is_connected or not self.kite:
            return AccountInfo(
                buying_power=0.0,
                portfolio_value=0.0,
                cash=0.0,
                positions_value=0.0,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
            )
        
        try:
            # Get margins
            margins = self.kite.margins()
            equity_margin = margins.get("equity", {})
            
            # Get positions for P&L
            positions = self.get_positions()
            positions_value = sum(p.current_price * p.quantity for p in positions)
            unrealized_pnl = sum(p.unrealized_pnl for p in positions)
            
            return AccountInfo(
                buying_power=equity_margin.get("available", {}).get("live_balance", 0.0),
                portfolio_value=equity_margin.get("net", 0.0) + positions_value,
                cash=equity_margin.get("available", {}).get("cash", 0.0),
                positions_value=positions_value,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=0.0,  # Not directly available in Kite API
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
