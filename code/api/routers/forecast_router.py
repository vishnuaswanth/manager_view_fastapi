"""
Forecast cascade filter endpoints.

Provides hierarchical filter dropdowns for forecast data:
- Years → Months → Platforms → Markets → Localities → Worktypes

Each level filters based on the previous selections, ensuring only
valid combinations are shown to users.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
import logging
from sqlalchemy import func

from code.logics.db import ForecastModel
from code.logics.cascade_filters import (
    generate_cascade_cache_key,
    extract_platforms_from_main_lobs,
    extract_markets_from_main_lobs,
    extract_localities_from_main_lobs,
    filter_main_lobs_by_criteria,
    get_month_name_from_number,
    get_month_number_from_name
)
from code.logics.cache_utils import TTLCache
from code.api.dependencies import get_core_utils, get_logger
from code.api.utils.responses import success_response, error_response
from code.api.utils.validators import validate_year

# Initialize router and dependencies
router = APIRouter()
logger = get_logger(__name__)
core_utils = get_core_utils()

# Initialize cache for cascade filters
# 5 minutes TTL, max 8 entries (shared with manager view filters)
filters_cache = TTLCache(max_size=8, ttl_seconds=300)


@router.get("/forecast/filter-years")
def get_forecast_filter_years():
    """
    Get all years that have forecast data available.

    Uses optimized database query (SELECT DISTINCT Year).

    Returns:
        {"years": [{"value": "2025", "display": "2025"}, ...]}

    Cache: TTL=5 minutes
    """
    cache_key = generate_cascade_cache_key("cascade:years")

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug("[Cascade] Returning cached years response")
        return cached_response

    try:
        # Get distinct years using database query (efficient!)
        db_manager = core_utils.get_db_manager(ForecastModel, limit=1, skip=0, select_columns=None)
        years = db_manager.get_distinct_values("Year")

        # Sort in descending order (newest first) and format response
        years_list = [{"value": str(y), "display": str(y)} for y in sorted(years, reverse=True)]
        response = {"years": years_list}

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[Cascade] Filter years endpoint: {len(years_list)} years found")
        return response

    except Exception as e:
        logger.error(f"[Cascade] Error in filter-years endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve available years")


@router.get("/forecast/months/{year}")
def get_forecast_months_for_year(year: int):
    """
    Get available months for the selected year.

    Uses optimized database query (SELECT DISTINCT Month WHERE Year=X).

    Path Parameters:
        year: Selected year (e.g., 2025)

    Returns:
        [{"value": "1", "display": "January"}, {"value": "2", "display": "February"}, ...]

    Cache: TTL=5 minutes
    """
    # Validate year
    year = validate_year(year)

    cache_key = generate_cascade_cache_key("cascade:months", year=year)

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cascade] Returning cached months response for year {year}")
        return cached_response

    try:
        # Get distinct months for this year using database query (efficient!)
        db_manager = core_utils.get_db_manager(ForecastModel, limit=1, skip=0, select_columns=None)

        # Use direct query for year filtering
        with db_manager.SessionLocal() as session:
            query = session.query(func.distinct(ForecastModel.Month))
            query = query.filter(ForecastModel.Year == year)
            query = query.filter(ForecastModel.Month.isnot(None), ForecastModel.Month != '')
            results = query.all()
            months_set = [row[0] for row in results if row[0]]

        if not months_set:
            raise HTTPException(status_code=404, detail=f"No data available for year {year}")

        # Convert month names to numeric format and sort
        month_list = []
        for month_str in months_set:
            try:
                month_num = get_month_number_from_name(month_str)
                month_list.append((month_num, month_str))
            except ValueError:
                logger.warning(f"[Cascade] Invalid month name: {month_str}")
                continue

        # Sort by month number
        month_list.sort(key=lambda x: x[0])

        # Format response
        response = [{"value": str(num), "display": name} for num, name in month_list]

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[Cascade] Months endpoint: {len(response)} months found for year {year}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Cascade] Error in months endpoint for year {year}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve months for year {year}")


@router.get("/forecast/platforms")
def get_forecast_platforms(year: int, month: int):
    """
    Get available platforms (BOC - Basis of Calculation) for selected year and month.

    Uses optimized database query to fetch only distinct Main_LOB values (~10-50 rows).

    Query Parameters:
        year: Selected year
        month: Selected month (1-12)

    Returns:
        [{"value": "Amisys", "display": "Amisys"}, {"value": "Facets", "display": "Facets"}, ...]

    Cache: TTL=5 minutes
    """
    # Validate parameters
    if not year or not month:
        raise HTTPException(status_code=400, detail="Invalid parameters: year and month are required")
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month: must be 1-12")

    year = validate_year(year)

    cache_key = generate_cascade_cache_key("cascade:platforms", year=year, month=month)

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cascade] Returning cached platforms response for year={year}, month={month}")
        return cached_response

    try:
        # Convert month number to month name
        month_name_str = get_month_name_from_number(month)

        # Get distinct Main_LOB values using database query (efficient! ~10-50 rows instead of 100k)
        db_manager = core_utils.get_db_manager(ForecastModel, limit=1, skip=0, select_columns=None)
        main_lob_values = db_manager.get_distinct_values("Centene_Capacity_Plan_Main_LOB", month_name_str, year)

        if not main_lob_values:
            raise HTTPException(
                status_code=404,
                detail=f"No platforms found for year={year}, month={month}"
            )

        # Extract platforms from Main_LOB strings (only ~10-50 parsing operations!)
        platforms = extract_platforms_from_main_lobs(main_lob_values)

        if not platforms:
            raise HTTPException(
                status_code=404,
                detail=f"No platforms found for year={year}, month={month}"
            )

        # Format response
        response = [{"value": platform, "display": platform} for platform in platforms]

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[Cascade] Platforms endpoint: {len(response)} platforms found for {month_name_str} {year}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Cascade] Error in platforms endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve platforms")


@router.get("/forecast/markets")
def get_forecast_markets(year: int, month: int, platform: str):
    """
    Get available markets (insurance types) filtered by platform, year, and month.

    Uses optimized database query to fetch only distinct Main_LOB values (~10-50 rows).

    Query Parameters:
        year: Selected year
        month: Selected month (1-12)
        platform: Selected platform (e.g., "Amisys")

    Returns:
        [{"value": "Medicaid", "display": "Medicaid"}, {"value": "Medicare", "display": "Medicare"}, ...]

    Cache: TTL=5 minutes
    """
    # Validate parameters
    if not year or not month or not platform:
        raise HTTPException(status_code=400, detail="Missing required parameters: year, month, platform")
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month: must be 1-12")

    year = validate_year(year)

    cache_key = generate_cascade_cache_key("cascade:markets", year=year, month=month, platform=platform)

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cascade] Returning cached markets response for year={year}, month={month}, platform={platform}")
        return cached_response

    try:
        # Convert month number to month name
        month_name_str = get_month_name_from_number(month)

        # Get distinct Main_LOB values using database query (efficient!)
        db_manager = core_utils.get_db_manager(ForecastModel, limit=1, skip=0, select_columns=None)
        main_lob_values = db_manager.get_distinct_values("Centene_Capacity_Plan_Main_LOB", month_name_str, year)

        if not main_lob_values:
            raise HTTPException(
                status_code=404,
                detail=f"No markets found for platform={platform}, year={year}, month={month}"
            )

        # Extract markets filtered by platform (only ~10-50 parsing operations!)
        markets = extract_markets_from_main_lobs(main_lob_values, platform)

        if not markets:
            raise HTTPException(
                status_code=404,
                detail=f"No markets found for platform={platform}, year={year}, month={month}"
            )

        # Format response
        response = [{"value": market, "display": market} for market in markets]

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[Cascade] Markets endpoint: {len(response)} markets found for {platform} / {month_name_str} {year}")
        return response

    except HTTPException:
        raise
    except ValueError as ve:
        logger.error(f"[Cascade] Validation error in markets endpoint: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[Cascade] Error in markets endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve markets")


@router.get("/forecast/localities")
def get_forecast_localities(year: int, month: int, platform: str, market: str):
    """
    Get available localities for selected platform and market.

    Always includes "-- All Localities --" as first option.
    Uses optimized database query to fetch only distinct Main_LOB values (~10-50 rows).

    Query Parameters:
        year: Selected year
        month: Selected month (1-12)
        platform: Selected platform
        market: Selected market

    Returns:
        [
            {"value": "", "display": "-- All Localities --"},
            {"value": "DOMESTIC", "display": "Domestic"},
            {"value": "OFFSHORE", "display": "Offshore"}
        ]

    Cache: TTL=5 minutes
    """
    # Validate parameters
    if not year or not month or not platform or not market:
        raise HTTPException(status_code=400, detail="Missing required parameters: year, month, platform, market")
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month: must be 1-12")

    year = validate_year(year)

    cache_key = generate_cascade_cache_key("cascade:localities", year=year, month=month, platform=platform, market=market)

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cascade] Returning cached localities response")
        return cached_response

    try:
        # Convert month number to month name
        month_name_str = get_month_name_from_number(month)

        # Get distinct Main_LOB values using database query (efficient!)
        db_manager = core_utils.get_db_manager(ForecastModel, limit=1, skip=0, select_columns=None)
        main_lob_values = db_manager.get_distinct_values("Centene_Capacity_Plan_Main_LOB", month_name_str, year)

        if not main_lob_values:
            raise HTTPException(status_code=404, detail="No localities found for given filters")

        # Extract localities filtered by platform and market (only ~10-50 parsing operations!)
        localities = extract_localities_from_main_lobs(main_lob_values, platform, market)

        # Always include "All Localities" option as first item
        response = [{"value": "", "display": "-- All Localities --"}]

        # Add found localities
        for locality in localities:
            response.append({"value": locality, "display": locality})

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[Cascade] Localities endpoint: {len(response)-1} localities found (+ All option)")
        return response

    except HTTPException:
        raise
    except ValueError as ve:
        logger.error(f"[Cascade] Validation error in localities endpoint: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[Cascade] Error in localities endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve localities")


@router.get("/forecast/worktypes")
def get_forecast_worktypes(
    year: int,
    month: int,
    platform: str,
    market: str,
    locality: Optional[str] = None
):
    """
    Get available worktypes (processes) for selected filters.

    This is the final step in the cascade filter hierarchy.
    Uses TWO optimized database queries (no Python looping through 100k records!):
    1. Get distinct Main_LOB values (~10-50 rows)
    2. Get distinct Case_Type WHERE Main_LOB IN [matching_lobs] (~10-20 rows)

    Query Parameters:
        year: Selected year
        month: Selected month (1-12)
        platform: Selected platform
        market: Selected market
        locality: Selected locality (optional - empty string or None = all localities)

    Returns:
        [
            {"value": "Claims Processing", "display": "Claims Processing"},
            {"value": "Enrollment", "display": "Enrollment"},
            ...
        ]

    Cache: TTL=5 minutes
    """
    # Validate parameters
    if not year or not month or not platform or not market:
        raise HTTPException(status_code=400, detail="Missing required parameters: year, month, platform, market")
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month: must be 1-12")

    year = validate_year(year)

    # Normalize locality (empty string or None both mean "all localities")
    locality_normalized = locality if locality else None

    cache_key = generate_cascade_cache_key(
        "cascade:worktypes",
        year=year,
        month=month,
        platform=platform,
        market=market,
        locality=locality_normalized
    )

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cascade] Returning cached worktypes response")
        return cached_response

    try:
        # Convert month number to month name
        month_name_str = get_month_name_from_number(month)

        db_manager = core_utils.get_db_manager(ForecastModel, limit=1, skip=0, select_columns=None)

        # Step 1: Get distinct Main_LOB values using database query (efficient! ~10-50 rows)
        main_lob_values = db_manager.get_distinct_values("Centene_Capacity_Plan_Main_LOB", month_name_str, year)

        if not main_lob_values:
            raise HTTPException(status_code=404, detail="No worktypes found for given filters")

        # Step 2: Filter Main_LOBs that match platform/market/locality criteria (Python, ~10-50 operations)
        matching_lobs = filter_main_lobs_by_criteria(main_lob_values, platform, market, locality_normalized)

        if not matching_lobs:
            raise HTTPException(status_code=404, detail="No worktypes found for given filters")

        # Step 3: Query database for distinct Case_Type WHERE Main_LOB IN matching_lobs (database query!)
        # This is the KEY optimization - we use filter_values to query only matching Main_LOBs
        worktypes = db_manager.get_distinct_values(
            "Centene_Capacity_Plan_Case_Type",
            month_name_str,
            year,
            filter_values={"Centene_Capacity_Plan_Main_LOB": matching_lobs}
        )

        if not worktypes:
            raise HTTPException(status_code=404, detail="No worktypes found for given filters")

        # Format response (worktypes already sorted by get_distinct_values)
        response = [{"value": wt, "display": wt} for wt in worktypes]

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[Cascade] Worktypes endpoint: {len(response)} worktypes found")
        return response

    except HTTPException:
        raise
    except ValueError as ve:
        logger.error(f"[Cascade] Validation error in worktypes endpoint: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[Cascade] Error in worktypes endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve worktypes")


# Export cache for use in main.py cache invalidation
__all__ = ['router', 'filters_cache']
