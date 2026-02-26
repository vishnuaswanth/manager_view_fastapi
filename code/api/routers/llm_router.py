"""
LLM Tools Router
Provides endpoints optimized for LLM consumption with rich metadata and context.
"""

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import hashlib
import json
import calendar

from code.logics.db import (
    ForecastModel,
    ProdTeamRosterModel,
    FTEAllocationMappingModel,
    AllocationValidityModel
)
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
    request: Request,
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

        # Merge bracket-notation params (e.g. state[]=TX) with standard params (e.g. state=TX)
        # Some clients (JS frameworks, curl) send array params as key[]=value instead of key=value
        raw_params = request.query_params
        platform = list(set((platform or []) + raw_params.getlist("platform[]")))
        market = list(set((market or []) + raw_params.getlist("market[]")))
        locality = list(set((locality or []) + raw_params.getlist("locality[]")))
        main_lob = list(set((main_lob or []) + raw_params.getlist("main_lob[]")))
        state = list(set((state or []) + raw_params.getlist("state[]")))
        case_type = list(set((case_type or []) + raw_params.getlist("case_type[]")))
        forecast_months = list(set((forecast_months or []) + raw_params.getlist("forecast_months[]")))

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
            main_lob_val = record.get("Centene_Capacity_Plan_Main_LOB", "")
            state_val = record.get("Centene_Capacity_Plan_State", "")
            case_type_val = record.get("Centene_Capacity_Plan_Case_Type", "")
            case_id_val = record.get("Centene_Capacity_Plan_Call_Type_ID", "")
            target_cph_val = record.get("Centene_Capacity_Plan_Target_CPH", 0.0)

            # Parse Main_LOB
            parsed = parse_main_lob(main_lob_val)
            platform_val = parsed.get("platform", "")
            market_val = parsed.get("market", "")
            locality_val = determine_locality(main_lob_val, case_type_val)

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
                "id": record.get("id"),
                "main_lob": main_lob_val,
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
            ).filter(
                AllocationValidityModel.is_valid == True
            ).order_by(
                AllocationValidityModel.year.desc(),
                AllocationValidityModel.month.desc()
            )

            results = query.all()

        # Step 3: Build response (only valid reports since we filtered in query)
        reports = []
        valid_count = len(results)  # All results are valid due to filter

        for result in results:
            (month, year, execution_id, is_valid, created_dt, _,
             _, status, forecast_file, roster_file,
             bench_completed, _, records_count) = result

            # Format as "YYYY-MM"
            month_abbr = _get_month_label(month, year).split('-')[0]  # Get just the month part
            value = f"{year}-{month_abbr}"
            display = f"{month} {year}"

            # Build report object (all are current since we filtered for is_valid=True)
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
                "data_freshness": "current"
            }

            # Add optional fields if applicable
            if records_count is not None:
                report["records_count"] = records_count

            reports.append(report)

        # Step 4: Build final response
        response = {
            "success": True,
            "reports": reports,
            "total_reports": len(reports),
            "valid_reports": valid_count,
            "description": "List of current/valid forecast reports. Use 'value' field to query /api/llm/forecast?month={month}&year={year}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Step 5: Cache and return
        filters_cache.set(cache_key, response)

        logger.info(
            f"[LLM Available Reports] Returned {len(reports)} current/valid reports"
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


@router.get("/api/llm/fte-allocations")
def get_fte_allocations(
    report_month: str,
    report_year: int,
    main_lob: str,
    case_type: str,
    state: str,
    forecast_month: Optional[str] = None
):
    """
    Get FTE allocation details for a specific forecast record.

    This endpoint allows LLMs to query which FTEs (resources) are allocated
    to a specific forecast record, grouped by forecast month.

    Args:
        report_month: Report month (e.g., "March")
        report_year: Report year (e.g., 2025)
        main_lob: Main LOB filter (e.g., "Amisys Medicaid Domestic")
        case_type: Case type filter (e.g., "Claims Processing")
        state: State filter (e.g., "LA", "N/A")
        forecast_month: Optional forecast month filter in "Apr-25" format

    Returns:
        FTE allocation details grouped by forecast month

    Example:
        GET /api/llm/fte-allocations?report_month=March&report_year=2025&main_lob=Amisys%20Medicaid%20Domestic&case_type=Claims%20Processing&state=LA

    Response includes:
        - total_fte_count: Total FTEs allocated across all months
        - allocation_type_summary: Count of primary vs bench allocations
        - fte_by_month: FTE details grouped by forecast month (e.g., "Apr-25")
        - forecast_months: List of available forecast months

    Cache: 60 seconds TTL
    """
    try:
        # Validate required parameters
        if not report_month or not report_month.strip():
            return {
                "success": False,
                "error": "report_month is required",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        if not main_lob or not main_lob.strip():
            return {
                "success": False,
                "error": "main_lob is required",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        if not case_type or not case_type.strip():
            return {
                "success": False,
                "error": "case_type is required",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        if not state or not state.strip():
            return {
                "success": False,
                "error": "state is required",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Validate year range
        current_year = datetime.now().year
        if report_year < 2020 or report_year > current_year + 5:
            return {
                "success": False,
                "error": f"report_year must be between 2020 and {current_year + 5}",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Generate cache key
        cache_key = f"llm:fte-allocations:{report_month}:{report_year}:{main_lob}:{state}:{case_type}:{forecast_month or 'all'}"
        cached_response = data_cache.get(cache_key)
        if cached_response is not None:
            logger.debug(f"[LLM FTE Allocations] Returning cached response")
            return cached_response

        # Query FTE mappings
        from code.logics.fte_allocation_mapping import get_fte_mappings

        result = get_fte_mappings(
            report_month=report_month.strip(),
            report_year=report_year,
            main_lob=main_lob.strip(),
            state=state.strip(),
            case_type=case_type.strip(),
            forecast_month_label=forecast_month.strip() if forecast_month else None,
            core_utils=core_utils
        )

        if not result.get('success'):
            return {
                "success": False,
                "error": result.get('error', 'No FTE allocations found'),
                "status_code": 404,
                "report_month": report_month,
                "report_year": report_year,
                "main_lob": main_lob,
                "case_type": case_type,
                "state": state,
                "forecast_month_filter": forecast_month,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Build successful response
        response = {
            "success": True,
            "report_month": report_month,
            "report_year": report_year,
            "main_lob": main_lob,
            "case_type": case_type,
            "state": state,
            "forecast_month_filter": forecast_month,
            "allocation_execution_id": result.get('allocation_execution_id'),
            "total_fte_count": result.get('total_fte_count', 0),
            "allocation_type_summary": result.get('allocation_type_summary', {}),
            "fte_by_month": result.get('fte_by_month', {}),
            "forecast_months": result.get('forecast_months', []),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Cache the response
        data_cache.set(cache_key, response)

        logger.info(
            f"[LLM FTE Allocations] Returned {result.get('total_fte_count', 0)} FTEs "
            f"for {main_lob} | {state} | {case_type} ({report_month} {report_year})"
        )

        return response

    except Exception as e:
        logger.error(f"[LLM FTE Allocations] Error in endpoint: {e}", exc_info=True)
        return {
            "success": False,
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@router.get("/api/llm/available-ftes")
def get_available_ftes(
    report_month: str,
    report_year: int,
    main_lob: str,
    case_type: str,
    state: str,
    forecast_month: Optional[str] = None
):
    """
    Get unallocated (available) FTEs for allocation based on filter criteria.

    This endpoint returns FTEs from the roster that have NOT been allocated
    to the specified forecast record, with per-month breakdown and full roster details.

    Args:
        report_month: Report month (e.g., "March")
        report_year: Report year (e.g., 2025)
        main_lob: Main LOB filter (e.g., "Amisys Medicaid Domestic")
        case_type: Case type to match NewWorkType
        state: State filter (e.g., "LA", "N/A")
        forecast_month: Optional specific forecast month filter (e.g., "Apr-25")

    Returns:
        Available FTE details grouped by forecast month with full roster info

    Example:
        GET /api/llm/available-ftes?report_month=March&report_year=2025&main_lob=Amisys%20Medicaid%20Domestic&case_type=FTC-Basic&state=LA

    Cache: 60 seconds TTL
    """
    try:
        # Validate required parameters
        if not report_month or not report_month.strip():
            return {
                "success": False,
                "error": "report_month is required",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        if not main_lob or not main_lob.strip():
            return {
                "success": False,
                "error": "main_lob is required",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        if not case_type or not case_type.strip():
            return {
                "success": False,
                "error": "case_type is required",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        if not state or not state.strip():
            return {
                "success": False,
                "error": "state is required",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Validate year range
        current_year = datetime.now().year
        if report_year < 2020 or report_year > current_year + 5:
            return {
                "success": False,
                "error": f"report_year must be between 2020 and {current_year + 5}",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Normalize inputs
        report_month = report_month.strip().capitalize()
        main_lob = main_lob.strip()
        case_type = case_type.strip()
        state = state.strip()
        forecast_month_filter = forecast_month.strip() if forecast_month else None

        # Generate cache key
        cache_key = f"llm:available-ftes:{report_month}:{report_year}:{main_lob}:{state}:{case_type}:{forecast_month_filter or 'all'}"
        cached_response = data_cache.get(cache_key)
        if cached_response is not None:
            logger.debug(f"[LLM Available FTEs] Returning cached response")
            return cached_response

        # Step 1: Get valid allocation execution ID
        db_manager = core_utils.get_db_manager(
            AllocationValidityModel,
            limit=1,
            skip=0,
            select_columns=None
        )

        with db_manager.SessionLocal() as session:
            validity_record = session.query(AllocationValidityModel).filter(
                AllocationValidityModel.month == report_month,
                AllocationValidityModel.year == report_year,
                AllocationValidityModel.is_valid == True
            ).first()

            if not validity_record:
                return {
                    "success": False,
                    "error": f"No valid allocation found for {report_month} {report_year}",
                    "message": "Please run allocation first before querying available FTEs",
                    "status_code": 404,
                    "report_month": report_month,
                    "report_year": report_year,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            allocation_execution_id = validity_record.allocation_execution_id

        # Step 2: Parse main_lob to get platform and locality
        parsed = parse_main_lob(main_lob)
        platform = parsed.get("platform", "")
        locality = determine_locality(main_lob, case_type)

        if not platform:
            return {
                "success": False,
                "error": f"Unable to determine platform from main_lob: {main_lob}",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Step 3: Get forecast months from ForecastMonthsModel
        # First get uploaded file name from forecast data
        db_manager_forecast = core_utils.get_db_manager(
            ForecastModel,
            limit=1,
            skip=0,
            select_columns=None
        )
        forecast_data = db_manager_forecast.read_db(report_month, report_year)
        raw_records = forecast_data.get("records", [])

        if not raw_records:
            return {
                "success": False,
                "error": f"No forecast data found for {report_month} {report_year}",
                "status_code": 404,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        uploaded_file = raw_records[0].get("UploadedFile", "")
        month_labels_list = get_forecast_months_list(report_month, report_year, uploaded_file)

        # Build forecast months mapping
        forecast_months = []
        for i, month_name in enumerate(month_labels_list, start=1):
            if month_name:
                forecast_year = _get_year_for_month(report_month, report_year, month_name)
                month_label = _get_month_label(month_name, forecast_year)
                forecast_months.append({
                    "label": month_label,
                    "month_name": month_name,
                    "year": forecast_year,
                    "index": i
                })

        # Step 4: Query roster - filter by platform, locality, case_type (via NewWorkType)
        # Handle both "Offshore" and "Global" in the data
        location_values = ["Domestic"] if locality == "Domestic" else ["Global", "Offshore"]

        db_manager_roster = core_utils.get_db_manager(
            ProdTeamRosterModel,
            limit=100000,
            skip=0,
            select_columns=None
        )

        from sqlalchemy import func, or_

        with db_manager_roster.SessionLocal() as session:
            # Build roster query with filters
            roster_query = session.query(ProdTeamRosterModel).filter(
                ProdTeamRosterModel.Month == report_month,
                ProdTeamRosterModel.Year == report_year,
                func.lower(ProdTeamRosterModel.PrimaryPlatform) == platform.lower(),
                or_(*[func.lower(ProdTeamRosterModel.Location) == loc.lower() for loc in location_values])
            )

            # Filter by case_type - match against NewWorkType (case-insensitive contains)
            roster_query = roster_query.filter(
                func.lower(ProdTeamRosterModel.NewWorkType).contains(case_type.lower())
            )

            # Filter by state - handle "N/A" case
            if state.upper() != "N/A":
                # For non-N/A states, check if state is in the roster's State field
                # The roster State field might be a single state or pipe-delimited
                roster_query = roster_query.filter(
                    or_(
                        func.lower(ProdTeamRosterModel.State) == state.lower(),
                        ProdTeamRosterModel.State.contains(state)
                    )
                )

            roster_records = roster_query.all()

        if not roster_records:
            response = {
                "success": True,
                "report_month": report_month,
                "report_year": report_year,
                "main_lob": main_lob,
                "case_type": case_type,
                "state": state,
                "platform": platform,
                "locality": locality,
                "allocation_execution_id": allocation_execution_id,
                "total_available_count": 0,
                "available_by_month": {},
                "forecast_months": [fm["label"] for fm in forecast_months],
                "message": "No roster records match the filter criteria",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            data_cache.set(cache_key, response)
            return response

        # Step 5: Get allocated FTEs from FTEAllocationMappingModel
        db_manager_mapping = core_utils.get_db_manager(
            FTEAllocationMappingModel,
            limit=100000,
            skip=0,
            select_columns=None
        )

        with db_manager_mapping.SessionLocal() as session:
            # Query all allocated FTEs for this allocation execution
            allocated_query = session.query(
                FTEAllocationMappingModel.cn,
                FTEAllocationMappingModel.forecast_month_label
            ).filter(
                FTEAllocationMappingModel.allocation_execution_id == allocation_execution_id
            )

            allocated_records = allocated_query.all()

        # Build a set of (cn, month_label) tuples for allocated FTEs
        allocated_by_month = {}
        for cn, month_label in allocated_records:
            if month_label not in allocated_by_month:
                allocated_by_month[month_label] = set()
            allocated_by_month[month_label].add(cn)

        # Step 6: Calculate available FTEs for each forecast month
        available_by_month = {}
        total_available_count = 0

        for fm in forecast_months:
            month_label = fm["label"]

            # Skip if forecast_month filter is applied and doesn't match
            if forecast_month_filter and month_label != forecast_month_filter:
                continue

            # Get CNs allocated for this month
            allocated_cns = allocated_by_month.get(month_label, set())

            # Filter roster to get available FTEs (not in allocated list)
            available_ftes = []
            for roster in roster_records:
                if roster.CN not in allocated_cns:
                    fte_data = {
                        "first_name": roster.FirstName or "",
                        "last_name": roster.LastName or "",
                        "cn": roster.CN or "",
                        "opid": roster.OPID or "",
                        "location": roster.Location or "",
                        "zip_code": roster.ZIPCode or "",
                        "city": roster.City or "",
                        "beeline_title": roster.BeelineTitle or "",
                        "status": roster.Status or "",
                        "primary_platform": roster.PrimaryPlatform or "",
                        "primary_market": roster.PrimaryMarket or "",
                        "worktype": roster.Worktype or "",
                        "lob": roster.LOB or "",
                        "supervisor_full_name": roster.SupervisorFullName or "",
                        "supervisor_cn_no": roster.SupervisorCNNo or "",
                        "user_status": roster.UserStatus or "",
                        "part_of_production": roster.PartofProduction or "",
                        "production_percentage": roster.ProductionPercentage,
                        "new_work_type": roster.NewWorkType or "",
                        "state": roster.State or "",
                        "centene_mail_id": roster.CenteneMailId or "",
                        "ntt_mail_id": roster.NTTMailID or ""
                    }
                    available_ftes.append(fte_data)

            available_by_month[month_label] = {
                "available_count": len(available_ftes),
                "ftes": available_ftes
            }
            total_available_count += len(available_ftes)

        # Step 7: Build and cache response
        response = {
            "success": True,
            "report_month": report_month,
            "report_year": report_year,
            "main_lob": main_lob,
            "case_type": case_type,
            "state": state,
            "platform": platform,
            "locality": locality,
            "allocation_execution_id": allocation_execution_id,
            "total_available_count": total_available_count,
            "available_by_month": available_by_month,
            "forecast_months": [fm["label"] for fm in forecast_months],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        data_cache.set(cache_key, response)

        logger.info(
            f"[LLM Available FTEs] Returned {total_available_count} available FTEs "
            f"for {main_lob} | {state} | {case_type} ({report_month} {report_year})"
        )

        return response

    except Exception as e:
        logger.error(f"[LLM Available FTEs] Error in endpoint: {e}", exc_info=True)
        return {
            "success": False,
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


# Request model for target CPH update
class UpdateTargetCPHRequest(BaseModel):
    """Request model for updating target CPH."""
    report_month: str = Field(
        ...,
        min_length=1,
        description="Report month (e.g., 'March')"
    )
    report_year: int = Field(
        ...,
        ge=2020,
        description="Report year (e.g., 2025)"
    )
    main_lob: str = Field(
        ...,
        min_length=1,
        description="Main LOB (e.g., 'Amisys Medicaid Domestic')"
    )
    state: str = Field(
        ...,
        min_length=1,
        description="State code (e.g., 'LA', 'N/A')"
    )
    case_type: str = Field(
        ...,
        min_length=1,
        description="Case type (e.g., 'Claims Processing')"
    )
    new_target_cph: int = Field(
        ...,
        ge=0,
        le=200,
        description="New target CPH value (must be >= 0 and <= 200)"
    )
    user_notes: Optional[str] = Field(
        default=None,
        description="Optional description of why CPH changed"
    )

    class Config:
        extra = "forbid"


@router.post("/api/llm/forecast/update-target-cph")
def update_forecast_target_cph(request: UpdateTargetCPHRequest):
    """
    Update target_CPH for forecast records matching the criteria.

    This endpoint is optimized for LLM consumption. It updates the target_CPH
    for all forecast records matching (main_lob, state, case_type, month, year)
    and automatically recalculates FTE_Required and Capacity for all 6 forecast months.

    Request Body:
        report_month (required): Report month name (e.g., "March")
        report_year (required): Report year (e.g., 2025)
        main_lob (required): Main LOB (e.g., "Amisys Medicaid Domestic")
        state (required): State code (e.g., "LA", "N/A")
        case_type (required): Case type (e.g., "Claims Processing")
        new_target_cph (required): New target CPH value (1-200)
        user_notes (optional): Description of why CPH changed

    Formulas used:
        FTE_Required = ceil(forecast / (working_days × work_hours × (1-shrinkage) × target_CPH))
        Capacity = fte_avail × working_days × work_hours × (1-shrinkage) × target_CPH

    Returns:
        Success response with:
            - old_target_cph: Previous target CPH value
            - new_target_cph: New target CPH value
            - records_updated: Count of forecast rows updated
            - history_log_id: UUID of the history log entry
            - recalculated_totals: Old/new FTE and Capacity by month

        Error response with:
            - error: Error message
            - status_code: HTTP status code
            - recommendation: Suggested action

    Example:
        POST /api/llm/forecast/update-target-cph
        {
            "report_month": "March",
            "report_year": 2025,
            "main_lob": "Amisys Medicaid Domestic",
            "state": "LA",
            "case_type": "Claims Processing",
            "new_target_cph": 50,
            "user_notes": "Adjusted based on new productivity analysis"
        }

    Response:
        {
            "success": true,
            "message": "Target CPH updated successfully",
            "old_target_cph": 45,
            "new_target_cph": 50,
            "records_updated": 3,
            "history_log_id": "uuid-string",
            "recalculated_totals": {
                "Apr-25": {
                    "fte_required": {"old": 36, "new": 30, "change": -6},
                    "capacity": {"old": 13500, "new": 15000, "change": 1500}
                },
                ...
            }
        }
    """
    try:
        # Validate year range
        current_year = datetime.now().year
        if request.report_year > current_year + 5:
            return {
                "success": False,
                "error": f"report_year must be between 2020 and {current_year + 5}",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Normalize month
        report_month = request.report_month.strip().capitalize()

        # Validate month name
        valid_months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]
        if report_month not in valid_months:
            return {
                "success": False,
                "error": f"Invalid month: {request.report_month}. Must be a full month name.",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Import the updater function
        from code.logics.llm_forecast_updater import update_single_record_target_cph

        # Call the update function
        result = update_single_record_target_cph(
            report_month=report_month,
            report_year=request.report_year,
            main_lob=request.main_lob.strip(),
            state=request.state.strip(),
            case_type=request.case_type.strip(),
            new_target_cph=request.new_target_cph,
            user_notes=request.user_notes,
            core_utils=core_utils
        )

        if result.get("success"):
            logger.info(
                f"[LLM Update Target CPH] Successfully updated CPH for "
                f"{request.main_lob} | {request.state} | {request.case_type} "
                f"({report_month} {request.report_year}): "
                f"{result.get('old_target_cph')} -> {result.get('new_target_cph')}"
            )
        else:
            logger.warning(
                f"[LLM Update Target CPH] Failed to update CPH: {result.get('error')}"
            )

        return result

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"[LLM Update Target CPH] Validation error: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "status_code": 400,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"[LLM Update Target CPH] Error in endpoint: {e}", exc_info=True)
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
