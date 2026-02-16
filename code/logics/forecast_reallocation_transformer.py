"""
Forecast Reallocation transformation functions.

Handles data loading, preview calculations, and forecast updates for the
Forecast Reallocation feature (Edit View Sections 10-13).
"""

import logging
from typing import Dict, List, Optional, Tuple
from code.logics.db import ForecastModel
from code.logics.core_utils import CoreUtils
from code.logics.edit_view_utils import (
    get_months_dict,
    get_forecast_column_name
)
from code.logics.capacity_calculations import calculate_fte_required, calculate_capacity
from code.logics.cph_update_transformer import (
    get_month_config_for_forecast,
    _get_work_type_from_main_lob
)
from code.logics.bench_allocation_transformer import (
    PreviewResponse,
    ModifiedRecordResponse,
    MonthDataResponse,
    SummaryResponse
)

logger = logging.getLogger(__name__)


def get_reallocation_filters(
    month: str,
    year: int,
    core_utils: CoreUtils
) -> Dict[str, List[str]]:
    """
    Get filter options for forecast reallocation.

    DEPRECATED: This endpoint is no longer used by the frontend UI.
    Filter options are now extracted client-side from loaded data.
    Kept for backward compatibility.

    Args:
        month: Report month name (e.g., "April")
        year: Report year (e.g., 2025)
        core_utils: CoreUtils instance for database access

    Returns:
        Dictionary with main_lobs, states, and case_types lists

    Raises:
        ValueError: If no forecast data found for month/year
    """
    db_manager = core_utils.get_db_manager(
        ForecastModel,
        limit=10000,
        skip=0,
        select_columns=None
    )

    # Get distinct values from database
    main_lobs = db_manager.get_distinct_values(
        "Centene_Capacity_Plan_Main_LOB",
        month=month,
        year=year
    )
    states = db_manager.get_distinct_values(
        "Centene_Capacity_Plan_State",
        month=month,
        year=year
    )
    case_types = db_manager.get_distinct_values(
        "Centene_Capacity_Plan_Case_Type",
        month=month,
        year=year
    )

    if not main_lobs and not states and not case_types:
        raise ValueError(f"No forecast data found for {month} {year}")

    logger.info(
        f"Retrieved reallocation filters for {month} {year}: "
        f"{len(main_lobs)} LOBs, {len(states)} states, {len(case_types)} case types"
    )

    return {
        "main_lobs": main_lobs,
        "states": states,
        "case_types": case_types
    }


def get_reallocation_data(
    month: str,
    year: int,
    core_utils: CoreUtils,
    main_lobs: Optional[List[str]] = None,
    states: Optional[List[str]] = None,
    case_types: Optional[List[str]] = None
) -> Tuple[Dict[str, str], List[Dict], int]:
    """
    Load forecast records with 6-month data for reallocation.

    Args:
        month: Report month name (e.g., "April")
        year: Report year (e.g., 2025)
        core_utils: CoreUtils instance for database access
        main_lobs: Optional list of Main LOB values to filter
        states: Optional list of State codes to filter
        case_types: Optional list of Case Type values to filter

    Returns:
        Tuple of (months_dict, data_records, total_count)

    Raises:
        ValueError: If no forecast data found for month/year
    """
    # Get month mappings
    months_dict = get_months_dict(month, year, core_utils)

    db_manager = core_utils.get_db_manager(
        ForecastModel,
        limit=10000,
        skip=0,
        select_columns=None
    )

    with db_manager.SessionLocal() as session:
        # Build query with optional filters
        query = session.query(ForecastModel).filter(
            ForecastModel.Month == month,
            ForecastModel.Year == year
        )

        # Apply optional filters
        if main_lobs:
            query = query.filter(ForecastModel.Centene_Capacity_Plan_Main_LOB.in_(main_lobs))
        if states:
            query = query.filter(ForecastModel.Centene_Capacity_Plan_State.in_(states))
        if case_types:
            query = query.filter(ForecastModel.Centene_Capacity_Plan_Case_Type.in_(case_types))

        records = query.all()

        if not records:
            raise ValueError(f"No forecast data found for {month} {year}")

        # Transform to API format
        data_records = []
        for record in records:
            # Build month data
            month_data = {}
            for month_idx, month_label in months_dict.items():
                suffix = month_idx.replace('month', '')

                forecast = getattr(
                    record,
                    get_forecast_column_name('forecast', suffix),
                    0
                ) or 0
                fte_req = getattr(
                    record,
                    get_forecast_column_name('fte_req', suffix),
                    0
                ) or 0
                fte_avail = getattr(
                    record,
                    get_forecast_column_name('fte_avail', suffix),
                    0
                ) or 0
                capacity = getattr(
                    record,
                    get_forecast_column_name('capacity', suffix),
                    0
                ) or 0

                month_data[month_label] = {
                    "forecast": int(forecast),
                    "fte_req": int(fte_req),
                    "fte_avail": int(fte_avail),
                    "capacity": int(capacity)
                }

            data_record = {
                "case_id": record.Centene_Capacity_Plan_Call_Type_ID,
                "main_lob": record.Centene_Capacity_Plan_Main_LOB,
                "state": record.Centene_Capacity_Plan_State,
                "case_type": record.Centene_Capacity_Plan_Case_Type,
                "target_cph": float(record.Centene_Capacity_Plan_Target_CPH or 0),
                "months": month_data
            }
            data_records.append(data_record)

        total = len(data_records)
        logger.info(f"Retrieved {total} reallocation records for {month} {year}")

        return months_dict, data_records, total


