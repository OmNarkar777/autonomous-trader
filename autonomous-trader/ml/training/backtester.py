"""
ml/training/backtester.py
==========================
Backtesting framework for evaluating ML model performance.

Simulates trading based on model predictions on historical data
to validate profitability before deploying to live/paper trading.

Metrics tracked:
  - Win rate (% of profitable trades)
  - Total P&L
  - Sharpe ratio
  - Maximum drawdown
  - Average gain per winning trade
  - Average loss per losing trade

Usage:
    from ml.training.backtester import Backtester
    bt = Backtester()
    results = bt.backtest_symbol("RELIANCE.NS", days_back=365)
    print(f"Win rate: {results.win_rate:.1%}, Total P&L: {results.total_pnl:.2f}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np

from ml.models.ensemble import EnsemblePredictor
from ml.training.trainer import ModelTrainer
from data.collectors.price_collector import PriceCollector
from config.constants import (
    STOP_LOSS_ATR_MULTIPLIER,
    TAKE_PROFIT_ATR_MULTIPLIER,
    POSITION_RISK_PCT,
    ENSEMBLE_BUY_THRESHOLD,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class BacktestTrade:
    """Single trade in the backtest."""
    symbol: str
    entry_date: datetime
    entry_price: float
    quantity: int
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "stop_loss" | "take_profit" | "signal" | "end"
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    hold_days: Optional[int] = None


@dataclass
class BacktestResults:
    """Complete backtest results."""
    symbol: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    
    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    
    # P&L metrics
    total_pnl: float
    total_pnl_pct: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    
    # Risk metrics
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    
    # Trade details
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series())


# ═══════════════════════════════════════════════════════════════
# BACKTESTER
# ═══════════════════════════════════════════════════════════════

class Backtester:
    """
    Backtesting engine for ML models.
    
    Simulates trades based on model predictions and calculates
    performance metrics.
    """
    
    def __init__(self, initial_capital: float = 100000.0):
        """
        Initialises the backtester.
        
        Args:
            initial_capital: Starting capital for backtest
        """
        self.initial_capital = initial_capital
        self.price_collector = PriceCollector()
        self.trainer = ModelTrainer()
    
    # ── Main Backtesting Method ────────────────────────────────────────────
    
    def backtest_symbol(
        self,
        symbol: str,
        days_back: int = 365,
        use_existing_model: bool = True,
        position_size_pct: float = POSITION_RISK_PCT,
    ) -> BacktestResults:
        """
        Runs a backtest for a single symbol.
        
        Args:
            symbol: Stock symbol to backtest
            days_back: How many days of history to backtest
            use_existing_model: If True, loads existing trained model.
                               If False, trains a new model.
            position_size_pct: Position size as % of capital
        
        Returns:
            BacktestResults with complete metrics
        """
        logger.info(
            f"[{symbol}] Starting backtest | "
            f"Days: {days_back} | Initial capital: {self.initial_capital:,.0f}"
        )
        
        # ── Load data ──────────────────────────────────────────────────────
        period_map = {
            365: "2y",
            180: "1y",
            90: "6mo",
        }
        period = period_map.get(days_back, "2y")
        
        df = self.price_collector.get_historical_data(
            symbol,
            period=period,
            interval="1d",
        )
        
        # Take only last days_back days
        df = df.tail(days_back)
        
        logger.info(f"[{symbol}] Loaded {len(df)} days for backtesting")
        
        # ── Load or train model ────────────────────────────────────────────
        if use_existing_model and self.trainer.model_exists(symbol):
            logger.info(f"[{symbol}] Loading existing model")
            ensemble = self.trainer.load_model(symbol)
        else:
            logger.info(f"[{symbol}] Training new model for backtest")
            # Use first 70% of data for training
            train_size = int(len(df) * 0.7)
            train_df = df.head(train_size)
            
            ensemble = EnsemblePredictor(symbol=symbol)
            ensemble.train(train_df, lstm_epochs=50, lstm_verbose=0)
        
        # ── Run backtest simulation ────────────────────────────────────────
        trades = []
        capital = self.initial_capital
        current_position: Optional[BacktestTrade] = None
        equity_curve = []
        
        # Use last 30% of data for backtesting
        test_start_idx = int(len(df) * 0.7)
        test_df = df.iloc[test_start_idx:]
        
        logger.info(f"[{symbol}] Running simulation on {len(test_df)} days")
        
        for i in range(len(test_df)):
            current_date = test_df.index[i]
            current_price = test_df["Close"].iloc[i]
            
            # Need at least 200 days of history for prediction
            history_end_idx = test_start_idx + i + 1
            if history_end_idx < 200:
                equity_curve.append(capital)
                continue
            
            history_df = df.iloc[:history_end_idx]
            
            # ── Check if we have an open position ─────────────────────────
            if current_position is not None:
                # Check stop loss
                if current_price <= current_position.stop_loss:
                    current_position = self._close_position(
                        current_position,
                        exit_date=current_date,
                        exit_price=current_price,
                        exit_reason="stop_loss",
                    )
                    capital += current_position.pnl
                    trades.append(current_position)
                    current_position = None
                
                # Check take profit
                elif current_price >= current_position.take_profit:
                    current_position = self._close_position(
                        current_position,
                        exit_date=current_date,
                        exit_price=current_price,
                        exit_reason="take_profit",
                    )
                    capital += current_position.pnl
                    trades.append(current_position)
                    current_position = None
                
                # Update equity curve
                if current_position:
                    unrealized_pnl = (
                        (current_price - current_position.entry_price)
                        * current_position.quantity
                    )
                    equity_curve.append(capital + unrealized_pnl)
                else:
                    equity_curve.append(capital)
                continue
            
            # ── Make prediction ────────────────────────────────────────────
            try:
                prediction = ensemble.predict(history_df)
            except Exception as e:
                logger.warning(f"[{symbol}] Prediction failed at {current_date}: {e}")
                equity_curve.append(capital)
                continue
            
            # ── Open new position if BUY signal ────────────────────────────
            if prediction.decision == "BUY" and prediction.score >= ENSEMBLE_BUY_THRESHOLD:
                # Calculate position size
                position_value = capital * position_size_pct
                quantity = int(position_value / current_price)
                
                if quantity > 0:
                    # Calculate stop loss and take profit using ATR
                    atr = history_df["ATR_14"].iloc[-1] if "ATR_14" in history_df.columns else current_price * 0.02
                    stop_loss = current_price - (STOP_LOSS_ATR_MULTIPLIER * atr)
                    take_profit = current_price + (TAKE_PROFIT_ATR_MULTIPLIER * atr)
                    
                    current_position = BacktestTrade(
                        symbol=symbol,
                        entry_date=current_date,
                        entry_price=current_price,
                        quantity=quantity,
                    )
                    current_position.stop_loss = stop_loss
                    current_position.take_profit = take_profit
                    
                    logger.debug(
                        f"[{symbol}] Opened position: {quantity} @ {current_price:.2f} | "
                        f"SL: {stop_loss:.2f}, TP: {take_profit:.2f}"
                    )
            
            equity_curve.append(capital)
        
        # ── Close any remaining position at end ────────────────────────────
        if current_position is not None:
            final_price = test_df["Close"].iloc[-1]
            final_date = test_df.index[-1]
            current_position = self._close_position(
                current_position,
                exit_date=final_date,
                exit_price=final_price,
                exit_reason="end",
            )
            capital += current_position.pnl
            trades.append(current_position)
        
        # ── Calculate metrics ──────────────────────────────────────────────
        results = self._calculate_metrics(
            symbol=symbol,
            trades=trades,
            equity_curve=pd.Series(equity_curve, index=test_df.index),
            start_date=test_df.index[0],
            end_date=test_df.index[-1],
            final_capital=capital,
        )
        
        logger.info(
            f"[{symbol}] Backtest complete | "
            f"Trades: {results.total_trades} | Win rate: {results.win_rate:.1%} | "
            f"Total P&L: {results.total_pnl:,.2f} ({results.total_pnl_pct:+.1%}) | "
            f"Sharpe: {results.sharpe_ratio:.2f}"
        )
        
        return results
    
    # ── Helper Methods ─────────────────────────────────────────────────────
    
    def _close_position(
        self,
        position: BacktestTrade,
        exit_date: datetime,
        exit_price: float,
        exit_reason: str,
    ) -> BacktestTrade:
        """Closes a position and calculates P&L."""
        position.exit_date = exit_date
        position.exit_price = exit_price
        position.exit_reason = exit_reason
        
        position.pnl = (exit_price - position.entry_price) * position.quantity
        position.pnl_pct = (exit_price - position.entry_price) / position.entry_price * 100
        position.hold_days = (exit_date - position.entry_date).days
        
        return position
    
    def _calculate_metrics(
        self,
        symbol: str,
        trades: List[BacktestTrade],
        equity_curve: pd.Series,
        start_date: datetime,
        end_date: datetime,
        final_capital: float,
    ) -> BacktestResults:
        """Calculates all backtest metrics from trades."""
        
        # Basic counts
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.pnl > 0)
        losing_trades = sum(1 for t in trades if t.pnl < 0)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        
        # P&L metrics
        total_pnl = sum(t.pnl for t in trades)
        total_pnl_pct = (final_capital - self.initial_capital) / self.initial_capital * 100
        
        wins = [t.pnl for t in trades if t.pnl > 0]
        losses = [t.pnl for t in trades if t.pnl < 0]
        
        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = np.mean(losses) if losses else 0.0
        largest_win = max(wins) if wins else 0.0
        largest_loss = min(losses) if losses else 0.0
        
        # Risk metrics
        max_drawdown, max_drawdown_pct = self._calculate_drawdown(equity_curve)
        sharpe_ratio = self._calculate_sharpe(equity_curve)
        
        return BacktestResults(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            trades=trades,
            equity_curve=equity_curve,
        )
    
    def _calculate_drawdown(self, equity_curve: pd.Series) -> Tuple[float, float]:
        """Calculates maximum drawdown from equity curve."""
        if len(equity_curve) == 0:
            return 0.0, 0.0
        
        # Calculate running maximum
        running_max = equity_curve.expanding().max()
        
        # Drawdown at each point
        drawdown = equity_curve - running_max
        max_dd = drawdown.min()
        
        # Percentage drawdown
        max_dd_pct = (max_dd / running_max.max()) * 100 if running_max.max() > 0 else 0.0
        
        return float(max_dd), float(max_dd_pct)
    
    def _calculate_sharpe(self, equity_curve: pd.Series) -> float:
        """Calculates Sharpe ratio from equity curve."""
        if len(equity_curve) < 2:
            return 0.0
        
        # Daily returns
        returns = equity_curve.pct_change().dropna()
        
        if len(returns) == 0:
            return 0.0
        
        # Sharpe ratio (annualized, assuming 252 trading days)
        mean_return = returns.mean()
        std_return = returns.std()
        
        if std_return == 0:
            return 0.0
        
        sharpe = (mean_return / std_return) * np.sqrt(252)
        
        return float(sharpe)
    
    # ── Batch Backtesting ──────────────────────────────────────────────────
    
    def backtest_watchlist(
        self,
        symbols: Optional[List[str]] = None,
        days_back: int = 365,
    ) -> Dict[str, BacktestResults]:
        """
        Runs backtest for all symbols in watchlist.
        
        Args:
            symbols: List of symbols (default: active watchlist)
            days_back: Days of history to backtest
        
        Returns:
            Dict mapping symbol → BacktestResults
        """
        from config.settings import settings
        
        if symbols is None:
            symbols = settings.active_watchlist
        
        logger.info(f"Starting batch backtest for {len(symbols)} symbols")
        
        results = {}
        
        for i, symbol in enumerate(symbols, 1):
            logger.info(f"Backtesting [{i}/{len(symbols)}]: {symbol}")
            
            try:
                result = self.backtest_symbol(symbol, days_back=days_back)
                results[symbol] = result
            except Exception as e:
                logger.error(f"[{symbol}] Backtest failed: {e}", exc_info=True)
        
        # Summary statistics
        self._log_batch_summary(results)
        
        return results
    
    def _log_batch_summary(self, results: Dict[str, BacktestResults]) -> None:
        """Logs summary statistics from batch backtest."""
        if not results:
            return
        
        avg_win_rate = np.mean([r.win_rate for r in results.values()])
        avg_pnl_pct = np.mean([r.total_pnl_pct for r in results.values()])
        avg_sharpe = np.mean([r.sharpe_ratio for r in results.values()])
        
        profitable_count = sum(1 for r in results.values() if r.total_pnl > 0)
        
        logger.info(
            f"Batch backtest summary | "
            f"Symbols: {len(results)} | "
            f"Avg win rate: {avg_win_rate:.1%} | "
            f"Avg P&L: {avg_pnl_pct:+.1%} | "
            f"Avg Sharpe: {avg_sharpe:.2f} | "
            f"Profitable: {profitable_count}/{len(results)}"
        )
