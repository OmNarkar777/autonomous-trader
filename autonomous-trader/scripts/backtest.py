"""
scripts/backtest.py
===================
Run backtesting on historical data.
"""

import argparse
from datetime import datetime
from ml.training.backtester import Backtester
from config.constants import INDIA_WATCHLIST, US_WATCHLIST
from config.settings import settings
from config.logging_config import get_logger

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Backtest trading strategy on historical data"
    )
    parser.add_argument(
        "--market",
        choices=["india", "us", "both"],
        default=settings.TARGET_MARKET,
        help="Which market to backtest"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Specific symbols to backtest (default: all in watchlist)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Number of days to backtest (default: 365)"
    )
    parser.add_argument(
        "--position-size",
        type=float,
        default=2.0,
        help="Position size as %% of capital (default: 2.0)"
    )
    
    args = parser.parse_args()
    
    # Determine symbols
    if args.symbols:
        symbols = args.symbols
    elif args.market == "india":
        symbols = INDIA_WATCHLIST
    elif args.market == "us":
        symbols = US_WATCHLIST
    else:
        symbols = INDIA_WATCHLIST + US_WATCHLIST
    
    logger.info("=" * 60)
    logger.info("BACKTESTING STARTED")
    logger.info("=" * 60)
    logger.info(f"Market: {args.market}")
    logger.info(f"Symbols: {len(symbols)}")
    logger.info(f"Days back: {args.days}")
    logger.info(f"Position size: {args.position_size}%")
    logger.info("")
    
    # Initialize backtester
    backtester = Backtester()
    
    # Backtest all symbols
    start_time = datetime.now()
    
    results = backtester.backtest_watchlist(
        symbols=symbols,
        days_back=args.days
    )
    
    duration = (datetime.now() - start_time).total_seconds()
    
    # Aggregate statistics
    all_results = list(results.values())
    profitable = [r for r in all_results if r.total_pnl > 0]
    
    avg_win_rate = sum(r.win_rate for r in all_results) / len(all_results) if all_results else 0
    avg_pnl_pct = sum(r.total_pnl_pct for r in all_results) / len(all_results) if all_results else 0
    avg_sharpe = sum(r.sharpe_ratio for r in all_results if r.sharpe_ratio) / len(all_results) if all_results else 0
    
    total_trades = sum(r.total_trades for r in all_results)
    
    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("BACKTESTING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Symbols tested: {len(all_results)}")
    logger.info(f"Profitable symbols: {len(profitable)} ({len(profitable)/len(all_results)*100:.1f}%)")
    logger.info(f"Total trades: {total_trades}")
    logger.info(f"Average win rate: {avg_win_rate:.1f}%")
    logger.info(f"Average P&L: {avg_pnl_pct:+.2f}%")
    logger.info(f"Average Sharpe: {avg_sharpe:.2f}")
    logger.info(f"Duration: {duration:.1f}s")
    logger.info("")
    
    # Print top performers
    logger.info("Top 5 performers by P&L:")
    sorted_by_pnl = sorted(all_results, key=lambda r: r.total_pnl_pct, reverse=True)
    for i, result in enumerate(sorted_by_pnl[:5], 1):
        logger.info(f"  {i}. {result.symbol}: {result.total_pnl_pct:+.2f}% "
                  f"(Win rate: {result.win_rate:.1f}%, Sharpe: {result.sharpe_ratio:.2f})")
    
    logger.info("")
    logger.info("Bottom 5 performers by P&L:")
    for i, result in enumerate(sorted_by_pnl[-5:], 1):
        logger.info(f"  {i}. {result.symbol}: {result.total_pnl_pct:+.2f}% "
                  f"(Win rate: {result.win_rate:.1f}%, Sharpe: {result.sharpe_ratio:.2f})")


if __name__ == "__main__":
    main()
