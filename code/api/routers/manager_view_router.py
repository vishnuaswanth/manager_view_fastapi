"""
Manager View endpoints for hierarchical category reporting.

Provides endpoints for:
- Dropdown filter options (report months, categories)
- Hierarchical category tree with metrics by month
- Debug/QA categorization diagnostics
"""

from fastapi import APIRouter
from typing import Optional
from datetime import datetime, timezone
import logging
import re
from calendar import month_name as cal_month_name

from code.logics.manager_view import (
    get_available_report_months,
    get_category_list,
    build_category_tree,
    get_forecast_months_from_db,
    diagnose_record_categorization
)
from code.logics.db import UploadDataTimeDetails, ForecastModel
from code.logics.cache_utils import TTLCache
from code.api.dependencies import get_core_utils, get_logger
from code.api.utils.responses import success_response, error_response

# Initialize router and dependencies
router = APIRouter()
logger = get_logger(__name__)
core_utils = get_core_utils()

# Initialize caches per API spec
# Filters: 5 minutes TTL, max 8 entries
# Data: 60 seconds TTL, max 64 entries
filters_cache = TTLCache(max_size=8, ttl_seconds=300)
data_cache = TTLCache(max_size=64, ttl_seconds=60)


@router.get("/api/manager-view/filters")
def get_manager_view_filters():
    """
    Get dropdown filter options for manager view.

    Returns available report months and category list for filtering.
    Cached for 5 minutes to improve performance.

    Returns:
        {
            "success": true,
            "report_months": [
                {"value": "2025-01", "display": "January 2025"},
                ...
            ],
            "categories": [
                {"value": "cat_id", "display": "Category Name"},
                ...
            ],
            "timestamp": "2025-01-15T10:30:00Z"
        }

    Cache:
        TTL: 5 minutes
        Key: "filters:v1"
    """
    cache_key = "filters:v1"

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug("[ManagerView] Returning cached filters response")
        return cached_response

    try:
        # Get available report months from database
        db_manager = core_utils.get_db_manager(
            UploadDataTimeDetails,
            limit=1000,
            skip=0,
            select_columns=None
        )
        report_months = get_available_report_months(db_manager)

        # Get categories from config
        categories = get_category_list()

        response = {
            "success": True,
            "report_months": report_months,
            "categories": categories,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(
            f"[ManagerView] Filters endpoint: "
            f"{len(report_months)} months, {len(categories)} categories"
        )
        return response

    except Exception as e:
        logger.error(f"[ManagerView] Error in filters endpoint: {e}", exc_info=True)
        return {
            "success": False,
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@router.get("/api/manager-view/data")
def get_manager_view_data(report_month: str, category: Optional[str] = None):
    """
    Get hierarchical category tree with metrics.

    Returns hierarchical category structure with metrics (cf, hc, cap, gap)
    for each month across 6 forecast months.

    Query Parameters:
        report_month (required): YYYY-MM format (e.g., "2025-02")
        category (optional): Category ID to filter. Empty = All Categories

    Returns:
        {
            "success": true,
            "report_month": "2025-01",
            "months": ["January", "February", ...],
            "categories": [
                {
                    "category_id": "...",
                    "category_name": "...",
                    "months": {
                        "January": {"cf": 100, "hc": 50, "cap": 80, "gap": 20},
                        ...
                    },
                    "children": [...]
                },
                ...
            ],
            "category_name": "All Categories",
            "timestamp": "2025-01-15T10:30:00Z"
        }

    Cache:
        TTL: 60 seconds
        Key: "data:v1:{report_month}:{category}"
    """
    # Generate cache key
    category_key = category if category else "all"
    cache_key = f"data:v1:{report_month}:{category_key}"

    # Check cache first
    cached_response = data_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[ManagerView] Returning cached data response for {cache_key}")
        return cached_response

    try:
        # Validate report_month format (YYYY-MM)
        month_pattern = r'^\d{4}-(0[1-9]|1[0-2])$'
        if not re.match(month_pattern, report_month):
            return {
                "success": False,
                "error": "Invalid report_month (expected YYYY-MM).",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Parse report_month to get month name and year
        year = int(report_month.split('-')[0])
        month_num = int(report_month.split('-')[1])
        month_name_str = list(cal_month_name)[month_num]

        # Get forecast months from database
        db_manager_forecast_months = core_utils.get_db_manager(
            ForecastModel,
            limit=1000,
            skip=0,
            select_columns=None
        )
        forecast_months = get_forecast_months_from_db(
            db_manager_forecast_months,
            month_name_str,
            year
        )

        if not forecast_months:
            logger.warning(
                f"[ManagerView] No forecast months found for {month_name_str} {year}"
            )
            # Return empty response
            return {
                "success": True,
                "report_month": report_month,
                "months": [],
                "categories": [],
                "category_name": "All Categories" if not category else category,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Get forecast records from database
        db_manager_forecast = core_utils.get_db_manager(
            ForecastModel,
            limit=100000,
            skip=0,
            select_columns=None
        )
        data = db_manager_forecast.read_db(month_name_str, year)
        records = data.get("records", [])

        if not records:
            logger.warning(
                f"[ManagerView] No forecast records found for {month_name_str} {year}"
            )
            return {
                "success": True,
                "report_month": report_month,
                "months": forecast_months,
                "categories": [],
                "category_name": "All Categories" if not category else category,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Build category tree
        categories_tree = build_category_tree(
            records,
            forecast_months,
            category_filter=category
        )

        # Get category name
        if category:
            category_list = get_category_list()
            category_name = next(
                (cat["display"] for cat in category_list if cat["value"] == category),
                "Unknown Category"
            )

            # Check if category exists
            if not categories_tree:
                return {
                    "success": False,
                    "error": f"Unknown category id: {category}",
                    "status_code": 404,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
        else:
            category_name = "All Categories"

        response = {
            "success": True,
            "report_month": report_month,
            "months": forecast_months,
            "categories": categories_tree,
            "category_name": category_name,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Cache the response
        data_cache.set(cache_key, response)

        logger.info(
            f"[ManagerView] Data endpoint: {report_month}, "
            f"category={category}, {len(categories_tree)} categories"
        )
        return response

    except Exception as e:
        logger.error(f"[ManagerView] Error in data endpoint: {e}", exc_info=True)
        return {
            "success": False,
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@router.get("/api/manager-view/debug/categorization")
def debug_record_categorization_endpoint(
    report_month: str,
    main_lob: Optional[str] = None,
    state: Optional[str] = None,
    case_type: Optional[str] = None
):
    """
    Debug endpoint for categorization diagnostics.

    **QA/DEBUG ENDPOINT**

    Returns detailed diagnostics showing why a record matched or didn't match
    each category. Helps analysts quickly identify why records aren't
    classifying as expected.

    Query Parameters:
        report_month (required): YYYY-MM format (e.g., "2025-02")
        main_lob (optional): Main LOB value to test
        state (optional): State value to test
        case_type (optional): Case type value to test

    Returns:
        {
            "success": true,
            "report_month": "2025-01",
            "test_record": {
                "main_lob": "...",
                "state": "...",
                "case_type": "..."
            },
            "diagnostics": [
                {
                    "category_id": "...",
                    "category_name": "...",
                    "category_path": "...",
                    "is_match": true,
                    "matched_fields": [...],
                    "unmatched_fields": [...],
                    "total_rules": 3,
                    "matched_rules": 3,
                    "unmatched_rules": 0
                },
                ...
            ],
            "summary": {
                "total_categories": 10,
                "matched_categories": 2,
                "unmatched_categories": 8
            },
            "timestamp": "2025-01-15T10:30:00Z"
        }

    Use Cases:
        - Verify why a record is/isn't appearing in a category
        - Troubleshoot categorization rules
        - QA category configuration changes
    """
    try:
        # Validate report_month format
        month_pattern = r'^\d{4}-(0[1-9]|1[0-2])$'
        if not re.match(month_pattern, report_month):
            return {
                "success": False,
                "error": "Invalid report_month (expected YYYY-MM).",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Build a test record
        test_record = {
            "Centene_Capacity_Plan_Main_LOB": main_lob or "",
            "Centene_Capacity_Plan_State": state or "",
            "Centene_Capacity_Plan_Case_Type": case_type or ""
        }

        # Run diagnostics
        diagnostics = diagnose_record_categorization(test_record)

        response = {
            "success": True,
            "report_month": report_month,
            "test_record": {
                "main_lob": main_lob,
                "state": state,
                "case_type": case_type
            },
            "diagnostics": diagnostics,
            "summary": {
                "total_categories": len(diagnostics),
                "matched_categories": sum(1 for d in diagnostics if d["is_match"]),
                "unmatched_categories": sum(1 for d in diagnostics if not d["is_match"])
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        logger.info(
            f"[ManagerView Debug] Categorization check: "
            f"{len(diagnostics)} categories analyzed"
        )
        return response

    except Exception as e:
        logger.error(
            f"[ManagerView Debug] Error in categorization endpoint: {e}",
            exc_info=True
        )
        return {
            "success": False,
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


# Export caches for use in main.py cache invalidation
__all__ = ['router', 'filters_cache', 'data_cache']