def calculate_reallocation_preview(
    month: str,
    year: int,
    modified_records: List[Dict],
    core_utils: CoreUtils
) -> PreviewResponse:
    """
    Calculate preview for forecast reallocation with recalculated FTE Required and Capacity.

    Takes user-edited Target CPH and FTE Available values and recalculates:
    - FTE Required: Based on forecast / (config * new CPH)
    - Capacity: Based on new FTE Available * config * new CPH

    Args:
        month: Report month name (e.g., "April")
        year: Report year (e.g., 2025)
        modified_records: List of records with user modifications:
            [{"case_id": "...", "main_lob": "...", "state": "...", "case_type": "...",
              "target_cph": 105.0, "target_cph_change": 5.0,
              "modified_fields": ["target_cph", "Apr-25.fte_avail"],
              "months": {"Apr-25": {"forecast": 12500, "fte_avail": 125, "fte_avail_change": 5, ...}}}]
        core_utils: CoreUtils instance

    Returns:
        PreviewResponse: Validated Pydantic model with recalculated values

    Raises:
        ValueError: If no modified records provided or validation fails
    """
    if not modified_records:
        raise ValueError("No records provided for preview")

    # Get month mappings
    months_dict = get_months_dict(month, year, core_utils)

    # Cache month configs by work_type to avoid redundant DB calls
    month_config_cache: Dict[str, Dict] = {}

    def get_cached_month_config(work_type: str) -> Dict:
        """Get month config from cache or fetch from DB."""
        if work_type not in month_config_cache:
            month_config_cache[work_type] = get_month_config_for_forecast(
                month, year, core_utils, work_type
            )
        return month_config_cache[work_type]

    # Get original values from database for comparison
    db_manager = core_utils.get_db_manager(
        ForecastModel,
        limit=10000,
        skip=0,
        select_columns=None
    )

    # Build case_id to original record lookup
    case_ids = [r.get('case_id') for r in modified_records if r.get('case_id')]

    with db_manager.SessionLocal() as session:
        original_records = session.query(ForecastModel).filter(
            ForecastModel.Month == month,
            ForecastModel.Year == year,
            ForecastModel.Centene_Capacity_Plan_Call_Type_ID.in_(case_ids)
        ).all()

        original_lookup = {
            r.Centene_Capacity_Plan_Call_Type_ID: r for r in original_records
        }

    result_records = []
    total_fte_change = 0
    total_capacity_change = 0

    for input_record in modified_records:
        case_id = input_record.get('case_id')
        if not case_id:
            raise ValueError("Record missing case_id")

        original = original_lookup.get(case_id)
        if not original:
            logger.warning(f"Original record not found for case_id {case_id}, skipping")
            continue

        # Get work type for config lookup
        work_type = _get_work_type_from_main_lob(original.Centene_Capacity_Plan_Main_LOB)
        month_config = get_cached_month_config(work_type)

        # Get new target CPH
        new_target_cph = float(input_record.get('target_cph', original.Centene_Capacity_Plan_Target_CPH or 0))
        original_target_cph = float(original.Centene_Capacity_Plan_Target_CPH or 0)
        target_cph_change = new_target_cph - original_target_cph

        # Track modified fields (will include all fields for months with changes)
        modified_fields = []
        if target_cph_change != 0:
            modified_fields.append("target_cph")

        input_months = input_record.get('months', {})
        month_data = {}

        # Calculate for each month
        for month_idx, month_label in months_dict.items():
            suffix = month_idx.replace('month', '')
            config = month_config[month_idx]

            # Get original values
            orig_forecast = int(getattr(
                original,
                get_forecast_column_name('forecast', suffix),
                0
            ) or 0)
            orig_fte_req = int(getattr(
                original,
                get_forecast_column_name('fte_req', suffix),
                0
            ) or 0)
            orig_fte_avail = int(getattr(
                original,
                get_forecast_column_name('fte_avail', suffix),
                0
            ) or 0)
            orig_capacity = int(getattr(
                original,
                get_forecast_column_name('capacity', suffix),
                0
            ) or 0)

            # Get user-modified FTE Available (from input or use original)
            input_month_data = input_months.get(month_label, {})
            new_fte_avail = int(input_month_data.get('fte_avail', orig_fte_avail))

            # Recalculate FTE Required based on new CPH
            new_fte_req = calculate_fte_required(orig_forecast, config, new_target_cph)

            # Recalculate Capacity based on new FTE Available and new CPH
            new_capacity = calculate_capacity(new_fte_avail, config, new_target_cph)

            # Calculate deltas
            fte_req_change = new_fte_req - orig_fte_req
            fte_avail_change = new_fte_avail - orig_fte_avail
            capacity_change = int(new_capacity) - orig_capacity

            # Check if any field changed for this month
            has_changes = (
                fte_req_change != 0 or
                fte_avail_change != 0 or
                capacity_change != 0
            )

            if has_changes:
                # Option 1: Track ALL 4 fields for months with any change
                fields_to_add = [
                    f"{month_label}.forecast",
                    f"{month_label}.fte_req",
                    f"{month_label}.fte_avail",
                    f"{month_label}.capacity"
                ]
                for field in fields_to_add:
                    if field not in modified_fields:
                        modified_fields.append(field)

                total_fte_change += abs(fte_avail_change)
                total_capacity_change += abs(capacity_change)

            month_data[month_label] = MonthDataResponse(
                forecast=orig_forecast,
                fte_req=new_fte_req,
                fte_avail=new_fte_avail,
                capacity=int(new_capacity),
                forecast_change=0,  # Forecast doesn't change in reallocation
                fte_req_change=fte_req_change,
                fte_avail_change=fte_avail_change,
                capacity_change=capacity_change
            )

        # Only include records with changes
        if modified_fields:
            record_response = ModifiedRecordResponse(
                main_lob=original.Centene_Capacity_Plan_Main_LOB,
                state=original.Centene_Capacity_Plan_State,
                case_type=original.Centene_Capacity_Plan_Case_Type,
                case_id=case_id,
                target_cph=int(new_target_cph),
                target_cph_change=int(target_cph_change),
                modified_fields=modified_fields,
                months=month_data
            )
            result_records.append(record_response)

    # Build summary
    summary = SummaryResponse(
        total_fte_change=total_fte_change,
        total_capacity_change=total_capacity_change
    )

    return PreviewResponse(
        success=True,
        months=months_dict,
        month=month,
        year=year,
        modified_records=result_records,
        total_modified=len(result_records),
        summary=summary,
        message=f"Preview shows forecast impact of {len(result_records)} reallocation changes"
    )
