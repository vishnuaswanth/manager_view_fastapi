"""
In-memory TTL Cache Implementation
Thread-safe caching with configurable TTL and LRU eviction.
"""

import time
import logging
from threading import Lock
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class TTLCache:
    """Thread-safe in-memory TTL cache with LRU eviction."""

    def __init__(self, max_size: int, ttl_seconds: int):
        """
        Initialize TTL cache.

        Args:
            max_size: Maximum number of entries to store
            ttl_seconds: Time-to-live in seconds for each entry
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, tuple] = {}  # key -> (value, timestamp, ttl)
        self.lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        with self.lock:
            if key not in self.cache:
                return None

            value, timestamp, ttl = self.cache[key]

            # Check if expired
            if time.time() - timestamp > ttl:
                del self.cache[key]
                logger.debug(f"[Cache] Key expired: {key}")
                return None

            logger.debug(f"[Cache] Hit: {key}")
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Set value in cache with LRU eviction.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Optional TTL in seconds for this specific entry
        """
        with self.lock:
            # Evict expired entries first
            current_time = time.time()
            expired_keys = [
                k for k, (_, ts, entry_ttl) in self.cache.items()
                if current_time - ts > entry_ttl
            ]
            for k in expired_keys:
                del self.cache[k]
                logger.debug(f"[Cache] Evicted expired key: {k}")

            # If still at max size, evict oldest entry (LRU)
            if len(self.cache) >= self.max_size and key not in self.cache:
                oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
                del self.cache[oldest_key]
                logger.debug(f"[Cache] Evicted oldest key (LRU): {oldest_key}")

            # Set new value with either the provided TTL or the default one
            entry_ttl = ttl if ttl is not None else self.ttl_seconds
            self.cache[key] = (value, current_time, entry_ttl)
            logger.debug(f"[Cache] Set: {key} with TTL {entry_ttl}s")

    def clear(self) -> None:
        """Clear all cache entries."""
        with self.lock:
            self.cache.clear()
            logger.info("[Cache] Cleared all entries")

    def delete(self, key: str) -> bool:
        """
        Delete a specific key from cache.

        Args:
            key: Cache key to delete

        Returns:
            True if key was deleted, False if not found
        """
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                logger.debug(f"[Cache] Deleted key: {key}")
                return True
            return False

    def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern (simple substring match).

        Args:
            pattern: Substring to match in cache keys

        Returns:
            Number of keys deleted
        """
        with self.lock:
            keys_to_delete = [k for k in self.cache.keys() if pattern in k]
            for k in keys_to_delete:
                del self.cache[k]
                logger.debug(f"[Cache] Deleted key (pattern match): {k}")

            if keys_to_delete:
                logger.info(f"[Cache] Deleted {len(keys_to_delete)} keys matching pattern: {pattern}")

            return len(keys_to_delete)

    def size(self) -> int:
        """Get current cache size."""
        with self.lock:
            return len(self.cache)

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self.lock:
            current_time = time.time()
            active_entries = sum(
                1 for _, ts, entry_ttl in self.cache.values()
                if current_time - ts <= entry_ttl
            )
            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
                "active_entries": active_entries
            }
