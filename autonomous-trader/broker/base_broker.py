"""
broker/base_broker.py
======================
Abstract base class for all broker integrations.

All brokers must implement:
  - place_order(symbol, action, quantity, order_type, price)
  - get_order_status(order_id)
  - cancel_order(order_id)
  - get_positions()
  - get_account_info()

Returns standardized data structures for consistency.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ═══════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════

class OrderType(Enum):
    """Order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_LIMIT = "STOP_LOSS_LIMIT"


class OrderStatus(Enum):
    """Order status."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    PARTIAL_FILL = "PARTIAL_FILL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderSide(Enum):
    """Order side."""
    BUY = "BUY"
    SELL = "SELL"


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class OrderResponse:
    """Standardized order response."""
    order_id: str
    symbol: str
    side: str
    quantity: int
    order_type: str
    status: str
    filled_quantity: int = 0
    filled_price: float = 0.0
    message: str = ""
    timestamp: datetime = None


@dataclass
class Position:
    """Standardized position data."""
    symbol: str
    quantity: int
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float = 0.0


@dataclass
class AccountInfo:
    """Standardized account information."""
    buying_power: float
    portfolio_value: float
    cash: float
    positions_value: float
    unrealized_pnl: float
    realized_pnl: float


# ═══════════════════════════════════════════════════════════════
# BASE BROKER
# ═══════════════════════════════════════════════════════════════

class BaseBroker(ABC):
    """
    Abstract base class for broker integrations.
    
    All brokers (paper, zerodha, alpaca) inherit from this
    and implement the abstract methods.
    """
    
    def __init__(self, broker_name: str):
        """
        Initializes the broker.
        
        Args:
            broker_name: Name of the broker (for logging)
        """
        self.broker_name = broker_name
        self.is_connected = False
    
    # ── Abstract Methods ───────────────────────────────────────────────────
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Connects to the broker API.
        
        Returns:
            True if connection successful
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """Disconnects from the broker API."""
        pass
    
    @abstractmethod
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
        Places an order.
        
        Args:
            symbol: Stock symbol
            side: "BUY" or "SELL"
            quantity: Number of shares
            order_type: "MARKET" | "LIMIT" | "STOP_LOSS"
            limit_price: Limit price (for LIMIT orders)
            stop_price: Stop price (for STOP_LOSS orders)
        
        Returns:
            OrderResponse with order details
        """
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderResponse:
        """
        Gets the status of an order.
        
        Args:
            order_id: Order ID from place_order
        
        Returns:
            OrderResponse with current status
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancels an order.
        
        Args:
            order_id: Order ID to cancel
        
        Returns:
            True if cancellation successful
        """
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Position]:
        """
        Gets all open positions.
        
        Returns:
            List of Position objects
        """
        pass
    
    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        Gets a specific position.
        
        Args:
            symbol: Stock symbol
        
        Returns:
            Position object or None if no position
        """
        pass
    
    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """
        Gets account information.
        
        Returns:
            AccountInfo with buying power, portfolio value, etc.
        """
        pass
    
    # ── Utility Methods ────────────────────────────────────────────────────
    
    def is_market_order(self, order_type: str) -> bool:
        """Returns True if order type is MARKET."""
        return order_type.upper() == "MARKET"
    
    def validate_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str,
    ) -> tuple[bool, str]:
        """
        Validates order parameters.
        
        Returns:
            (is_valid, error_message)
        """
        if not symbol:
            return False, "Symbol is required"
        
        if side not in ["BUY", "SELL"]:
            return False, f"Invalid side: {side}"
        
        if quantity <= 0:
            return False, f"Invalid quantity: {quantity}"
        
        if order_type not in ["MARKET", "LIMIT", "STOP_LOSS", "STOP_LOSS_LIMIT"]:
            return False, f"Invalid order type: {order_type}"
        
        return True, ""
