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


def calculate_reallocation_preview(
    month: str,
    year: int,
    modified_records: List[Dict],
    core_utils: CoreUtils
) -> PreviewResponse:
    """
    Calculate preview for forecast reallocation.

    Steps:
    1. Get DB record for each modified record
    2. Create old_data (from DB) and new_data (to update)
    3. Update target_cph from modified record
    4. Update fte_avail for each month from modified record
    5. If target_cph changed, recalculate fte_required for all 6 months
    6. Calculate capacity for all 6 months
    7. Calculate changes by comparing old_data and new_data
    """
    if not modified_records:
        raise ValueError("No records provided for preview")

    months_dict = get_months_dict(month, year, core_utils)
    month_labels = list(months_dict.values())  # ['May-25', 'Jun-25', ...]

    # Cache month configs by work_type
    config_cache: Dict[str, Dict] = {}

    def get_config(work_type: str) -> Dict:
        if work_type not in config_cache:
            config_cache[work_type] = get_month_config_for_forecast(month, year, core_utils, work_type)
        return config_cache[work_type]

    # Load all DB records for this month/year
    db_manager = core_utils.get_db_manager(ForecastModel, limit=10000, skip=0, select_columns=None)
    with db_manager.SessionLocal() as session:
        db_records = session.query(ForecastModel).filter(
            ForecastModel.Month == month,
            ForecastModel.Year == year
        ).all()
        db_lookup = {
            (r.Centene_Capacity_Plan_Main_LOB, r.Centene_Capacity_Plan_State, r.Centene_Capacity_Plan_Case_Type): r
            for r in db_records
        }

    result_records = []
    total_fte_change = 0
    total_capacity_change = 0

    for input_rec in modified_records:
        # Step 1: Get DB record
        key = (input_rec.get('main_lob'), input_rec.get('state'), input_rec.get('case_type'))
        if not all(key):
            raise ValueError(f"Record missing required fields: {key}")

        db_rec = db_lookup.get(key)
        if not db_rec:
            logger.warning(f"DB record not found for {key}, skipping")
            continue

        work_type = _get_work_type_from_main_lob(key[0], key[2])
        month_config = get_config(work_type)

        # Step 2: Create old_data and new_data structures
        old_data = {
            'target_cph': float(db_rec.Centene_Capacity_Plan_Target_CPH or 0),
            'months': {}
        }
        new_data = {
            'target_cph': float(input_rec.get('target_cph', old_data['target_cph'])),
            'months': {}
        }

        # Populate old_data months from DB
        for month_idx, month_label in months_dict.items():
            suffix = month_idx.replace('month', '')
            old_data['months'][month_label] = {
                'forecast': int(getattr(db_rec, get_forecast_column_name('forecast', suffix), 0) or 0),
                'fte_req': int(getattr(db_rec, get_forecast_column_name('fte_req', suffix), 0) or 0),
                'fte_avail': int(getattr(db_rec, get_forecast_column_name('fte_avail', suffix), 0) or 0),
                'capacity': int(getattr(db_rec, get_forecast_column_name('capacity', suffix), 0) or 0),
            }
            # Initialize new_data with old values
            new_data['months'][month_label] = old_data['months'][month_label].copy()

        # Step 3: Validate target_cph change
        input_target_cph_change = float(input_rec.get('target_cph_change', 0))
        if input_target_cph_change != 0:
            calc_change = new_data['target_cph'] - old_data['target_cph']
            if abs(calc_change - input_target_cph_change) > 0.001:
                raise ValueError(
                    f"target_cph_change mismatch for {key}: "
                    f"reported={input_target_cph_change}, calculated={calc_change}"
                )

        target_cph_changed = (new_data['target_cph'] != old_data['target_cph'])

        # Step 4: Update fte_avail for each month from input
        input_months = input_rec.get('months', {})
        for month_label in month_labels:
            input_month = input_months.get(month_label, {})
            if isinstance(input_month, dict):
                new_fte_avail = int(input_month.get('fte_avail', old_data['months'][month_label]['fte_avail']))
                input_fte_change = int(input_month.get('fte_avail_change', 0))
            else:
                new_fte_avail = int(getattr(input_month, 'fte_avail', old_data['months'][month_label]['fte_avail']))
                input_fte_change = int(getattr(input_month, 'fte_avail_change', 0))

            # Validate fte_avail change
            if input_fte_change != 0:
                calc_change = new_fte_avail - old_data['months'][month_label]['fte_avail']
                if calc_change != input_fte_change:
                    raise ValueError(
                        f"fte_avail_change mismatch for {key} month {month_label}: "
                        f"reported={input_fte_change}, calculated={calc_change}"
                    )

            new_data['months'][month_label]['fte_avail'] = new_fte_avail

        # Step 5: If target_cph changed, recalculate fte_required for all 6 months
        if target_cph_changed:
            for month_idx, month_label in months_dict.items():
                config = month_config[month_idx]
                forecast = old_data['months'][month_label]['forecast']
                new_data['months'][month_label]['fte_req'] = calculate_fte_required(
                    forecast, config, new_data['target_cph']
                )

        # Step 6: Calculate capacity for all 6 months
        for month_idx, month_label in months_dict.items():
            config = month_config[month_idx]
            new_data['months'][month_label]['capacity'] = int(calculate_capacity(
                new_data['months'][month_label]['fte_avail'],
                config,
                new_data['target_cph']
            ))

        # Step 7: Calculate changes and build response
        modified_fields = []

        modified_fields.append("target_cph")

        month_data = {}
        for month_label in month_labels:
            old_m = old_data['months'][month_label]
            new_m = new_data['months'][month_label]

            fte_req_change = new_m['fte_req'] - old_m['fte_req']
            fte_avail_change = new_m['fte_avail'] - old_m['fte_avail']
            capacity_change = new_m['capacity'] - old_m['capacity']

            if fte_req_change != 0 or fte_avail_change != 0 or capacity_change != 0:
                modified_fields.extend([
                    f"{month_label}.forecast",
                    f"{month_label}.fte_req",
                    f"{month_label}.fte_avail",
                    f"{month_label}.capacity"
                ])
                total_fte_change += abs(fte_avail_change)
                total_capacity_change += abs(capacity_change)

            month_data[month_label] = MonthDataResponse(
                forecast=old_m['forecast'],
                fte_req=new_m['fte_req'],
                fte_avail=new_m['fte_avail'],
                capacity=new_m['capacity'],
                forecast_change=0,
                fte_req_change=fte_req_change,
                fte_avail_change=fte_avail_change,
                capacity_change=capacity_change
            )

        if modified_fields:
            result_records.append(ModifiedRecordResponse(
                main_lob=db_rec.Centene_Capacity_Plan_Main_LOB,
                state=db_rec.Centene_Capacity_Plan_State,
                case_type=db_rec.Centene_Capacity_Plan_Case_Type,
                case_id=db_rec.Centene_Capacity_Plan_Call_Type_ID,
                target_cph=int(new_data['target_cph']),
                target_cph_change=int(new_data['target_cph'] - old_data['target_cph']),
                modified_fields=list(set(modified_fields)),  # Remove duplicates
                months=month_data
            ))

    return PreviewResponse(
        success=True,
        months=months_dict,
        month=month,
        year=year,
        modified_records=result_records,
        total_modified=len(result_records),
        summary=SummaryResponse(
            total_fte_change=total_fte_change,
            total_capacity_change=total_capacity_change
        ),
        message=f"Preview shows forecast impact of {len(result_records)} reallocation changes"
    )
