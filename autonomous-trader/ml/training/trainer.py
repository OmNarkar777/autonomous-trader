"""
ml/training/trainer.py
=======================
Handles training pipeline for all models across the watchlist.

This orchestrates:
  1. Weekly model retraining (every Sunday)
  2. Batch training for all watchlist symbols
  3. Model versioning and persistence
  4. Training metrics tracking

Training schedule:
  - Sunday 02:00 AM: Full retraining of all models
  - Models saved to: models/{symbol}/ensemble/
  - Old models archived with timestamp

Usage:
    from ml.training.trainer import ModelTrainer
    trainer = ModelTrainer()
    
    # Train single symbol
    trainer.train_symbol("RELIANCE.NS")
    
    # Train entire watchlist
    trainer.train_watchlist()
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
import pandas as pd

from ml.models.ensemble import EnsemblePredictor
from data.collectors.price_collector import PriceCollector
from data.storage.database import DatabaseManager
from config.settings import settings
from config.constants import (
    ML_TRAINING_PERIOD,
    ML_MIN_TRAINING_DAYS,
    INDIA_WATCHLIST,
    US_WATCHLIST,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# MODEL TRAINER
# ═══════════════════════════════════════════════════════════════

class ModelTrainer:
    """
    Manages training pipeline for ML models.
    
    Handles data fetching, model training, persistence, and metrics tracking.
    """
    
    def __init__(
        self,
        models_dir: Optional[str] = None,
        db: Optional[DatabaseManager] = None,
    ):
        """
        Initialises the trainer.
        
        Args:
            models_dir: Directory to save trained models (default: ./models/)
            db: Database manager instance
        """
        self.models_dir = Path(models_dir or "./models")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        self.price_collector = PriceCollector()
        self.db = db or DatabaseManager()
    
    # ── Single Symbol Training ────────────────────────────────────────────
    
    def train_symbol(
        self,
        symbol: str,
        lstm_epochs: int = 100,
        save_model: bool = True,
        archive_old: bool = True,
    ) -> Dict[str, Any]:
        """
        Trains an ensemble model for a single symbol.
        
        Args:
            symbol: Stock symbol to train
            lstm_epochs: Max epochs for LSTM
            save_model: Whether to save the trained model
            archive_old: Whether to archive the previous model version
        
        Returns:
            Dict with training results and metrics
        """
        logger.info(f"[{symbol}] Starting model training")
        
        result = {
            "symbol": symbol,
            "success": False,
            "start_time": datetime.utcnow(),
        }
        
        try:
            # ── Fetch historical data ──────────────────────────────────────
            logger.info(f"[{symbol}] Fetching {ML_TRAINING_PERIOD} historical data")
            
            df = self.price_collector.get_historical_data(
                symbol,
                period=ML_TRAINING_PERIOD,
                interval="1d",
            )
            
            if len(df) < ML_MIN_TRAINING_DAYS:
                raise ValueError(
                    f"Insufficient data: {len(df)} days < {ML_MIN_TRAINING_DAYS} required"
                )
            
            logger.info(f"[{symbol}] Loaded {len(df)} days of historical data")
            
            # ── Archive old model if exists ────────────────────────────────
            if archive_old and save_model:
                self._archive_old_model(symbol)
            
            # ── Train ensemble ─────────────────────────────────────────────
            ensemble = EnsemblePredictor(symbol=symbol)
            
            training_results = ensemble.train(
                df,
                lstm_epochs=lstm_epochs,
                lstm_verbose=0,
                xgb_verbose=False,
            )
            
            result["training_results"] = training_results
            
            # ── Save model ─────────────────────────────────────────────────
            if save_model:
                model_path = self._get_model_path(symbol)
                ensemble.save(str(model_path))
                result["model_path"] = str(model_path)
                logger.info(f"[{symbol}] Model saved to {model_path}")
            
            # ── Quick evaluation ───────────────────────────────────────────
            try:
                # Use last 20% of data as test set
                test_size = int(len(df) * 0.2)
                test_df = df.tail(test_size)
                
                eval_metrics = ensemble.evaluate(test_df)
                result["evaluation"] = eval_metrics
            except Exception as e:
                logger.warning(f"[{symbol}] Evaluation failed: {e}")
                result["evaluation"] = {"error": str(e)}
            
            # ── Log training event ─────────────────────────────────────────
            self.db.log_event(
                event_type="MODEL_TRAINING",
                agent_name="ModelTrainer",
                symbol=symbol,
                message=f"Model training completed successfully",
                data={
                    "data_days": len(df),
                    "lstm_epochs": training_results.get("lstm", {}).get("epochs", 0),
                    "xgb_accuracy": training_results.get("xgboost", {}).get("test_accuracy", 0),
                },
                severity="INFO",
            )
            
            result["success"] = True
            result["end_time"] = datetime.utcnow()
            result["duration_seconds"] = (
                result["end_time"] - result["start_time"]
            ).total_seconds()
            
            logger.info(
                f"[{symbol}] Training complete in {result['duration_seconds']:.1f}s | "
                f"LSTM epochs: {training_results['lstm'].get('epochs', 0)} | "
                f"XGB acc: {training_results['xgboost'].get('test_accuracy', 0):.1%}"
            )
        
        except Exception as e:
            logger.error(f"[{symbol}] Training failed: {e}", exc_info=True)
            result["success"] = False
            result["error"] = str(e)
            result["end_time"] = datetime.utcnow()
            
            # Log failure
            self.db.log_event(
                event_type="MODEL_TRAINING_FAILED",
                agent_name="ModelTrainer",
                symbol=symbol,
                message=f"Model training failed: {e}",
                severity="ERROR",
            )
        
        return result
    
    # ── Batch Training ─────────────────────────────────────────────────────
    
    def train_watchlist(
        self,
        symbols: Optional[List[str]] = None,
        lstm_epochs: int = 100,
    ) -> Dict[str, Any]:
        """
        Trains models for all symbols in the watchlist.
        
        Args:
            symbols: List of symbols to train (default: active watchlist)
            lstm_epochs: Max epochs for LSTM
        
        Returns:
            Dict with overall training statistics
        """
        if symbols is None:
            # Get active watchlist based on target market
            if settings.TARGET_MARKET == "india":
                symbols = INDIA_WATCHLIST
            elif settings.TARGET_MARKET == "us":
                symbols = US_WATCHLIST
            else:
                symbols = INDIA_WATCHLIST + US_WATCHLIST
        
        total = len(symbols)
        logger.info(f"Starting batch training for {total} symbols")
        
        overall_start = datetime.utcnow()
        results = {
            "total_symbols": total,
            "successful": 0,
            "failed": 0,
            "results": [],
            "start_time": overall_start,
        }
        
        for i, symbol in enumerate(symbols, 1):
            logger.info(f"Training [{i}/{total}]: {symbol}")
            
            symbol_result = self.train_symbol(
                symbol,
                lstm_epochs=lstm_epochs,
                save_model=True,
                archive_old=True,
            )
            
            results["results"].append(symbol_result)
            
            if symbol_result["success"]:
                results["successful"] += 1
            else:
                results["failed"] += 1
        
        overall_end = datetime.utcnow()
        results["end_time"] = overall_end
        results["total_duration_seconds"] = (
            overall_end - overall_start
        ).total_seconds()
        
        # Summary
        success_rate = results["successful"] / total if total > 0 else 0
        logger.info(
            f"Batch training complete | "
            f"Success: {results['successful']}/{total} ({success_rate:.1%}) | "
            f"Duration: {results['total_duration_seconds']:.1f}s"
        )
        
        # Log summary event
        self.db.log_event(
            event_type="BATCH_TRAINING_COMPLETE",
            agent_name="ModelTrainer",
            message=f"Trained {results['successful']}/{total} models successfully",
            data={
                "successful": results["successful"],
                "failed": results["failed"],
                "duration_seconds": results["total_duration_seconds"],
            },
            severity="INFO",
        )
        
        return results
    
    # ── Model Management ───────────────────────────────────────────────────
    
    def _get_model_path(self, symbol: str) -> Path:
        """Returns the directory path for a symbol's model."""
        # Sanitize symbol for filesystem (replace . with _)
        safe_symbol = symbol.replace(".", "_")
        return self.models_dir / safe_symbol / "ensemble"
    
    def _archive_old_model(self, symbol: str) -> None:
        """Archives the existing model with a timestamp before overwriting."""
        model_path = self._get_model_path(symbol)
        
        if not model_path.exists():
            return
        
        # Create archive with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        archive_path = model_path.parent / f"ensemble_archived_{timestamp}"
        
        try:
            shutil.move(str(model_path), str(archive_path))
            logger.info(f"[{symbol}] Old model archived to {archive_path}")
        except Exception as e:
            logger.warning(f"[{symbol}] Failed to archive old model: {e}")
    
    def load_model(self, symbol: str) -> EnsemblePredictor:
        """
        Loads a trained ensemble model for a symbol.
        
        Args:
            symbol: Stock symbol
        
        Returns:
            Loaded EnsemblePredictor
        
        Raises:
            FileNotFoundError: If model doesn't exist
        """
        model_path = self._get_model_path(symbol)
        
        if not model_path.exists():
            raise FileNotFoundError(
                f"No trained model found for {symbol} at {model_path}"
            )
        
        ensemble = EnsemblePredictor(symbol=symbol)
        ensemble.load(str(model_path))
        
        logger.info(f"[{symbol}] Model loaded from {model_path}")
        return ensemble
    
    def model_exists(self, symbol: str) -> bool:
        """Checks if a trained model exists for a symbol."""
        model_path = self._get_model_path(symbol)
        lstm_exists = (model_path / "lstm" / "lstm_model.keras").exists()
        xgb_exists = (model_path / "xgboost" / "xgboost_model.json").exists()
        return lstm_exists and xgb_exists
    
    def get_model_age(self, symbol: str) -> Optional[timedelta]:
        """
        Returns how old the model is (time since last training).
        
        Returns:
            timedelta or None if model doesn't exist
        """
        model_path = self._get_model_path(symbol)
        model_file = model_path / "lstm" / "lstm_model.keras"
        
        if not model_file.exists():
            return None
        
        mod_time = datetime.fromtimestamp(model_file.stat().st_mtime)
        return datetime.now() - mod_time
    
    def needs_retraining(
        self,
        symbol: str,
        max_age_days: int = 7,
    ) -> bool:
        """
        Checks if a model needs retraining based on age.
        
        Args:
            symbol: Stock symbol
            max_age_days: Maximum days before retraining needed
        
        Returns:
            True if model doesn't exist or is older than max_age_days
        """
        if not self.model_exists(symbol):
            return True
        
        age = self.get_model_age(symbol)
        if age is None:
            return True
        
        return age.days >= max_age_days
    
    # ── Scheduled Training ─────────────────────────────────────────────────
    
    def retrain_stale_models(
        self,
        max_age_days: int = 7,
        symbols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Retrains models that are older than max_age_days.
        
        This is called by the scheduler on a weekly basis.
        
        Args:
            max_age_days: Maximum model age before retraining
            symbols: Symbols to check (default: active watchlist)
        
        Returns:
            Dict with retraining results
        """
        if symbols is None:
            if settings.TARGET_MARKET == "india":
                symbols = INDIA_WATCHLIST
            elif settings.TARGET_MARKET == "us":
                symbols = US_WATCHLIST
            else:
                symbols = INDIA_WATCHLIST + US_WATCHLIST
        
        # Find symbols needing retraining
        stale_symbols = [
            s for s in symbols
            if self.needs_retraining(s, max_age_days=max_age_days)
        ]
        
        if not stale_symbols:
            logger.info("All models are up to date — no retraining needed")
            return {
                "stale_symbols": 0,
                "retrained": 0,
                "message": "All models up to date",
            }
        
        logger.info(
            f"Found {len(stale_symbols)} stale models (older than {max_age_days} days): "
            f"{stale_symbols}"
        )
        
        # Retrain stale models
        results = self.train_watchlist(symbols=stale_symbols)
        results["stale_symbols"] = len(stale_symbols)
        
        return results
    
    # ── Statistics ─────────────────────────────────────────────────────────
    
    def get_training_statistics(self) -> Dict[str, Any]:
        """
        Returns statistics about trained models.
        
        Returns:
            Dict with model count, ages, etc.
        """
        watchlist = settings.active_watchlist
        
        stats = {
            "total_symbols": len(watchlist),
            "models_trained": 0,
            "models_missing": 0,
            "average_age_days": 0,
            "oldest_model_age_days": 0,
            "newest_model_age_days": None,
        }
        
        ages = []
        
        for symbol in watchlist:
            if self.model_exists(symbol):
                stats["models_trained"] += 1
                age = self.get_model_age(symbol)
                if age:
                    ages.append(age.days)
            else:
                stats["models_missing"] += 1
        
        if ages:
            stats["average_age_days"] = sum(ages) / len(ages)
            stats["oldest_model_age_days"] = max(ages)
            stats["newest_model_age_days"] = min(ages)
        
        return stats
