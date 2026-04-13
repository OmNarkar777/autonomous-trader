"""
data/storage/cache.py
======================
Redis-based in-memory caching layer for high-frequency data.

Why Redis on top of SQLite?
  - SQLite is great for persistent data (trades, portfolio, events)
  - Redis is faster for ephemeral, high-frequency reads (price ticks, features)
  - Reduces disk I/O during analysis cycles

What's cached here:
  - Live price ticks (TTL: 60 seconds)
  - Computed technical features (TTL: 5 minutes)
  - ML model predictions (TTL: 10 minutes)
  - Agent outputs during a trading cycle (TTL: 1 hour)

Graceful degradation: If Redis is unavailable, methods return None/False
and the system falls back to direct computation or SQLite cache.

Usage:
    from data.storage.cache import CacheManager
    cache = CacheManager()
    
    # Store a price
    cache.set("price:RELIANCE.NS", {"current": 2450.30, "volume": 1234567}, ttl=60)
    
    # Retrieve
    price_data = cache.get("price:RELIANCE.NS")
    
    # Store ML prediction
    cache.set_json("ml_pred:RELIANCE.NS", prediction_dict, ttl=600)
"""

from __future__ import annotations

import json
import pickle
from typing import Any, Optional, List, Dict
from datetime import timedelta

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from config.settings import settings
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# CACHE MANAGER
# ═══════════════════════════════════════════════════════════════

