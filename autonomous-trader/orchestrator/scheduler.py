"""
orchestrator/scheduler.py
==========================
Scheduler for automated trading cycles.

Manages:
  1. Trading cycle schedule (e.g., every hour during market hours)
  2. Model retraining schedule (e.g., weekly on Sunday)
  3. Portfolio monitoring (continuous during market hours)
  4. Data cleanup (daily)

Uses APScheduler for cron-like scheduling.

Usage:
    from orchestrator.scheduler import TradingScheduler
    scheduler = TradingScheduler()
    scheduler.start()  # Runs in background
    
    # Or run one-time
    scheduler.run_trading_cycle()
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime, time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from orchestrator.graph import TradingGraph
from orchestrator.circuit_breaker import CircuitBreaker
from ml.training.trainer import ModelTrainer
from data.storage.database import DatabaseManager
from config.settings import settings
from config.constants import NSE_HOURS, NYSE_HOURS
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# TRADING SCHEDULER
# ═══════════════════════════════════════════════════════════════

class TradingScheduler:
    """
    Automated scheduler for trading system operations.
    
    Schedules:
      - Trading cycles (hourly during market hours)
      - Model retraining (weekly)
      - Data cleanup (daily)
      - Circuit breaker health checks
    """
    
    def __init__(
        self,
        broker_type: str = "paper",
        enable_auto_trading: bool = True,
    ):
        """
        Initializes the scheduler.
        
        Args:
            broker_type: "paper" | "zerodha" | "alpaca"
            enable_auto_trading: If False, only manual triggers work
        """
        self.broker_type = broker_type
        self.enable_auto_trading = enable_auto_trading
        
        self.trading_graph = TradingGraph(broker_type=broker_type)
        self.circuit_breaker = CircuitBreaker()
        self.model_trainer = ModelTrainer()
        self.db = DatabaseManager()
        
        self.scheduler = BackgroundScheduler()
        self._is_running = False
    
    # ── Trading Cycle ──────────────────────────────────────────────────────
    
    def run_trading_cycle(self) -> dict:
        """
        Runs a single trading cycle manually.
        
        Returns:
            Cycle summary
        """
        logger.info("Starting manual trading cycle")
        
        # Check circuit breaker
        if self.circuit_breaker.is_open():
            logger.error("Trading cycle aborted: Circuit breaker is OPEN")
            return {
                "status": "aborted",
                "reason": "Circuit breaker open",
            }
        
        try:
            # Run the trading graph
            summary = self.trading_graph.run()
            
            # Record success/failure in circuit breaker
            if summary.get("errors", 0) == 0:
                self.circuit_breaker.record_success()
            else:
                self.circuit_breaker.record_failure(
                    f"Cycle completed with {summary['errors']} errors"
                )
            
            return summary
        
        except Exception as e:
            logger.error(f"Trading cycle crashed: {e}", exc_info=True)
            self.circuit_breaker.record_failure(f"Cycle crashed: {e}")
            
            # Log to database
            self.db.log_event(
                event_type="TRADING_CYCLE_CRASHED",
                message=f"Trading cycle crashed: {e}",
                severity="CRITICAL",
            )
            
            return {
                "status": "crashed",
                "error": str(e),
            }
    
    def _scheduled_trading_cycle(self) -> None:
        """Internal method for scheduled trading cycles."""
        if not self.enable_auto_trading:
            logger.debug("Auto-trading disabled, skipping scheduled cycle")
            return
        
        # Check if market is open
        if not self._is_market_open():
            logger.debug("Market closed, skipping trading cycle")
            return
        
        logger.info("Running scheduled trading cycle")
        self.run_trading_cycle()
    
    # ── Model Retraining ───────────────────────────────────────────────────
    
    def run_model_retraining(self) -> dict:
        """
        Runs model retraining for stale models.
        
        Returns:
            Retraining summary
        """
        logger.info("Starting model retraining")
        
        try:
            results = self.model_trainer.retrain_stale_models(
                max_age_days=7
            )
            
            logger.info(
                f"Model retraining complete | "
                f"Retrained: {results.get('successful', 0)}/{results.get('stale_symbols', 0)}"
            )
            
            return results
        
        except Exception as e:
            logger.error(f"Model retraining crashed: {e}", exc_info=True)
            
            self.db.log_event(
                event_type="MODEL_RETRAINING_CRASHED",
                message=f"Model retraining crashed: {e}",
                severity="ERROR",
            )
            
            return {
                "status": "crashed",
                "error": str(e),
            }
    
    def _scheduled_model_retraining(self) -> None:
        """Internal method for scheduled model retraining."""
        logger.info("Running scheduled model retraining")
        self.run_model_retraining()
    
    # ── Data Cleanup ───────────────────────────────────────────────────────
    
    def run_data_cleanup(self) -> None:
        """Runs daily data cleanup tasks."""
        logger.info("Starting data cleanup")
        
        try:
            # Clean old cache entries
            deleted = self.db.cleanup_old_cache(days=7)
            
            logger.info(f"Data cleanup complete | Deleted: {deleted} cache entries")
        
        except Exception as e:
            logger.error(f"Data cleanup failed: {e}", exc_info=True)
    
    # ── Market Hours Check ─────────────────────────────────────────────────
    
    def _is_market_open(self) -> bool:
        """
        Checks if the market is currently open.
        
        Returns:
            True if market is open, False otherwise
        """
        now = datetime.now()
        current_time = now.time()
        
        # Check day of week (Monday=0, Sunday=6)
        if now.weekday() >= 5:  # Weekend
            return False
        
        # Check market hours based on target market
        if settings.TARGET_MARKET == "india":
            return NSE_HOURS.open_time <= current_time <= NSE_HOURS.close_time
        elif settings.TARGET_MARKET == "us":
            return NYSE_HOURS.open_time <= current_time <= NYSE_HOURS.close_time
        else:
            # Both markets - check if either is open
            india_open = NSE_HOURS.open_time <= current_time <= NSE_HOURS.close_time
            us_open = NYSE_HOURS.open_time <= current_time <= NYSE_HOURS.close_time
            return india_open or us_open
    
    # ── Scheduler Control ──────────────────────────────────────────────────
    
    def start(self) -> None:
        """
        Starts the scheduler with all automated jobs.
        
        Jobs:
          - Trading cycle: Every hour during market hours
          - Model retraining: Sunday 02:00 AM
          - Data cleanup: Daily 01:00 AM
        """
        if self._is_running:
            logger.warning("Scheduler already running")
            return
        
        logger.info("Starting trading scheduler")
        
        # ── Job 1: Trading Cycle (hourly during market hours) ──────────────
        if self.enable_auto_trading:
            # India market hours: 9:15 AM - 3:30 PM IST
            # Run every hour: 10:00, 11:00, 12:00, 13:00, 14:00, 15:00
            self.scheduler.add_job(
                self._scheduled_trading_cycle,
                CronTrigger(
                    day_of_week='mon-fri',
                    hour='10,11,12,13,14,15',
                    minute=0,
                    timezone='Asia/Kolkata'
                ),
                id='trading_cycle_india',
                name='Trading Cycle (India)',
            )
            
            # US market hours: 9:30 AM - 4:00 PM EST
            # Run every hour: 10:00, 11:00, 12:00, 13:00, 14:00, 15:00
            self.scheduler.add_job(
                self._scheduled_trading_cycle,
                CronTrigger(
                    day_of_week='mon-fri',
                    hour='10,11,12,13,14,15',
                    minute=0,
                    timezone='America/New_York'
                ),
                id='trading_cycle_us',
                name='Trading Cycle (US)',
            )
            
            logger.info("Trading cycle jobs scheduled (hourly during market hours)")
        else:
            logger.info("Auto-trading disabled, trading cycle jobs not scheduled")
        
        # ── Job 2: Model Retraining (weekly) ───────────────────────────────
        self.scheduler.add_job(
            self._scheduled_model_retraining,
            CronTrigger(
                day_of_week='sun',
                hour=2,
                minute=0,
            ),
            id='model_retraining',
            name='Model Retraining (Weekly)',
        )
        logger.info("Model retraining job scheduled (Sunday 02:00 AM)")
        
        # ── Job 3: Data Cleanup (daily) ────────────────────────────────────
        self.scheduler.add_job(
            self.run_data_cleanup,
            CronTrigger(
                hour=1,
                minute=0,
            ),
            id='data_cleanup',
            name='Data Cleanup (Daily)',
        )
        logger.info("Data cleanup job scheduled (daily 01:00 AM)")
        
        # Start the scheduler
        self.scheduler.start()
        self._is_running = True
        
        logger.info("✓ Trading scheduler started successfully")
        
        # Log scheduled jobs
        jobs = self.scheduler.get_jobs()
        logger.info(f"Active jobs: {len(jobs)}")
        for job in jobs:
            logger.info(f"  - {job.name}: Next run at {job.next_run_time}")
    
    def stop(self) -> None:
        """Stops the scheduler."""
        if not self._is_running:
            logger.warning("Scheduler not running")
            return
        
        logger.info("Stopping trading scheduler")
        self.scheduler.shutdown()
        self._is_running = False
        logger.info("✓ Trading scheduler stopped")
    
    def get_next_run_times(self) -> dict:
        """
        Returns the next scheduled run times for all jobs.
        
        Returns:
            Dict mapping job_id → next_run_time
        """
        jobs = self.scheduler.get_jobs()
        return {
            job.id: job.next_run_time.isoformat() if job.next_run_time else None
            for job in jobs
        }
    
    def pause(self) -> None:
        """Pauses all scheduled jobs."""
        self.scheduler.pause()
        logger.info("Scheduler paused")
    
    def resume(self) -> None:
        """Resumes all scheduled jobs."""
        self.scheduler.resume()
        logger.info("Scheduler resumed")


# ═══════════════════════════════════════════════════════════════
# MAIN (for testing)
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Example: Run one-time trading cycle
    scheduler = TradingScheduler(broker_type="paper")
    results = scheduler.run_trading_cycle()
    print(f"Trading cycle complete: {results}")
