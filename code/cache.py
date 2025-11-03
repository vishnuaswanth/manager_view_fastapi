"""
Shared cache module for all API routers.

Centralizes cache instance management and provides a single point for
cache invalidation across all routers.

Cache Instances:
    - filters_cache: 5 minutes TTL, max 8 entries (for filter dropdowns)
    - data_cache: 60 seconds TTL, max 64 entries (for data responses)
    - month_config_cache: 15 minutes TTL, max 20 entries (for month configurations)
    - allocation_list_cache: 30 seconds TTL, max 50 entries (for execution lists)
    - allocation_detail_cache: dynamic TTL, max 100 entries (for execution details)

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


# ============ Month Configuration Caches ============

# Month configuration cache: Used by month config endpoints
# 15 minutes TTL, max 20 entries
# Keys: "month_config:v1:{month}:{year}:{work_type}"
month_config_cache = TTLCache(max_size=20, ttl_seconds=900)


# ============ Allocation Execution Caches ============

# Allocation executions list cache: Used by execution listing endpoint
# 30 seconds TTL, max 50 entries
# Keys: "allocation_executions:v1:{month}:{year}:{status}:{uploaded_by}:{limit}:{offset}"
allocation_list_cache = TTLCache(max_size=50, ttl_seconds=30)

# Allocation execution detail cache: Used by execution detail endpoint
# Dynamic TTL (5s for active, 1hr for completed), max 100 entries
# Keys: "allocation_execution_detail:v1:{execution_id}"
allocation_detail_cache = TTLCache(max_size=100, ttl_seconds=5)


# ============ Cache Key Generation Helpers ============

def generate_month_config_cache_key(
    month: str = None,
    year: int = None,
    work_type: str = None
) -> str:
    """
    Generate cache key for month configuration queries.

    Args:
        month: Month name (optional)
        year: Year number (optional)
        work_type: Work type "Domestic" or "Global" (optional)

    Returns:
        Cache key string

    Examples:
        generate_month_config_cache_key("January", 2025, "Domestic")
        -> "month_config:v1:January:2025:Domestic"

        generate_month_config_cache_key()
        -> "month_config:v1:::"
    """
    month_part = month or ""
    year_part = str(year) if year else ""
    work_type_part = work_type or ""
    return f"month_config:v1:{month_part}:{year_part}:{work_type_part}"


def generate_execution_list_cache_key(
    month: str = None,
    year: int = None,
    status: str = None,
    uploaded_by: str = None,
    limit: int = 50,
    offset: int = 0
) -> str:
    """
    Generate cache key for execution list queries.

    Args:
        month: Month name (optional)
        year: Year number (optional)
        status: Execution status (optional)
        uploaded_by: Username (optional)
        limit: Pagination limit (default: 50)
        offset: Pagination offset (default: 0)

    Returns:
        Cache key string

    Examples:
        generate_execution_list_cache_key("January", 2025, "SUCCESS", "john", 50, 0)
        -> "allocation_executions:v1:January:2025:SUCCESS:john:50:0"
    """
    month_part = month or ""
    year_part = str(year) if year else ""
    status_part = status or ""
    uploaded_by_part = uploaded_by or ""
    return f"allocation_executions:v1:{month_part}:{year_part}:{status_part}:{uploaded_by_part}:{limit}:{offset}"


def generate_execution_detail_cache_key(execution_id: str) -> str:
    """
    Generate cache key for execution detail queries.

    Args:
        execution_id: UUID of the execution

    Returns:
        Cache key string

    Examples:
        generate_execution_detail_cache_key("550e8400-e29b-41d4-a716-446655440000")
        -> "allocation_execution_detail:v1:550e8400-e29b-41d4-a716-446655440000"
    """
    return f"allocation_execution_detail:v1:{execution_id}"


# ============ Cache Invalidation Helpers ============

def invalidate_month_config_cache() -> int:
    """
    Invalidate all month configuration cache entries.

    Called when month configurations are created, updated, or deleted.

    Returns:
        Number of cache entries invalidated
    """
    try:
        # Clear all month config cache entries
        month_config_cache.clear()
        count = month_config_cache.stats()["size"]
        logger.info(f"[Cache] Invalidated all month configuration cache entries")
        return count
    except Exception as e:
        logger.error(f"[Cache] Error invalidating month config cache: {e}", exc_info=True)
        return 0


def invalidate_execution_list_cache() -> int:
    """
    Invalidate all execution list cache entries.

    Called when new executions are created or statuses change.

    Returns:
        Number of cache entries invalidated
    """
    try:
        # Clear all execution list cache entries
        allocation_list_cache.clear()
        count = allocation_list_cache.stats()["size"]
        logger.info(f"[Cache] Invalidated all execution list cache entries")
        return count
    except Exception as e:
        logger.error(f"[Cache] Error invalidating execution list cache: {e}", exc_info=True)
        return 0


def invalidate_execution_detail_cache(execution_id: str = None) -> bool:
    """
    Invalidate specific or all execution detail cache entries.

    Called when execution status changes.

    Args:
        execution_id: UUID of the execution to invalidate (optional, if None clears all)

    Returns:
        True if cache entry/entries were deleted, False otherwise
    """
    try:
        if execution_id:
            cache_key = generate_execution_detail_cache_key(execution_id)
            deleted = allocation_detail_cache.delete(cache_key)
            if deleted:
                logger.info(f"[Cache] Invalidated execution detail cache for {execution_id}")
            return deleted
        else:
            # Clear all execution detail cache entries
            allocation_detail_cache.clear()
            logger.info(f"[Cache] Invalidated all execution detail cache entries")
            return True
    except Exception as e:
        logger.error(f"[Cache] Error invalidating execution detail cache: {e}", exc_info=True)
        return False


def clear_all_caches() -> dict:
    """
    Clear all caches across all routers.

    This function is called when forecast files are uploaded to ensure
    that all cached data is invalidated and fresh data is fetched.

    Clears:
        - filters_cache (manager view filters, forecast cascade filters)
        - data_cache (manager view hierarchical data)
        - month_config_cache (month configurations)
        - allocation_list_cache (execution lists)
        - allocation_detail_cache (execution details)

    Returns:
        Dictionary with cache clearing statistics:
        {
            "success": True,
            "filters_cache": {"size": 0, "max_size": 8, "ttl_seconds": 300},
            "data_cache": {"size": 0, "max_size": 64, "ttl_seconds": 60},
            "month_config_cache": {"size": 0, "max_size": 20, "ttl_seconds": 900},
            "allocation_list_cache": {"size": 0, "max_size": 50, "ttl_seconds": 30},
            "allocation_detail_cache": {"size": 0, "max_size": 100, "ttl_seconds": 5},
            "cleared_at": "2025-01-15T10:30:00.123456",
            "message": "All caches cleared successfully"
        }
    """
    try:
        # Clear all cache instances
        filters_cache.clear()
        data_cache.clear()
        month_config_cache.clear()
        allocation_list_cache.clear()
        allocation_detail_cache.clear()

        cleared_at = datetime.now().isoformat()

        logger.info(
            f"[Cache] Cleared all caches at {cleared_at} - "
            f"filters_cache: {filters_cache.stats()}, "
            f"data_cache: {data_cache.stats()}, "
            f"month_config_cache: {month_config_cache.stats()}, "
            f"allocation_list_cache: {allocation_list_cache.stats()}, "
            f"allocation_detail_cache: {allocation_detail_cache.stats()}"
        )

        return {
            "success": True,
            "filters_cache": filters_cache.stats(),
            "data_cache": data_cache.stats(),
            "month_config_cache": month_config_cache.stats(),
            "allocation_list_cache": allocation_list_cache.stats(),
            "allocation_detail_cache": allocation_detail_cache.stats(),
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


__all__ = [
    'filters_cache',
    'data_cache',
    'month_config_cache',
    'allocation_list_cache',
    'allocation_detail_cache',
    'generate_month_config_cache_key',
    'generate_execution_list_cache_key',
    'generate_execution_detail_cache_key',
    'invalidate_month_config_cache',
    'invalidate_execution_list_cache',
    'invalidate_execution_detail_cache',
    'clear_all_caches'
]
