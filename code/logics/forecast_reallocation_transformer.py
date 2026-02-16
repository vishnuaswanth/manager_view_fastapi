"""
Forecast Reallocation transformation functions.

Handles data loading, preview calculations, and forecast updates for the
Forecast Reallocation feature (Edit View Sections 10-13).
"""

import logging
from typing import Dict, List, Optional, Tuple, Union
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


def _extract_changes_from_modified_fields(modified_fields: List) -> Tuple[Optional[float], Dict[str, int]]:
    """
    Extract target_cph and FTE available changes from modified_fields list.

    The frontend sends modified_fields as objects:
    - CPH change: {"field": "target_cph", "original_value": 3, "new_value": 5, "change": 2}
    - FTE change: {"month_label": "May-25", "field": "fte_avail", "original_fte_avail": 4,
                   "new_fte_avail": 7, "fte_avail_change": 3, "forecast": 1535}

    Args:
        modified_fields: List of modified field objects from frontend

    Returns:
        Tuple of (new_target_cph or None, dict mapping month_label to new_fte_avail)
    """
    new_target_cph = None
    fte_changes = {}

    for field_obj in modified_fields:
        if isinstance(field_obj, dict):
            field_name = field_obj.get('field', '')

            if field_name == 'target_cph':
                # Extract new CPH value
                new_value = field_obj.get('new_value')
                if new_value is not None:
                    new_target_cph = float(new_value)
                    logger.debug(f"Extracted target_cph change: {new_target_cph}")

            elif field_name == 'fte_avail' and 'month_label' in field_obj:
                # Extract FTE change for specific month
                month_label = field_obj['month_label']
                new_fte_avail = field_obj.get('new_fte_avail')
                if new_fte_avail is not None:
                    fte_changes[month_label] = int(new_fte_avail)
                    logger.debug(f"Extracted FTE change: {month_label} -> {new_fte_avail}")

        elif isinstance(field_obj, str):
            # String format like "target_cph" or "May-25.fte_avail" - no value info
            pass

    return new_target_cph, fte_changes


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
        modified_records: List of records with user modifications from frontend
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
        # Use main_lob from input record if available, otherwise from DB
        main_lob_for_work_type = input_record.get('main_lob') or original.Centene_Capacity_Plan_Main_LOB
        work_type = _get_work_type_from_main_lob(main_lob_for_work_type)
        month_config = get_cached_month_config(work_type)

        logger.info(
            f"[Work Type Detection] case_id={case_id}, "
            f"main_lob='{main_lob_for_work_type}', "
            f"detected_work_type='{work_type}'"
        )

        # Extract changes from modified_fields (frontend sends new values here)
        input_modified_fields = input_record.get('modified_fields', [])
        extracted_target_cph, fte_changes_from_modified = _extract_changes_from_modified_fields(input_modified_fields)

        logger.debug(f"Extracted target_cph: {extracted_target_cph}, FTE changes: {fte_changes_from_modified}")

        # Get new target CPH - prioritize extracted value from modified_fields
        original_target_cph = float(original.Centene_Capacity_Plan_Target_CPH or 0)
        if extracted_target_cph is not None:
            new_target_cph = extracted_target_cph
            logger.debug(f"Using target_cph from modified_fields: {new_target_cph}")
        else:
            # Fall back to top-level target_cph field or original value
            new_target_cph = float(input_record.get('target_cph', original_target_cph))

        target_cph_change = new_target_cph - original_target_cph

        # Track modified fields for response (will include all fields for months with changes)
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

            # Get user-modified FTE Available
            # Priority: 1) modified_fields extraction, 2) months dict, 3) original DB value
            input_month_data = input_months.get(month_label, {})
            if month_label in fte_changes_from_modified:
                # New FTE value from modified_fields (preferred source)
                new_fte_avail = fte_changes_from_modified[month_label]
                logger.debug(f"Using FTE from modified_fields for {month_label}: {new_fte_avail}")
            elif isinstance(input_month_data, dict):
                new_fte_avail = int(input_month_data.get('fte_avail', orig_fte_avail))
            else:
                # input_month_data might be a Pydantic model
                new_fte_avail = int(getattr(input_month_data, 'fte_avail', orig_fte_avail))

            # Debug logging - show all values used in calculation
            logger.info(
                f"[Reallocation Calc] {month_label} | work_type={work_type} | "
                f"config: WD={config.get('working_days')}, WH={config.get('work_hours')}, "
                f"shrinkage={config.get('shrinkage')}, occupancy={config.get('occupancy')}"
            )
            logger.info(
                f"[Reallocation Calc] {month_label} | "
                f"orig_fte_avail={orig_fte_avail}, new_fte_avail={new_fte_avail}, "
                f"orig_target_cph={original_target_cph}, new_target_cph={new_target_cph}"
            )

            # Recalculate FTE Required based on new CPH
            new_fte_req = calculate_fte_required(orig_forecast, config, new_target_cph)

            # Recalculate Capacity based on new FTE Available and new CPH
            new_capacity = calculate_capacity(new_fte_avail, config, new_target_cph)

            # Manual calculation for verification
            manual_capacity = (
                new_fte_avail *
                config.get('working_days', 21) *
                config.get('work_hours', 9) *
                (1 - config.get('shrinkage', 0.10)) *
                new_target_cph
            )

            logger.info(
                f"[Reallocation Calc] {month_label} | "
                f"orig_capacity={orig_capacity}, new_capacity={new_capacity}, "
                f"manual_verify={manual_capacity:.2f}"
            )

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
