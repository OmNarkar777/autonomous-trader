"""
scripts/health_check.py
========================
System health check and diagnostics.
"""

import sys
from datetime import datetime
from data.storage.database import DatabaseManager
from data.storage.cache import cache
from ml.training.trainer import ModelTrainer
from orchestrator.circuit_breaker import CircuitBreaker
from config.logging_config import get_logger
from config.constants import INDIA_WATCHLIST, US_WATCHLIST
from config.settings import settings

logger = get_logger(__name__)


def check_database():
    """Check database connectivity and status."""
    print("📊 Database Check:")
    try:
        db = DatabaseManager()
        
        # Get stats
        trades_count = len(db.get_all_trades())
        portfolio = db.get_portfolio()
        
        print(f"  ✓ Database connected")
        print(f"  ✓ Trades in database: {trades_count}")
        print(f"  ✓ Open positions: {len(portfolio)}")
        return True
    except Exception as e:
        print(f"  ✗ Database error: {e}")
        return False


def check_cache():
    """Check cache connectivity."""
    print("\n💾 Cache Check:")
    try:
        # Test cache operations
        test_key = "health_check_test"
        cache.set(test_key, "test_value", ttl=10)
        value = cache.get(test_key)
        
        if value == "test_value":
            print(f"  ✓ Cache working")
            return True
        else:
            print(f"  ✗ Cache read/write mismatch")
            return False
    except Exception as e:
        print(f"  ✗ Cache error: {e}")
        return False


def check_models():
    """Check ML models status."""
    print("\n🤖 ML Models Check:")
    try:
        trainer = ModelTrainer()
        
        # Check models for watchlist
        if settings.TARGET_MARKET == "india":
            symbols = INDIA_WATCHLIST[:5]  # Check first 5
        elif settings.TARGET_MARKET == "us":
            symbols = US_WATCHLIST[:5]
        else:
            symbols = (INDIA_WATCHLIST + US_WATCHLIST)[:5]
        
        models_found = 0
        for symbol in symbols:
            if trainer.model_exists(symbol):
                models_found += 1
        
        print(f"  ✓ Models found: {models_found}/{len(symbols)} (sample)")
        
        if models_found == 0:
            print(f"  ⚠ No models found - run: python scripts/train_models.py")
            return False
        
        # Get training statistics
        stats = trainer.get_training_statistics()
        print(f"  ✓ Total models trained: {stats['models_trained']}")
        
        if stats['average_age_days']:
            print(f"  ✓ Average model age: {stats['average_age_days']:.1f} days")
        
        return True
    except Exception as e:
        print(f"  ✗ Models check error: {e}")
        return False


def check_circuit_breaker():
    """Check circuit breaker status."""
    print("\n⚡ Circuit Breaker Check:")
    try:
        breaker = CircuitBreaker()
        status = breaker.get_status()
        
        if status.state == "CLOSED":
            print(f"  ✓ Circuit breaker: CLOSED (normal)")
        else:
            print(f"  ✗ Circuit breaker: {status.state}")
            print(f"    Reason: {status.reason}")
        
        print(f"  ✓ Failure count: {status.failure_count}")
        
        return status.state == "CLOSED"
    except Exception as e:
        print(f"  ✗ Circuit breaker check error: {e}")
        return False


def check_dependencies():
    """Check Python dependencies."""
    print("\n📦 Dependencies Check:")
    
    required = [
        "pandas",
        "numpy",
        "yfinance",
        "tensorflow",
        "xgboost",
        "langgraph",
        "fastapi",
        "pytest",
    ]
    
    missing = []
    for package in required:
        try:
            __import__(package)
        except ImportError:
            missing.append(package)
    
    if not missing:
        print(f"  ✓ All required packages installed")
        return True
    else:
        print(f"  ✗ Missing packages: {', '.join(missing)}")
        print(f"    Run: pip install -r requirements.txt")
        return False


def main():
    print("=" * 60)
    print("AUTONOMOUS TRADER - SYSTEM HEALTH CHECK")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Target Market: {settings.TARGET_MARKET}")
    print("")
    
    checks = {
        "Dependencies": check_dependencies(),
        "Database": check_database(),
        "Cache": check_cache(),
        "ML Models": check_models(),
        "Circuit Breaker": check_circuit_breaker(),
    }
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    
    for name, status in checks.items():
        icon = "✓" if status else "✗"
        print(f"{icon} {name}")
    
    print("")
    print(f"Checks passed: {passed}/{total}")
    
    if passed == total:
        print("\n✅ System is healthy!")
        sys.exit(0)
    else:
        print("\n⚠️ System has issues - see above")
        sys.exit(1)


if __name__ == "__main__":
    main()
