"""
Shared cache module for all API routers.

Centralizes cache instance management and provides a single point for
cache invalidation across all routers.

Cache Instances:
    - filters_cache: 5 minutes TTL, max 8 entries (for filter dropdowns)
    - data_cache: 60 seconds TTL, max 64 entries (for data responses)

Usage:
    from code.cache import filters_cache, data_cache, clear_all_caches

    # Set cache
    filters_cache.set("my_key", {"data": "value"})

    # Get cache
    result = filters_cache.get("my_key")

    # Clear all caches
    clear_all_caches()
"""

from code.logics.cache_utils import TTLCache
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ============ Manager View & Forecast Cascade Caches ============

# Filters cache: Used by both manager view filters and forecast cascade filters
# 5 minutes TTL, max 8 entries
# Keys: "filters:v1", "cascade:years", "cascade:months", etc.
filters_cache = TTLCache(max_size=8, ttl_seconds=300)

# Data cache: Used by manager view data endpoint
# 60 seconds TTL, max 64 entries
# Keys: "data:v1:{month}:{category}"
data_cache = TTLCache(max_size=64, ttl_seconds=60)


def clear_all_caches() -> dict:
    """
    Clear all caches across all routers.

    This function is called when forecast files are uploaded to ensure
    that all cached data is invalidated and fresh data is fetched.

    Clears:
        - filters_cache (manager view filters, forecast cascade filters)
        - data_cache (manager view hierarchical data)

    Returns:
        Dictionary with cache clearing statistics:
        {
            "success": True,
            "filters_cache": {"size": 0, "max_size": 8, "ttl_seconds": 300},
            "data_cache": {"size": 0, "max_size": 64, "ttl_seconds": 60},
            "cleared_at": "2025-01-15T10:30:00.123456",
            "message": "All caches cleared successfully"
        }
    """
    try:
        # Clear all cache instances
        filters_cache.clear()
        data_cache.clear()

        cleared_at = datetime.now().isoformat()

        logger.info(
            f"[Cache] Cleared all caches at {cleared_at} - "
            f"filters_cache: {filters_cache.stats()}, "
            f"data_cache: {data_cache.stats()}"
        )

        return {
            "success": True,
            "filters_cache": filters_cache.stats(),
            "data_cache": data_cache.stats(),
            "cleared_at": cleared_at,
            "message": "All caches cleared successfully"
        }
    except Exception as e:
        logger.error(f"[Cache] Error clearing all caches: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "message": "Error clearing caches"
        }


__all__ = ['filters_cache', 'data_cache', 'clear_all_caches']
