"""
api/websocket/live_feed.py
============================
WebSocket endpoint for real-time trading data feeds.

Provides:
  - Live position updates
  - Real-time trade notifications
  - Portfolio value streaming
  - System event notifications
  - Market regime updates

Connect via WebSocket:
    ws://localhost:8000/ws/live

Usage in React:
    const ws = new WebSocket('ws://localhost:8000/ws/live');
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log(data);
    };
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
import asyncio
import json
from datetime import datetime

from data.storage.database import DatabaseManager
from broker.paper_broker import PaperBroker
from config.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()

# Initialize dependencies
db = DatabaseManager()
broker = PaperBroker()
broker.connect()


# ═══════════════════════════════════════════════════════════════
# CONNECTION MANAGER
# ═══════════════════════════════════════════════════════════════

class ConnectionManager:
    """
    Manages WebSocket connections.
    """
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        """Accept and store a new connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """Remove a connection."""
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket):
        """Send message to a specific connection."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send message to websocket: {e}")
    
    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connections."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Failed to broadcast to connection: {e}")
                disconnected.append(connection)
        
        # Remove disconnected clients
        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)


manager = ConnectionManager()


# ═══════════════════════════════════════════════════════════════
# DATA PROVIDERS
# ═══════════════════════════════════════════════════════════════

async def get_portfolio_snapshot() -> Dict[str, Any]:
    """Get current portfolio snapshot."""
    try:
        account_info = broker.get_account_info()
        positions = broker.get_positions()
        
        return {
            "type": "portfolio_snapshot",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "total_value": account_info.portfolio_value,
                "cash": account_info.cash,
                "positions_value": account_info.positions_value,
                "unrealized_pnl": account_info.unrealized_pnl,
                "realized_pnl": account_info.realized_pnl,
                "position_count": len(positions),
            },
        }
    except Exception as e:
        logger.error(f"Failed to get portfolio snapshot: {e}")
        return {
            "type": "error",
            "message": str(e),
        }


async def get_positions_snapshot() -> Dict[str, Any]:
    """Get current positions snapshot."""
    try:
        positions = broker.get_positions()
        
        positions_data = []
        for pos in positions:
            positions_data.append({
                "symbol": pos.symbol,
                "quantity": pos.quantity,
                "avg_entry_price": pos.avg_entry_price,
                "current_price": pos.current_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "unrealized_pnl_pct": (
                    (pos.current_price - pos.avg_entry_price) / pos.avg_entry_price * 100
                    if pos.avg_entry_price > 0 else 0
                ),
            })
        
        return {
            "type": "positions_snapshot",
            "timestamp": datetime.utcnow().isoformat(),
            "data": positions_data,
        }
    except Exception as e:
        logger.error(f"Failed to get positions snapshot: {e}")
        return {
            "type": "error",
            "message": str(e),
        }


async def get_recent_trades_snapshot(limit: int = 5) -> Dict[str, Any]:
    """Get recent trades snapshot."""
    try:
        trades = db.get_all_trades()
        
        # Sort by entry time (most recent first)
        trades.sort(key=lambda t: t.entry_time or datetime.min, reverse=True)
        recent_trades = trades[:limit]
        
        trades_data = []
        for trade in recent_trades:
            trades_data.append({
                "trade_id": trade.trade_id,
                "symbol": trade.symbol,
                "action": trade.action,
                "quantity": trade.quantity,
                "entry_price": trade.entry_price,
                "status": trade.status,
                "pnl": trade.pnl,
                "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
            })
        
        return {
            "type": "recent_trades",
            "timestamp": datetime.utcnow().isoformat(),
            "data": trades_data,
        }
    except Exception as e:
        logger.error(f"Failed to get recent trades: {e}")
        return {
            "type": "error",
            "message": str(e),
        }


async def get_system_status() -> Dict[str, Any]:
    """Get system status."""
    try:
        # Get recent events
        events = db.get_recent_events(limit=5)
        
        events_data = []
        for event in events:
            events_data.append({
                "event_type": event.event_type,
                "message": event.message,
                "severity": event.severity,
                "timestamp": event.timestamp.isoformat(),
            })
        
        return {
            "type": "system_status",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "recent_events": events_data,
            },
        }
    except Exception as e:
        logger.error(f"Failed to get system status: {e}")
        return {
            "type": "error",
            "message": str(e),
        }


# ═══════════════════════════════════════════════════════════════
# WEBSOCKET ENDPOINT
# ═══════════════════════════════════════════════════════════════

@router.websocket("/live")
async def websocket_live_feed(websocket: WebSocket):
    """
    WebSocket endpoint for real-time trading data.
    
    Sends periodic updates:
      - Portfolio snapshot (every 5s)
      - Positions snapshot (every 10s)
      - Recent trades (every 10s)
      - System status (every 30s)
    """
    await manager.connect(websocket)
    
    try:
        # Send initial data
        await manager.send_personal_message(
            await get_portfolio_snapshot(),
            websocket
        )
        await manager.send_personal_message(
            await get_positions_snapshot(),
            websocket
        )
        await manager.send_personal_message(
            await get_recent_trades_snapshot(),
            websocket
        )
        
        # Counters for different update frequencies
        counter = 0
        
        while True:
            try:
                # Check for client messages (ping/pong)
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=1.0
                    )
                    
                    # Handle client messages
                    try:
                        message = json.loads(data)
                        if message.get("type") == "ping":
                            await manager.send_personal_message(
                                {"type": "pong", "timestamp": datetime.utcnow().isoformat()},
                                websocket
                            )
                    except json.JSONDecodeError:
                        pass
                
                except asyncio.TimeoutError:
                    # No message received, continue with periodic updates
                    pass
                
                # Send periodic updates
                counter += 1
                
                # Portfolio snapshot every 5 seconds
                if counter % 5 == 0:
                    await manager.send_personal_message(
                        await get_portfolio_snapshot(),
                        websocket
                    )
                
                # Positions snapshot every 10 seconds
                if counter % 10 == 0:
                    await manager.send_personal_message(
                        await get_positions_snapshot(),
                        websocket
                    )
                    await manager.send_personal_message(
                        await get_recent_trades_snapshot(),
                        websocket
                    )
                
                # System status every 30 seconds
                if counter % 30 == 0:
                    await manager.send_personal_message(
                        await get_system_status(),
                        websocket
                    )
                
                # Reset counter to prevent overflow
                if counter > 1000:
                    counter = 0
                
                # Sleep to avoid busy loop
                await asyncio.sleep(1)
            
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error in websocket loop: {e}")
                break
    
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        manager.disconnect(websocket)


# ═══════════════════════════════════════════════════════════════
# BROADCAST FUNCTIONS (for system to push updates)
# ═══════════════════════════════════════════════════════════════

async def broadcast_trade_execution(trade_data: Dict[str, Any]):
    """
    Broadcast trade execution to all connected clients.
    
    Call this from ExecutionAgent after executing a trade.
    """
    message = {
        "type": "trade_executed",
        "timestamp": datetime.utcnow().isoformat(),
        "data": trade_data,
    }
    await manager.broadcast(message)


async def broadcast_position_update(position_data: Dict[str, Any]):
    """
    Broadcast position update to all connected clients.
    
    Call this when positions are updated.
    """
    message = {
        "type": "position_update",
        "timestamp": datetime.utcnow().isoformat(),
        "data": position_data,
    }
    await manager.broadcast(message)


async def broadcast_system_event(event_data: Dict[str, Any]):
    """
    Broadcast system event to all connected clients.
    
    Call this for important system events (errors, circuit breaker, etc.).
    """
    message = {
        "type": "system_event",
        "timestamp": datetime.utcnow().isoformat(),
        "data": event_data,
    }
    await manager.broadcast(message)
