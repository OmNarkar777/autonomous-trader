"""
scripts/train_models.py
========================
Train ML models for all symbols in watchlist.
"""

import argparse
from datetime import datetime
from ml.training.trainer import ModelTrainer
from config.constants import INDIA_WATCHLIST, US_WATCHLIST
from config.settings import settings
from config.logging_config import get_logger

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Train ML models for watchlist symbols"
    )
    parser.add_argument(
        "--market",
        choices=["india", "us", "both"],
        default=settings.TARGET_MARKET,
        help="Which market to train models for"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Specific symbols to train (default: all in watchlist)"
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=100,
        help="Number of LSTM training epochs (default: 100)"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip symbols that already have models"
    )
    
    args = parser.parse_args()
    
    # Determine symbols to train
    if args.symbols:
        symbols = args.symbols
    elif args.market == "india":
        symbols = INDIA_WATCHLIST
    elif args.market == "us":
        symbols = US_WATCHLIST
    else:  # both
        symbols = INDIA_WATCHLIST + US_WATCHLIST
    
    logger.info("=" * 60)
    logger.info("MODEL TRAINING STARTED")
    logger.info("=" * 60)
    logger.info(f"Market: {args.market}")
    logger.info(f"Symbols: {len(symbols)}")
    logger.info(f"LSTM epochs: {args.epochs}")
    logger.info(f"Skip existing: {args.skip_existing}")
    logger.info("")
    
    # Initialize trainer
    trainer = ModelTrainer()
    
    # Check existing models
    if args.skip_existing:
        symbols_to_train = [
            s for s in symbols if not trainer.model_exists(s)
        ]
        logger.info(f"Skipping {len(symbols) - len(symbols_to_train)} existing models")
        symbols = symbols_to_train
    
    if not symbols:
        logger.info("No symbols to train!")
        return
    
    # Train all symbols
    start_time = datetime.now()
    
    result = trainer.train_watchlist(
        symbols=symbols,
        lstm_epochs=args.epochs
    )
    
    duration = (datetime.now() - start_time).total_seconds()
    
    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("TRAINING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total symbols: {result['total_symbols']}")
    logger.info(f"Successful: {result['successful']}")
    logger.info(f"Failed: {result['failed']}")
    logger.info(f"Duration: {duration:.1f}s")
    logger.info("")
    
    if result['failed'] > 0:
        logger.warning("Failed symbols:")
        for item in result['results']:
            if not item.get('success'):
                logger.warning(f"  - {item['symbol']}: {item.get('error', 'Unknown error')}")
    
    # Print success examples
    if result['successful'] > 0:
        logger.info("Sample successful trainings:")
        success_count = 0
        for item in result['results']:
            if item.get('success') and success_count < 3:
                training_result = item['training_results']
                logger.info(f"  - {item['symbol']}: "
                          f"XGB accuracy={training_result['xgboost']['test_accuracy']:.3f}, "
                          f"duration={item['duration_seconds']:.1f}s")
                success_count += 1
    
    logger.info("")
    logger.info("Models saved to: models/")


if __name__ == "__main__":
    main()
