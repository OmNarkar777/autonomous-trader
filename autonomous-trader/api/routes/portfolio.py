"""
api/routes/portfolio.py
========================
Portfolio endpoints for account and position management.

Endpoints:
  GET  /api/portfolio/summary       - Portfolio overview
  GET  /api/portfolio/positions     - All open positions
  GET  /api/portfolio/positions/{symbol} - Specific position
  GET  /api/portfolio/performance   - Performance metrics
  GET  /api/portfolio/allocation    - Asset allocation
"""

from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from data.storage.database import DatabaseManager
from broker.paper_broker import PaperBroker
from config.settings import settings
from config.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()

# Initialize dependencies
db = DatabaseManager()
broker = PaperBroker()  # TODO: Support multiple brokers


# ═══════════════════════════════════════════════════════════════
# RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════

class PositionResponse(BaseModel):
    symbol: str
    quantity: int
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    position_value: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class PortfolioSummary(BaseModel):
    total_value: float
    cash: float
    positions_value: float
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    total_pnl_pct: float
    buying_power: float
    position_count: int


class PerformanceMetrics(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None


class AllocationItem(BaseModel):
    category: str
    value: float
    percentage: float


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.get("/summary", response_model=PortfolioSummary)

@router.get('/')
async def get_portfolio_root():
    """Root endpoint"""
    return await get_portfolio_summary()

async def get_portfolio_summary():
    """
    Get portfolio summary with total value, P&L, and buying power.
    """
    try:
        # Get account info
        account_info = broker.get_account_info()
        
        # Get positions
        positions = broker.get_positions()
        position_count = len(positions)
        
        # Calculate total P&L
        total_pnl = account_info.realized_pnl + account_info.unrealized_pnl
        
        # Calculate P&L percentage
        initial_capital = 100000
        total_pnl_pct = (total_pnl / initial_capital * 100) if initial_capital > 0 else 0
        
        return PortfolioSummary(
            total_value=account_info.portfolio_value,
            cash=account_info.cash,
            positions_value=account_info.positions_value,
            unrealized_pnl=account_info.unrealized_pnl,
            realized_pnl=account_info.realized_pnl,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            buying_power=account_info.buying_power,
            position_count=position_count,
        )
    
    except Exception as e:
        logger.error(f"Failed to get portfolio summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions", response_model=List[PositionResponse])
async def get_all_positions():
    """
    Get all open positions.
    """
    try:
        positions = broker.get_positions()
        
        # Convert to response models
        position_responses = []
        for pos in positions:
            unrealized_pnl_pct = (
                (pos.current_price - pos.avg_entry_price) / pos.avg_entry_price * 100
                if pos.avg_entry_price > 0 else 0
            )
            
            position_value = pos.current_price * pos.quantity
            
            # Get stop loss and take profit from database
            db_position = db.get_position(pos.symbol)
            stop_loss = db_position.stop_loss if db_position else None
            take_profit = db_position.take_profit if db_position else None
            
            position_responses.append(PositionResponse(
                symbol=pos.symbol,
                quantity=pos.quantity,
                avg_entry_price=pos.avg_entry_price,
                current_price=pos.current_price,
                unrealized_pnl=pos.unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                position_value=position_value,
                stop_loss=stop_loss,
                take_profit=take_profit,
            ))
        
        return position_responses
    
    except Exception as e:
        logger.error(f"Failed to get positions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions/{symbol}", response_model=PositionResponse)
async def get_position(symbol: str):
    """
    Get a specific position by symbol.
    """
    try:
        pos = broker.get_position(symbol)
        
        if not pos:
            raise HTTPException(status_code=404, detail=f"No position found for {symbol}")
        
        unrealized_pnl_pct = (
            (pos.current_price - pos.avg_entry_price) / pos.avg_entry_price * 100
            if pos.avg_entry_price > 0 else 0
        )
        
        position_value = pos.current_price * pos.quantity
        
        # Get stop loss and take profit from database
        db_position = db.get_position(symbol)
        stop_loss = db_position.stop_loss if db_position else None
        take_profit = db_position.take_profit if db_position else None
        
        return PositionResponse(
            symbol=pos.symbol,
            quantity=pos.quantity,
            avg_entry_price=pos.avg_entry_price,
            current_price=pos.current_price,
            unrealized_pnl=pos.unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            position_value=position_value,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get position for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance", response_model=PerformanceMetrics)
async def get_performance_metrics():
    """
    Get performance metrics (win rate, P&L, etc.).
    """
    try:
        # Get all closed trades
        trades = db.get_all_trades()
        
        # Filter closed trades
        closed_trades = [t for t in trades if t.exit_price is not None]
        
        if not closed_trades:
            return PerformanceMetrics(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                largest_win=0.0,
                largest_loss=0.0,
            )
        
        # Calculate metrics
        winning_trades = [t for t in closed_trades if t.pnl and t.pnl > 0]
        losing_trades = [t for t in closed_trades if t.pnl and t.pnl <= 0]
        
        total_trades = len(closed_trades)
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        
        total_pnl = sum(t.pnl for t in closed_trades if t.pnl)
        
        wins = [t.pnl for t in winning_trades if t.pnl]
        losses = [t.pnl for t in losing_trades if t.pnl]
        
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        largest_win = max(wins) if wins else 0
        largest_loss = min(losses) if losses else 0
        
        return PerformanceMetrics(
            total_trades=total_trades,
            winning_trades=win_count,
            losing_trades=loss_count,
            win_rate=win_rate,
            total_pnl=total_pnl,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            sharpe_ratio=None,  # TODO: Calculate from equity curve
            max_drawdown=None,  # TODO: Calculate from equity curve
        )
    
    except Exception as e:
        logger.error(f"Failed to get performance metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/allocation", response_model=List[AllocationItem])
async def get_allocation():
    """
    Get portfolio allocation by asset/sector.
    """
    try:
        account_info = broker.get_account_info()
        total_value = account_info.portfolio_value
        
        if total_value == 0:
            return []
        
        allocation = []
        
        # Cash allocation
        cash_pct = (account_info.cash / total_value * 100) if total_value > 0 else 0
        allocation.append(AllocationItem(
            category="Cash",
            value=account_info.cash,
            percentage=cash_pct,
        ))
        
        # Position allocation (grouped by symbol for now)
        # TODO: Group by sector using MacroCollector
        positions = broker.get_positions()
        for pos in positions:
            position_value = pos.current_price * pos.quantity
            position_pct = (position_value / total_value * 100) if total_value > 0 else 0
            
            allocation.append(AllocationItem(
                category=pos.symbol,
                value=position_value,
                percentage=position_pct,
            ))
        
        return allocation
    
    except Exception as e:
        logger.error(f"Failed to get allocation: {e}")
        raise HTTPException(status_code=500, detail=str(e))
