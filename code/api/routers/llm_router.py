"""
LLM Tools Router
Provides endpoints optimized for LLM consumption with rich metadata and context.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timezone
import hashlib
import json
import calendar

from code.logics.db import ForecastModel
from code.logics.llm_utils import (
    determine_locality,
    apply_forecast_filters,
    calculate_totals,
    generate_business_insights
)
from code.logics.manager_view import parse_main_lob
from code.logics.month_config_utils import get_specific_config
from code.logics.export_utils import get_forecast_months_list
from code.api.dependencies import get_core_utils, get_logger
from code.cache import data_cache, filters_cache

# Initialize router and dependencies
router = APIRouter()
logger = get_logger(__name__)
core_utils = get_core_utils()


def _generate_cache_key(month: str, year: int, filters: dict) -> str:
    """
    Generate cache key for LLM forecast endpoint.

    Args:
        month: Report month
        year: Report year
        filters: Dictionary of filter parameters

    Returns:
        Cache key string
    """
    # Create a deterministic hash of the filters
    filter_str = json.dumps(filters, sort_keys=True)
    filter_hash = hashlib.md5(filter_str.encode()).hexdigest()[:8]

    return f"llm:forecast:{year}:{month}:{filter_hash}"


def _get_month_label(month_name: str, year: int) -> str:
    """
    Convert month name and year to label format (e.g., "Apr-25").

    Args:
        month_name: Full month name (e.g., "April")
        year: Year (e.g., 2025)

    Returns:
        Month label (e.g., "Apr-25")
    """
    # Map full month names to abbreviations
    month_abbr_map = {
        "January": "Jan",
        "February": "Feb",
        "March": "Mar",
        "April": "Apr",
        "May": "May",
        "June": "Jun",
        "July": "Jul",
        "August": "Aug",
        "September": "Sep",
        "October": "Oct",
        "November": "Nov",
        "December": "Dec"
    }

    abbr = month_abbr_map.get(month_name, month_name[:3])
    year_short = str(year)[2:]  # Last 2 digits

    return f"{abbr}-{year_short}"


def _get_year_for_month(report_month: str, report_year: int, forecast_month: str) -> int:
    """
    Calculate the correct year for a forecast month in a consecutive 6-month sequence.

    When the 6 forecast months wrap from December into January, this function
    determines the correct year to use for config lookups.

    Args:
        report_month: The report month (e.g., "March")
        report_year: The year of the report month (e.g., 2025)
        forecast_month: The forecast month we need to determine the year for (e.g., "January")

    Returns:
        The correct year for the forecast_month

    Examples:
        >>> _get_year_for_month("August", 2024, "August")
        2024
        >>> _get_year_for_month("August", 2024, "December")
        2024
        >>> _get_year_for_month("August", 2024, "January")
        2025  # Wrapped to next year
    """
    # Create mapping from month name to month number (1-12)
    month_to_num = {month: idx for idx, month in enumerate(calendar.month_name) if month}

    # Convert month names to numbers
    report_month_num = month_to_num.get(report_month, 1)
    forecast_month_num = month_to_num.get(forecast_month, 1)

    # If forecast month number < report month number, we've wrapped to next year
    return report_year + 1 if forecast_month_num < report_month_num else report_year


@router.get("/api/llm/forecast/filter-options")
def get_llm_forecast_filter_options(
    month: str,
    year: int
):
    """
    Get available filter options for a specific forecast month and year.

    This endpoint helps LLMs validate user input and discover available filter values
    before querying the main forecast endpoint. Use this to:
    - Validate user-provided filter values (catch spelling mistakes)
    - Show users available options to choose from
    - Auto-correct or suggest alternatives for typos

    Query Parameters:
        month (required): Report month name (e.g., "January", "February")
        year (required): Report year (e.g., 2025)

    Cache: 5 minutes TTL

    Returns:
        Dictionary of available filter values for all filterable fields

    Responses:
        200: Success with filter options
        400: Invalid parameters
        404: No data found for month/year
        500: Internal server error
    """
    try:
        # Step 1: Validate and normalize parameters
        if not month or not year:
            return {
                "success": False,
                "error": "month and year are required parameters",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Normalize month to capitalized full name
        month_normalized = month.strip().capitalize()

        # Validate year
        if year < 1900 or year > 2100:
            return {
                "success": False,
                "error": f"Invalid year: {year} (must be between 1900 and 2100)",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Step 2: Generate cache key and check cache
        cache_key = f"llm:filter-options:{year}:{month_normalized}"
        cached_response = filters_cache.get(cache_key)
        if cached_response is not None:
            logger.debug(f"[LLM Filter Options] Returning cached response for {cache_key}")
            return cached_response

        # Step 3: Query database for forecast records
        db_manager_forecast = core_utils.get_db_manager(
            ForecastModel,
            limit=100000,
            skip=0,
            select_columns=None
        )
        forecast_data = db_manager_forecast.read_db(month_normalized, year)
        raw_records = forecast_data.get("records", [])

        if not raw_records:
            logger.warning(f"[LLM Filter Options] No forecast data found for {month_normalized} {year}")
            return {
                "success": False,
                "error": f"No forecast data found for {month_normalized} {year}",
                "message": f"Please upload forecast data for {month_normalized} {year} before querying filter options",
                "status_code": 404,
                "month": month_normalized,
                "year": year,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Step 4: Get forecast months
        uploaded_file = raw_records[0].get("UploadedFile", "")
        month_labels_list = get_forecast_months_list(month_normalized, year, uploaded_file)

        forecast_month_labels = []
        for i, month_name in enumerate(month_labels_list, start=1):
            if month_name:
                forecast_year = _get_year_for_month(month_normalized, year, month_name)
                month_label = _get_month_label(month_name, forecast_year)
                forecast_month_labels.append(month_label)

        # Step 5: Extract unique values for each filterable field
        platforms = set()
        markets = set()
        localities = set()
        main_lobs = set()
        states = set()
        case_types = set()

        for record in raw_records:
            main_lob = record.get("Centene_Capacity_Plan_Main_LOB", "")
            state = record.get("Centene_Capacity_Plan_State", "")
            case_type = record.get("Centene_Capacity_Plan_Case_Type", "")

            # Add main_lob
            if main_lob:
                main_lobs.add(main_lob)

            # Parse and add platform, market, locality
            if main_lob:
                parsed = parse_main_lob(main_lob)
                platform = parsed.get("platform", "")
                market = parsed.get("market", "")
                locality = determine_locality(main_lob, case_type)

                if platform:
                    platforms.add(platform)
                if market:
                    markets.add(market)
                if locality:
                    localities.add(locality)

            # Add state
            if state:
                states.add(state)

            # Add case_type
            if case_type:
                case_types.add(case_type)

        # Step 6: Build response with sorted lists
        response = {
            "success": True,
            "month": month_normalized,
            "year": year,
            "filter_options": {
                "platforms": sorted(list(platforms)),
                "markets": sorted(list(markets)),
                "localities": sorted(list(localities)),
                "main_lobs": sorted(list(main_lobs)),
                "states": sorted(list(states)),
                "case_types": sorted(list(case_types)),
                "forecast_months": forecast_month_labels
            },
            "record_count": len(raw_records),
            "description": "Available filter values for the specified month and year. Use these to validate user input before querying /api/llm/forecast.",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Step 7: Cache and return (5 minutes cache)
        filters_cache.set(cache_key, response)

        logger.info(
            f"[LLM Filter Options] Returned filter options for {month_normalized} {year}: "
            f"{len(platforms)} platforms, {len(markets)} markets, {len(localities)} localities, "
            f"{len(main_lobs)} LOBs, {len(states)} states, {len(case_types)} case types"
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LLM Filter Options] Error in endpoint: {e}", exc_info=True)
        return {
            "success": False,
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@router.get("/api/llm/forecast")
def get_llm_forecast_data(
    month: str,
    year: int,
    platform: Optional[List[str]] = Query(None),
    market: Optional[List[str]] = Query(None),
    locality: Optional[List[str]] = Query(None),
    main_lob: Optional[List[str]] = Query(None),
    state: Optional[List[str]] = Query(None),
    case_type: Optional[List[str]] = Query(None),
    forecast_months: Optional[List[str]] = Query(None)
):
    """
    Get comprehensive forecast data for LLM consumption.

    Provides forecast data with metadata, configuration details, business insights,
    and calculated metrics optimized for LLM understanding.

    Query Parameters:
        month (required): Report month name (e.g., "January", "February")
        year (required): Report year (e.g., 2025)
        platform: Filter by platforms (Amisys, Facets, Xcelys)
        market: Filter by markets extracted from Main_LOB
        locality: Filter by localities (Domestic, Global)
        main_lob: Filter by specific Main_LOB values (overrides platform/market/locality)
        state: Filter by US state codes or 'N/A'
        case_type: Filter by case type names
        forecast_months: Include only specified months (1-6 months, e.g., ["Apr-25", "May-25"])

    Cache: 60 seconds TTL

    Returns:
        Comprehensive forecast data with metadata, configuration, records, totals, and insights

    Responses:
        200: Success
        400: Invalid parameters
        404: No data found
        500: Internal server error
    """
    try:
        # Step 1: Validate and normalize parameters
        if not month or not year:
            return {
                "success": False,
                "error": "month and year are required parameters",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Normalize month to capitalized full name
        month_normalized = month.strip().capitalize()

        # Validate year
        if year < 1900 or year > 2100:
            return {
                "success": False,
                "error": f"Invalid year: {year} (must be between 1900 and 2100)",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Step 2: Build filters dictionary
        filters = {
            "platform": platform or [],
            "market": market or [],
            "locality": locality or [],
            "main_lob": main_lob or [],
            "state": state or [],
            "case_type": case_type or [],
            "forecast_months": forecast_months or []
        }

        # Step 3: Generate cache key and check cache
        cache_key = _generate_cache_key(month_normalized, year, filters)
        cached_response = data_cache.get(cache_key)
        if cached_response is not None:
            logger.debug(f"[LLM Forecast] Returning cached response for {cache_key}")
            return cached_response

        # Step 4: Query database for forecast records
        db_manager_forecast = core_utils.get_db_manager(
            ForecastModel,
            limit=100000,
            skip=0,
            select_columns=None
        )
        forecast_data = db_manager_forecast.read_db(month_normalized, year)
        raw_records = forecast_data.get("records", [])

        if not raw_records:
            logger.warning(f"[LLM Forecast] No forecast data found for {month_normalized} {year}")
            return {
                "success": False,
                "error": f"No forecast data found for {month_normalized} {year}",
                "message": f"Please upload forecast data for {month_normalized} {year} before querying this endpoint",
                "status_code": 404,
                "month": month_normalized,
                "year": year,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Step 5: Get month mappings (Month1-6 to actual month names)
        # Get the uploaded file name from the first record
        uploaded_file = raw_records[0].get("UploadedFile", "")
        month_labels_list = get_forecast_months_list(month_normalized, year, uploaded_file)

        # Create month mapping dictionary (Month1 -> "Apr-25", etc.)
        months_mapping = {}
        month_labels = []
        for i, month_name in enumerate(month_labels_list, start=1):
            if month_name:
                # Determine the correct year for this forecast month
                forecast_year = _get_year_for_month(month_normalized, year, month_name)
                month_label = _get_month_label(month_name, forecast_year)
                months_mapping[f"Month{i}"] = month_label
                month_labels.append((month_label, month_name, forecast_year))

        # Step 6: Get configurations for each forecast month (Domestic and Global)
        configurations = {}
        for month_label, month_name, forecast_year in month_labels:
            # Get Domestic and Global configs for this specific month
            config_domestic = get_specific_config(month_name, forecast_year, "Domestic")
            config_global = get_specific_config(month_name, forecast_year, "Global")

            month_configs = {}

            if config_domestic:
                month_configs["Domestic"] = {
                    "working_days": config_domestic.get("working_days", 21),
                    "work_hours": config_domestic.get("work_hours", 9),
                    "occupancy": config_domestic.get("occupancy", 0.95),
                    "shrinkage": config_domestic.get("shrinkage", 0.10),
                    "description": "Domestic workforce parameters for FTE and capacity calculations"
                }

            if config_global:
                month_configs["Global"] = {
                    "working_days": config_global.get("working_days", 21),
                    "work_hours": config_global.get("work_hours", 9),
                    "occupancy": config_global.get("occupancy", 0.90),
                    "shrinkage": config_global.get("shrinkage", 0.15),
                    "description": "Global (Offshore) workforce parameters for FTE and capacity calculations"
                }

            if month_configs:
                configurations[month_label] = month_configs

        # Step 7: Apply filters
        filtered_records = apply_forecast_filters(raw_records, filters)

        if not filtered_records:
            # Build helpful message about applied filters
            active_filters = {k: v for k, v in filters.items() if v}
            filter_descriptions = []

            if active_filters.get("platform"):
                filter_descriptions.append(f"platform: {', '.join(active_filters['platform'])}")
            if active_filters.get("market"):
                filter_descriptions.append(f"market: {', '.join(active_filters['market'])}")
            if active_filters.get("locality"):
                filter_descriptions.append(f"locality: {', '.join(active_filters['locality'])}")
            if active_filters.get("main_lob"):
                filter_descriptions.append(f"main_lob: {', '.join(active_filters['main_lob'])}")
            if active_filters.get("state"):
                filter_descriptions.append(f"state: {', '.join(active_filters['state'])}")
            if active_filters.get("case_type"):
                filter_descriptions.append(f"case_type: {', '.join(active_filters['case_type'])}")

            filter_summary = " AND ".join(filter_descriptions) if filter_descriptions else "none"

            logger.info(f"[LLM Forecast] No records match the filter criteria: {filter_summary}")
            return {
                "success": False,
                "error": "No records match the applied filter criteria",
                "message": f"Found {len(raw_records)} total records for {month_normalized} {year}, but none matched your filters. Please check your filter parameters and try again.",
                "status_code": 404,
                "month": month_normalized,
                "year": year,
                "total_records_before_filtering": len(raw_records),
                "filters_applied": active_filters,
                "suggestions": [
                    "Remove some filters to broaden your search",
                    "Check that filter values match exactly (case-insensitive)",
                    "Try querying without filters first to see available values",
                    "Use GET /api/forecast/platforms, /markets, /localities to see valid filter options"
                ],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Step 8: Transform records to response format
        # Extract just the month labels for iteration
        month_labels_only = [ml[0] for ml in month_labels]

        transformed_records = []
        for record in filtered_records:
            main_lob = record.get("Centene_Capacity_Plan_Main_LOB", "")
            state_val = record.get("Centene_Capacity_Plan_State", "")
            case_type_val = record.get("Centene_Capacity_Plan_Case_Type", "")
            case_id_val = record.get("Centene_Capacity_Plan_Call_Type_ID", "")
            target_cph_val = record.get("Centene_Capacity_Plan_Target_CPH", 0.0)

            # Parse Main_LOB
            parsed = parse_main_lob(main_lob)
            platform_val = parsed.get("platform", "")
            market_val = parsed.get("market", "")
            locality_val = determine_locality(main_lob, case_type_val)

            # Build months data
            months_data = {}
            for i, month_label in enumerate(month_labels_only, start=1):
                # Skip if forecast_months filter is applied and this month is not in the list
                if filters.get("forecast_months") and month_label not in filters["forecast_months"]:
                    continue

                forecast_val = record.get(f"Client_Forecast_Month{i}", 0.0) or 0.0
                fte_avail_val = record.get(f"FTE_Avail_Month{i}", 0) or 0
                fte_req_val = record.get(f"FTE_Required_Month{i}", 0) or 0
                capacity_val = record.get(f"Capacity_Month{i}", 0.0) or 0.0
                gap_val = capacity_val - forecast_val

                months_data[month_label] = {
                    "forecast": round(forecast_val, 2),
                    "fte_available": fte_avail_val,
                    "fte_required": fte_req_val,
                    "capacity": round(capacity_val, 2),
                    "gap": round(gap_val, 2)
                }

            transformed_record = {
                "main_lob": main_lob,
                "state": state_val,
                "case_type": case_type_val,
                "case_id": case_id_val,
                "target_cph": target_cph_val,
                "platform": platform_val,
                "market": market_val,
                "locality": locality_val,
                "months": months_data
            }

            transformed_records.append(transformed_record)

        # Step 9: Calculate totals
        # Filter month_labels if forecast_months filter is applied
        if filters.get("forecast_months"):
            month_labels_filtered = [ml for ml in month_labels_only if ml in filters["forecast_months"]]
        else:
            month_labels_filtered = month_labels_only

        totals = calculate_totals(transformed_records, month_labels_filtered)

        # Step 10: Generate business insights
        business_insights = generate_business_insights(totals, month_labels_filtered)

        # Step 11: Build final response
        response = {
            "success": True,
            "metadata": _get_metadata(),
            "configuration": configurations,
            "months": months_mapping,
            "month": month_normalized,
            "year": year,
            "records": transformed_records,
            "totals": totals,
            "business_insights": business_insights,
            "total_records": len(transformed_records),
            "filters_applied": filters,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Step 12: Cache and return
        data_cache.set(cache_key, response)

        logger.info(
            f"[LLM Forecast] Returned {len(transformed_records)} records for "
            f"{month_normalized} {year} with filters: {filters}"
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LLM Forecast] Error in endpoint: {e}", exc_info=True)
        return {
            "success": False,
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@router.get("/api/llm/forecast/available-reports")
def get_available_forecast_reports():
    """
    Get list of available forecast reports for LLM discovery.

    This endpoint helps LLMs discover which month/year combinations have
    forecast data available before querying the main /api/llm/forecast endpoint.

    Use this to:
    - Show users what forecast reports are available
    - Validate date ranges before querying
    - Provide quick overview of data availability

    Returns:
        List of available forecast reports with metadata

    Cache: 5 minutes TTL

    Responses:
        200: Success with list of reports
        500: Internal server error
    """
    try:
        # Step 1: Check cache
        cache_key = "llm:available-reports:v1"
        cached_response = filters_cache.get(cache_key)
        if cached_response is not None:
            logger.debug(f"[LLM Available Reports] Returning cached response")
            return cached_response

        # Step 2: Query database for all validity records with execution metadata
        from code.logics.db import AllocationValidityModel, AllocationExecutionModel

        db_manager = core_utils.get_db_manager(AllocationValidityModel, limit=1000, skip=0, select_columns=None)
        with db_manager.SessionLocal() as session:
            # Join AllocationValidityModel with AllocationExecutionModel
            query = session.query(
                AllocationValidityModel.month,
                AllocationValidityModel.year,
                AllocationValidityModel.allocation_execution_id,
                AllocationValidityModel.is_valid,
                AllocationValidityModel.created_datetime,
                AllocationValidityModel.invalidated_datetime,
                AllocationValidityModel.invalidated_reason,
                AllocationExecutionModel.Status,
                AllocationExecutionModel.ForecastFilename,
                AllocationExecutionModel.RosterFilename,
                AllocationExecutionModel.BenchAllocationCompleted,
                AllocationExecutionModel.StartTime,
                AllocationExecutionModel.RecordsProcessed
            ).join(
                AllocationExecutionModel,
                AllocationValidityModel.allocation_execution_id == AllocationExecutionModel.execution_id
            ).order_by(
                AllocationValidityModel.year.desc(),
                AllocationValidityModel.month.desc()
            )

            results = query.all()

        # Step 3: Build response
        reports = []
        valid_count = 0
        outdated_count = 0

        for result in results:
            (month, year, execution_id, is_valid, created_dt, invalidated_dt,
             invalidated_reason, status, forecast_file, roster_file,
             bench_completed, start_time, records_count) = result

            # Format as "YYYY-MM"
            month_abbr = _get_month_label(month, year).split('-')[0]  # Get just the month part
            value = f"{year}-{month_abbr}"
            display = f"{month} {year}"

            # Determine data freshness
            if is_valid:
                data_freshness = "current"
                valid_count += 1
            else:
                data_freshness = "outdated"
                outdated_count += 1

            # Build report object
            report = {
                "value": value,
                "display": display,
                "month": month,
                "year": year,
                "is_valid": is_valid,
                "status": status,
                "allocation_execution_id": execution_id,
                "forecast_file": forecast_file,
                "roster_file": roster_file,
                "created_at": created_dt.isoformat() if created_dt else None,
                "has_bench_allocation": bench_completed,
                "data_freshness": data_freshness
            }

            # Add optional fields if applicable
            if records_count is not None:
                report["records_count"] = records_count

            if invalidated_dt:
                report["invalidated_at"] = invalidated_dt.isoformat()

            if invalidated_reason:
                report["invalidated_reason"] = invalidated_reason

            reports.append(report)

        # Step 4: Build final response
        response = {
            "success": True,
            "reports": reports,
            "total_reports": len(reports),
            "valid_reports": valid_count,
            "outdated_reports": outdated_count,
            "description": "List of available forecast reports. Use 'value' field to query /api/llm/forecast?month={month}&year={year}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Step 5: Cache and return
        filters_cache.set(cache_key, response)

        logger.info(
            f"[LLM Available Reports] Returned {len(reports)} reports "
            f"({valid_count} valid, {outdated_count} outdated)"
        )

        return response

    except Exception as e:
        logger.error(f"[LLM Available Reports] Error in endpoint: {e}", exc_info=True)
        return {
            "success": False,
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


def _get_metadata() -> dict:
    """
    Get metadata section for response.

    Returns:
        Dictionary with field descriptions, units, and formulas
    """
    return {
        "description": "Forecast data for capacity planning and resource allocation",
        "field_descriptions": {
            "forecast": "Client forecast demand (number of cases expected)",
            "fte_available": "Full-Time Equivalents available (number of resources)",
            "fte_required": "Full-Time Equivalents required to meet forecast demand",
            "capacity": "Total processing capacity (number of cases that can be handled)",
            "gap": "Capacity gap (capacity - forecast). Positive = overstaffed, negative = understaffed",
            "target_cph": "Target Cases Per Hour (productivity metric)",
            "platform": "Technology platform (Amisys, Facets, or Xcelys)",
            "market": "Insurance market segment (e.g., Medicaid, Medicare)",
            "locality": "Workforce location type (Domestic or Global/Offshore)",
            "main_lob": "Line of Business - combination of platform, market, and locality",
            "state": "US state code (e.g., CA, TX) or 'N/A' for non-state-specific work",
            "case_type": "Type of work or process (e.g., Claims Processing, Enrollment)",
            "case_id": "Unique identifier for the work type"
        },
        "units": {
            "forecast": "cases",
            "fte_available": "FTEs (Full-Time Equivalents)",
            "fte_required": "FTEs (Full-Time Equivalents)",
            "capacity": "cases",
            "gap": "cases",
            "target_cph": "cases per hour"
        },
        "formulas": {
            "fte_required": "ceil(forecast / (working_days × work_hours × (1 - shrinkage) × target_cph))",
            "capacity": "fte_available × working_days × work_hours × (1 - shrinkage) × target_cph",
            "gap": "capacity - forecast"
        }
    }


# Export router
__all__ = ['router']