class CacheManager:
    """
    Redis cache wrapper with automatic fallback if Redis is unavailable.
    
    Thread-safe (Redis client is thread-safe by default).
    All methods gracefully return None/False on Redis errors
    rather than crashing the application.
    """
    
    # Key namespace prefix to avoid collisions with other apps
    _KEY_PREFIX = "autotrader:"
    
    # Serialization format
    _USE_JSON = True  # True = JSON (human-readable), False = pickle (faster, binary)
    
    def __init__(
        self,
        host: str = None,
        port: int = None,
        db: int = None,
    ):
        """
        Initialises Redis connection.
        
        If Redis is not installed or cannot connect, logs a warning
        and all cache operations become no-ops (return None/False).
        """
        self._redis: Optional[redis.Redis] = None
        self._is_available = False
        
        if not REDIS_AVAILABLE:
            logger.warning(
                "redis-py not installed. Cache layer disabled. "
                "Install with: pip install redis"
            )
            return
        
        host = host or settings.REDIS_HOST
        port = port or settings.REDIS_PORT
        db = db or settings.REDIS_DB
        
        try:
            self._redis = redis.Redis(
                host=host,
                port=port,
                db=db,
                decode_responses=False,  # We'll handle encoding ourselves
                socket_timeout=2,
                socket_connect_timeout=2,
                retry_on_timeout=True,
                health_check_interval=30,
            )
            # Test connection
            self._redis.ping()
            self._is_available = True
            logger.info(f"Redis cache connected: {host}:{port}/{db}")
        
        except redis.ConnectionError as e:
            logger.warning(
                f"Redis connection failed: {e}. "
                f"Cache layer disabled. System will still work without it."
            )
        except Exception as e:
            logger.warning(f"Redis initialisation error: {e}. Cache disabled.")
    
    # ── Internal: Key handling ─────────────────────────────────────────────
    
    def _make_key(self, key: str) -> str:
        """Adds namespace prefix to key."""
        return f"{self._KEY_PREFIX}{key}"
    
    def _serialize(self, value: Any) -> bytes:
        """Serializes a Python object to bytes for Redis storage."""
        if self._USE_JSON:
            return json.dumps(value, default=str).encode("utf-8")
        else:
            return pickle.dumps(value)
    
    def _deserialize(self, data: bytes) -> Any:
        """Deserializes bytes back to a Python object."""
        if self._USE_JSON:
            return json.loads(data.decode("utf-8"))
        else:
            return pickle.loads(data)
    
    # ── Core Cache Operations ──────────────────────────────────────────────
    
    def get(self, key: str) -> Optional[Any]:
        """
        Retrieves a value from cache.
        
        Returns:
            The cached value, or None if key doesn't exist or Redis is unavailable.
        """
        if not self._is_available:
            return None
        
        try:
            full_key = self._make_key(key)
            data = self._redis.get(full_key)
            if data is None:
                return None
            return self._deserialize(data)
        except Exception as e:
            logger.debug(f"Cache get failed for key '{key}': {e}")
            return None
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Stores a value in cache with optional TTL (time-to-live in seconds).
        
        Args:
            key: Cache key (will be namespaced automatically)
            value: Any JSON-serializable or picklable Python object
            ttl: Expiration time in seconds. None = no expiration.
        
        Returns:
            True if successful, False otherwise.
        """
        if not self._is_available:
            return False
        
        try:
            full_key = self._make_key(key)
            data = self._serialize(value)
            
            if ttl:
                self._redis.setex(full_key, ttl, data)
            else:
                self._redis.set(full_key, data)
            
            return True
        except Exception as e:
            logger.debug(f"Cache set failed for key '{key}': {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """
        Deletes a key from cache.
        
        Returns:
            True if key was deleted, False if it didn't exist or Redis unavailable.
        """
        if not self._is_available:
            return False
        
        try:
            full_key = self._make_key(key)
            result = self._redis.delete(full_key)
            return result > 0
        except Exception as e:
            logger.debug(f"Cache delete failed for key '{key}': {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """
        Checks if a key exists in cache.
        
        Returns:
            True if key exists, False otherwise.
        """
        if not self._is_available:
            return False
        
        try:
            full_key = self._make_key(key)
            return self._redis.exists(full_key) > 0
        except Exception as e:
            logger.debug(f"Cache exists check failed for key '{key}': {e}")
            return False
    
    def expire(self, key: str, ttl: int) -> bool:
        """
        Sets or updates the TTL for an existing key.
        
        Returns:
            True if expiration was set, False if key doesn't exist or error.
        """
        if not self._is_available:
            return False
        
        try:
            full_key = self._make_key(key)
            return self._redis.expire(full_key, ttl)
        except Exception as e:
            logger.debug(f"Cache expire failed for key '{key}': {e}")
            return False
    
    def ttl(self, key: str) -> int:
        """
        Returns the remaining TTL for a key in seconds.
        
        Returns:
            Seconds remaining, or -1 if key has no expiration, or -2 if key doesn't exist.
        """
        if not self._is_available:
            return -2
        
        try:
            full_key = self._make_key(key)
            return self._redis.ttl(full_key)
        except Exception as e:
            logger.debug(f"Cache ttl check failed for key '{key}': {e}")
            return -2
    
    # ── Convenience Methods ────────────────────────────────────────────────
    
    def get_json(self, key: str) -> Optional[Dict]:
        """Retrieves and parses a JSON value. Alias for get()."""
        return self.get(key)
    
    def set_json(self, key: str, value: Dict, ttl: Optional[int] = None) -> bool:
        """Stores a dict as JSON. Alias for set()."""
        return self.set(key, value, ttl=ttl)
    
    def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """
        Atomically increments a numeric value.
        Creates the key with value=0 if it doesn't exist.
        
        Returns:
            The new value after increment, or None on error.
        """
        if not self._is_available:
            return None
        
        try:
            full_key = self._make_key(key)
            return self._redis.incrby(full_key, amount)
        except Exception as e:
            logger.debug(f"Cache increment failed for key '{key}': {e}")
            return None
    
    def decrement(self, key: str, amount: int = 1) -> Optional[int]:
        """
        Atomically decrements a numeric value.
        
        Returns:
            The new value after decrement, or None on error.
        """
        if not self._is_available:
            return None
        
        try:
            full_key = self._make_key(key)
            return self._redis.decrby(full_key, amount)
        except Exception as e:
            logger.debug(f"Cache decrement failed for key '{key}': {e}")
            return None
    
    # ── Bulk Operations ────────────────────────────────────────────────────
    
    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """
        Retrieves multiple keys in a single operation.
        
        Returns:
            Dict mapping key → value for keys that exist.
            Missing keys are absent from the returned dict.
        """
        if not self._is_available or not keys:
            return {}
        
        try:
            full_keys = [self._make_key(k) for k in keys]
            values = self._redis.mget(full_keys)
            
            result = {}
            for key, data in zip(keys, values):
                if data is not None:
                    result[key] = self._deserialize(data)
            
            return result
        except Exception as e:
            logger.debug(f"Cache get_many failed: {e}")
            return {}
    
    def set_many(self, mapping: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """
        Stores multiple key-value pairs in a single operation.
        
        Note: If TTL is provided, it's applied individually (slower than mset).
        
        Returns:
            True if all sets succeeded, False otherwise.
        """
        if not self._is_available or not mapping:
            return False
        
        try:
            if ttl:
                # With TTL, we need to set each key individually
                pipe = self._redis.pipeline()
                for key, value in mapping.items():
                    full_key = self._make_key(key)
                    data = self._serialize(value)
                    pipe.setex(full_key, ttl, data)
                pipe.execute()
            else:
                # Without TTL, use fast mset
                full_mapping = {
                    self._make_key(k): self._serialize(v)
                    for k, v in mapping.items()
                }
                self._redis.mset(full_mapping)
            
            return True
        except Exception as e:
            logger.debug(f"Cache set_many failed: {e}")
            return False
    
    def delete_many(self, keys: List[str]) -> int:
        """
        Deletes multiple keys in a single operation.
        
        Returns:
            Number of keys deleted.
        """
        if not self._is_available or not keys:
            return 0
        
        try:
            full_keys = [self._make_key(k) for k in keys]
            return self._redis.delete(*full_keys)
        except Exception as e:
            logger.debug(f"Cache delete_many failed: {e}")
            return 0
    
    # ── Pattern-Based Operations ───────────────────────────────────────────
    
    def keys(self, pattern: str) -> List[str]:
        """
        Returns all keys matching a pattern.
        
        Pattern examples:
          - "price:*" → all price keys
          - "ml_pred:RELIANCE*" → all ML predictions for RELIANCE symbols
        
        WARNING: KEYS command scans the entire keyspace — use sparingly in production.
        
        Returns:
            List of matching keys (without namespace prefix).
        """
        if not self._is_available:
            return []
        
        try:
            full_pattern = self._make_key(pattern)
            full_keys = self._redis.keys(full_pattern)
            # Strip namespace prefix from results
            prefix_len = len(self._KEY_PREFIX)
            return [k.decode("utf-8")[prefix_len:] for k in full_keys]
        except Exception as e:
            logger.debug(f"Cache keys scan failed for pattern '{pattern}': {e}")
            return []
    
    def delete_pattern(self, pattern: str) -> int:
        """
        Deletes all keys matching a pattern.
        
        Example:
            cache.delete_pattern("price:*")  # Clear all cached prices
        
        Returns:
            Number of keys deleted.
        """
        if not self._is_available:
            return 0
        
        try:
            keys_to_delete = self.keys(pattern)
            if keys_to_delete:
                return self.delete_many(keys_to_delete)
            return 0
        except Exception as e:
            logger.debug(f"Cache delete_pattern failed for '{pattern}': {e}")
            return 0
    
    # ── Trading-Specific Helpers ───────────────────────────────────────────
    
    def cache_price(
        self,
        symbol: str,
        price_data: Dict[str, Any],
        ttl: int = 60,
    ) -> bool:
        """
        Stores current price data for a symbol.
        Standard TTL: 60 seconds (prices update frequently).
        """
        return self.set(f"price:{symbol}", price_data, ttl=ttl)
    
    def get_cached_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached price data for a symbol."""
        return self.get(f"price:{symbol}")
    
    def cache_features(
        self,
        symbol: str,
        features: Dict[str, float],
        ttl: int = 300,
    ) -> bool:
        """
        Stores computed technical features for a symbol.
        Standard TTL: 5 minutes (recomputed each analysis cycle).
        """
        return self.set(f"features:{symbol}", features, ttl=ttl)
    
    def get_cached_features(self, symbol: str) -> Optional[Dict[str, float]]:
        """Retrieves cached technical features."""
        return self.get(f"features:{symbol}")
    
    def cache_ml_prediction(
        self,
        symbol: str,
        prediction: Dict[str, Any],
        ttl: int = 600,
    ) -> bool:
        """
        Stores ML model prediction for a symbol.
        Standard TTL: 10 minutes (models don't change frequently).
        """
        return self.set(f"ml_pred:{symbol}", prediction, ttl=ttl)
    
    def get_cached_ml_prediction(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached ML prediction."""
        return self.get(f"ml_pred:{symbol}")
    
    def cache_agent_output(
        self,
        agent_name: str,
        symbol: str,
        output: Dict[str, Any],
        ttl: int = 3600,
    ) -> bool:
        """
        Stores an agent's output during an analysis cycle.
        Standard TTL: 1 hour (valid for current trading cycle).
        """
        return self.set(f"agent:{agent_name}:{symbol}", output, ttl=ttl)
    
    def get_cached_agent_output(
        self,
        agent_name: str,
        symbol: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieves cached agent output."""
        return self.get(f"agent:{agent_name}:{symbol}")
    
    def invalidate_symbol(self, symbol: str) -> int:
        """
        Clears all cached data for a specific symbol.
        Used when we detect stale/bad data and need a fresh fetch.
        
        Returns:
            Number of keys deleted.
        """
        return self.delete_pattern(f"*:{symbol}")
    
    def clear_all_prices(self) -> int:
        """Clears all cached price data across all symbols."""
        return self.delete_pattern("price:*")
    
    def clear_all_features(self) -> int:
        """Clears all cached technical features."""
        return self.delete_pattern("features:*")
    
    def clear_all_predictions(self) -> int:
        """Clears all cached ML predictions."""
        return self.delete_pattern("ml_pred:*")
    
    # ── Admin / Debugging ──────────────────────────────────────────────────
    
    def info(self) -> Dict[str, Any]:
        """
        Returns Redis server info.
        Useful for monitoring memory usage, hit rate, etc.
        """
        if not self._is_available:
            return {"status": "unavailable"}
        
        try:
            info = self._redis.info()
            return {
                "status": "connected",
                "used_memory_human": info.get("used_memory_human"),
                "total_keys": self._redis.dbsize(),
                "hit_rate": info.get("keyspace_hits", 0) / max(
                    info.get("keyspace_hits", 0) + info.get("keyspace_misses", 1), 1
                ),
            }
        except Exception as e:
            logger.debug(f"Cache info failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def flush(self) -> bool:
        """
        **DANGER**: Deletes ALL keys in the current database.
        Only use for testing or manual cleanup.
        
        Returns:
            True if successful, False otherwise.
        """
        if not self._is_available:
            return False
        
        try:
            self._redis.flushdb()
            logger.warning("Redis cache flushed — all keys deleted")
            return True
        except Exception as e:
            logger.error(f"Cache flush failed: {e}")
            return False
    
    def is_available(self) -> bool:
        """Returns True if Redis is connected and available."""
        return self._is_available
    
    def ping(self) -> bool:
        """
        Tests Redis connection.
        
        Returns:
            True if Redis responds to PING, False otherwise.
        """
        if not self._is_available:
            return False
        
        try:
            return self._redis.ping()
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════
# Import this singleton throughout the application:
#   from data.storage.cache import cache
#
# It automatically handles Redis unavailability gracefully.

try:
    cache = CacheManager()
except Exception as e:
    logger.error(f"Failed to initialise cache manager: {e}")
    # Create a dummy cache manager that always returns None/False
    cache = CacheManager.__new__(CacheManager)
    cache._is_available = False
    cache._redis = None
