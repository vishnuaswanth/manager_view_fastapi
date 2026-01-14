"""
CPH Update transformation functions.

Handles CPH changes, forecast impact calculations, and database updates
for Target CPH modifications.
"""

import logging
import uuid
from typing import Dict, List, Tuple
from code.logics.db import ForecastModel
from code.logics.core_utils import CoreUtils
from code.logics.edit_view_utils import (
    get_months_dict,
    parse_month_label,
    get_forecast_column_name
)
from code.logics.capacity_calculations import calculate_fte_required, calculate_capacity
from code.logics.bench_allocation_transformer import (
    PreviewResponse,
    ModifiedRecordResponse,
    MonthDataResponse,
    SummaryResponse
)

logger = logging.getLogger(__name__)


def get_cph_data(
    month: str,
    year: int,
    core_utils: CoreUtils
) -> List[Dict]:
    """
    Get unique Target CPH values by LOB/CaseType combination.

    Args:
        month: Report month name (e.g., "April")
        year: Report year (e.g., 2025)
        core_utils: CoreUtils instance for database access

    Returns:
        List of CPH records with structure:
        {
            "id": "cph_1",  # Generated unique ID
            "lob": "Amisys Medicaid DOMESTIC",
            "case_type": "Claims Processing",
            "target_cph": 45.0,
            "modified_target_cph": 45.0  # Initially same as target_cph
        }

    Raises:
        ValueError: If no forecast data found for month/year
    """
    db_manager = core_utils.get_db_manager(
        ForecastModel,
        limit=10000,
        skip=0,
        select_columns=None
    )

    with db_manager.SessionLocal() as session:
        # Query unique LOB/CaseType/CPH combinations
        records = session.query(
            ForecastModel.Centene_Capacity_Plan_Main_LOB,
            ForecastModel.Centene_Capacity_Plan_Case_Type,
            ForecastModel.Centene_Capacity_Plan_Target_CPH
        ).filter(
            ForecastModel.Month == month,
            ForecastModel.Year == year
        ).distinct().all()

        if not records:
            raise ValueError(f"No forecast data found for {month} {year}")

        # Transform to CPH data format
        cph_data = []
        for idx, (main_lob, case_type, target_cph) in enumerate(records, start=1):
            cph_data.append({
                "id": f"cph_{idx}",
                "lob": main_lob,
                "case_type": case_type,
                "target_cph": round(target_cph, 2),
                "modified_target_cph": round(target_cph, 2)
            })

        logger.info(f"Retrieved {len(cph_data)} unique CPH records for {month} {year}")
        return cph_data


def get_month_config_for_forecast(
    month: str,
    year: int,
    core_utils: CoreUtils,
    work_type: str = "Domestic"
) -> Dict:
    """
    Get month configuration for all 6 months for forecast recalculation.

    Returns dict: {"month1": {config}, "month2": {config}, ...}

    Args:
        month: Report month name (e.g., "April")
        year: Report year (e.g., 2025)
        core_utils: CoreUtils instance
        work_type: Work type to query ("Domestic" or "Global"), defaults to "Domestic"

    Returns:
        Dict with month configs for all 6 months, each containing:
        - working_days: Number of working days
        - work_hours: Work hours per day
        - shrinkage: Shrinkage rate (0.0-1.0)
        - occupancy: Occupancy rate (0.0-1.0)

    Raises:
        ValueError: If work_type is invalid

    Example:
        config = get_month_config_for_forecast("April", 2025, core_utils, "Domestic")
        # Returns: {
        #     "month1": {"working_days": 21, "work_hours": 9, "shrinkage": 0.10, "occupancy": 0.95},
        #     "month2": {...},
        #     ...
        # }
    """
    from code.logics.db import MonthConfigurationModel

    # Validate work_type
    if work_type not in ["Domestic", "Global"]:
        raise ValueError(f"Invalid work_type: '{work_type}'. Must be 'Domestic' or 'Global'")

    months_dict = get_months_dict(month, year, core_utils)
    month_config = {}

    db_manager = core_utils.get_db_manager(
        MonthConfigurationModel,
        limit=20,  # Increased to accommodate both Domestic and Global records
        skip=0,
        select_columns=None
    )

    with db_manager.SessionLocal() as session:
        for month_idx, month_label in months_dict.items():
            # Parse month label "Jun-25" → ("June", 2025)
            full_month, full_year = parse_month_label(month_label)

            # Query month config for specific WorkType
            config_record = session.query(MonthConfigurationModel).filter(
                MonthConfigurationModel.Month == full_month,
                MonthConfigurationModel.Year == full_year,
                MonthConfigurationModel.WorkType == work_type
            ).first()

            if not config_record:
                logger.warning(
                    f"Month config not found for {full_month} {full_year} ({work_type}), using defaults"
                )
                # Use default values
                month_config[month_idx] = {
                    'working_days': 21,
                    'work_hours': 9,
                    'shrinkage': 0.10,
                    'occupancy': 0.95
                }
            else:
                # Access direct fields from model (no JSON parsing needed)
                month_config[month_idx] = {
                    'working_days': config_record.WorkingDays,
                    'work_hours': config_record.WorkHours,
                    'shrinkage': config_record.Shrinkage,
                    'occupancy': config_record.Occupancy
                }

                logger.debug(
                    f"Loaded config for {full_month} {full_year} ({work_type}): "
                    f"WD={config_record.WorkingDays}, WH={config_record.WorkHours}, "
                    f"S={config_record.Shrinkage}, O={config_record.Occupancy}"
                )

    return month_config


def calculate_cph_preview(
    month: str,
    year: int,
    modified_cph_records: List[Dict],
    core_utils: CoreUtils
) -> PreviewResponse:
    """
    Calculate forecast impact of CPH changes (preview only modified records).

    Takes CPH record changes (lob, case_type, target_cph, modified_target_cph)
    and returns affected forecast rows in PreviewResponse format with
    recalculated FTE_required and Capacity values.

    **IMPORTANT**: The output format is a validated Pydantic PreviewResponse model
    that can be serialized and submitted to the CPH update endpoint
    (/api/edit-view/target-cph/update/). This ensures preview data is exactly
    what gets applied to the database.

    Args:
        month: Report month name
        year: Report year
        modified_cph_records: List of CPH records with changes:
            [{"id": "cph_1", "lob": "...", "case_type": "...",
              "target_cph": 45.0, "modified_target_cph": 50.0}]
        core_utils: CoreUtils instance

    Returns:
        PreviewResponse: Validated Pydantic model with:
            - success: True
            - months: {"month1": "Jun-25", ...}
            - month: Report month name
            - year: Report year
            - modified_records: List[ModifiedRecordResponse]
            - total_modified: Count of modified records
            - summary: SummaryResponse with total changes
            - message: Description of preview results

    Raises:
        ValueError: If no actual CPH changes detected
    """
    # Filter records with actual changes
    actual_changes = [
        r for r in modified_cph_records
        if r['target_cph'] != r['modified_target_cph']
    ]

    if not actual_changes:
        raise ValueError(
            "No actual CPH changes detected. "
            "All modified_target_cph values match target_cph."
        )

    # Get month mappings
    months_dict = get_months_dict(month, year, core_utils)

    # Get month config for recalculation
    month_config = get_month_config_for_forecast(month, year, core_utils)

    # Get affected forecast records
    db_manager = core_utils.get_db_manager(
        ForecastModel,
        limit=10000,
        skip=0,
        select_columns=None
    )

    modified_records = []

    with db_manager.SessionLocal() as session:
        for cph_record in actual_changes:
            # Find all forecast records matching LOB/CaseType
            forecast_records = session.query(ForecastModel).filter(
                ForecastModel.Month == month,
                ForecastModel.Year == year,
                ForecastModel.Centene_Capacity_Plan_Main_LOB == cph_record['lob'],
                ForecastModel.Centene_Capacity_Plan_Case_Type == cph_record['case_type']
            ).all()

            # Calculate new FTE Required and Capacity for each affected record
            for forecast_row in forecast_records:
                modified_fields = ["target_cph"]
                month_data = {}

                # Calculate impact for each month
                for month_idx, month_label in months_dict.items():
                    suffix = month_idx.replace('month', '')

                    # Use utility function for column name lookup
                    forecast = getattr(
                        forecast_row,
                        get_forecast_column_name('forecast', suffix),
                        0
                    )
                    old_fte_req = getattr(
                        forecast_row,
                        get_forecast_column_name('fte_req', suffix),
                        0
                    )
                    fte_avail = getattr(
                        forecast_row,
                        get_forecast_column_name('fte_avail', suffix),
                        0
                    )
                    old_capacity = getattr(
                        forecast_row,
                        get_forecast_column_name('capacity', suffix),
                        0
                    )

                    # Recalculate with new CPH
                    new_cph = cph_record['modified_target_cph']
                    config = month_config[month_idx]

                    # Calculate FTE Required using utility function
                    new_fte_req = calculate_fte_required(forecast, config, new_cph)

                    # Calculate Capacity using utility function
                    new_capacity = calculate_capacity(fte_avail, config, new_cph)

                    # Calculate changes
                    fte_req_change = new_fte_req - old_fte_req
                    capacity_change = new_capacity - old_capacity

                    # Create MonthDataResponse for this month
                    month_data[month_label] = MonthDataResponse(
                        forecast=int(forecast),
                        fte_req=int(new_fte_req),
                        fte_req_change=int(fte_req_change),
                        fte_avail=int(fte_avail),
                        fte_avail_change=0,  # CPH change doesn't affect FTE Available
                        capacity=int(new_capacity),
                        capacity_change=int(capacity_change)
                    )

                    # Track modified fields
                    # OPTION 1: If ANY field changed for this month, track ALL fields
                    has_changes = (fte_req_change != 0 or capacity_change != 0)

                    if has_changes:
                        # Add ALL fields for this month (complete snapshot of modified record)
                        fields_to_add = [
                            f"{month_label}.forecast",
                            f"{month_label}.fte_req",
                            f"{month_label}.fte_avail",
                            f"{month_label}.capacity"
                        ]

                        # Only add if not already in list
                        for field in fields_to_add:
                            if field not in modified_fields:
                                modified_fields.append(field)

                # Only include if there are changes (more than just "target_cph")
                if len(modified_fields) > 1:
                    # Create ModifiedRecordResponse with correct field names
                    record = ModifiedRecordResponse(
                        main_lob=forecast_row.Centene_Capacity_Plan_Main_LOB,
                        state=forecast_row.Centene_Capacity_Plan_State,
                        case_type=forecast_row.Centene_Capacity_Plan_Case_Type,
                        case_id=forecast_row.Centene_Capacity_Plan_Call_Type_ID,
                        target_cph=float(cph_record['modified_target_cph']),  # Use modified value as new target
                        target_cph_change=float(cph_record['modified_target_cph'] - cph_record['target_cph']),
                        modified_fields=modified_fields,
                        months=month_data
                    )
                    modified_records.append(record)

    # Calculate summary
    total_fte_change = sum(
        abs(month_data.fte_req_change)
        for record in modified_records
        for month_data in record.months.values()
    )
    total_capacity_change = sum(
        abs(month_data.capacity_change)
        for record in modified_records
        for month_data in record.months.values()
    )

    summary = SummaryResponse(
        total_fte_change=int(total_fte_change),
        total_capacity_change=int(total_capacity_change)
    )

    return PreviewResponse(
        success=True,
        months=months_dict,
        month=month,
        year=year,
        modified_records=modified_records,
        total_modified=len(modified_records),
        summary=summary,
        message=f"Preview shows forecast impact of {len(actual_changes)} CPH changes"
    )


def update_forecast_from_cph_changes(
    month: str,
    year: int,
    modified_cph_records: List[Dict],
    core_utils: CoreUtils
) -> Tuple[int, int]:
    """
    Update ForecastModel records with new CPH values and recalculate metrics.

    Args:
        month: Report month name
        year: Report year
        modified_cph_records: List of CPH records with changes
        core_utils: CoreUtils instance

    Returns:
        Tuple of (cph_records_updated, forecast_rows_affected)

    Raises:
        ValueError: If no forecast records found
        SQLAlchemyError: If database update fails
    """
    # Filter actual changes
    actual_changes = [
        r for r in modified_cph_records
        if r['target_cph'] != r['modified_target_cph']
    ]

    if not actual_changes:
        return (0, 0)

    db_manager = core_utils.get_db_manager(
        ForecastModel,
        limit=10000,
        skip=0,
        select_columns=None
    )

    cph_records_updated = 0
    forecast_rows_affected = 0

    # Get month config for recalculation
    month_config = get_month_config_for_forecast(month, year, core_utils)

    with db_manager.SessionLocal() as session:
        for cph_record in actual_changes:
            # Find all forecast records matching LOB/CaseType
            forecast_records = session.query(ForecastModel).filter(
                ForecastModel.Month == month,
                ForecastModel.Year == year,
                ForecastModel.Centene_Capacity_Plan_Main_LOB == cph_record['lob'],
                ForecastModel.Centene_Capacity_Plan_Case_Type == cph_record['case_type']
            ).all()

            if not forecast_records:
                logger.warning(
                    f"No forecast records found for {cph_record['lob']}, "
                    f"{cph_record['case_type']}"
                )
                continue

            new_cph = cph_record['modified_target_cph']

            for forecast_row in forecast_records:
                # Update Target_CPH
                forecast_row.Centene_Capacity_Plan_Target_CPH = new_cph

                # Recalculate FTE Required and Capacity for all 6 months
                for suffix in ['1', '2', '3', '4', '5', '6']:
                    # Use utility function for column name lookup
                    forecast = getattr(
                        forecast_row,
                        get_forecast_column_name('forecast', suffix),
                        0
                    )
                    fte_avail = getattr(
                        forecast_row,
                        get_forecast_column_name('fte_avail', suffix),
                        0
                    )

                    config = month_config[f'month{suffix}']

                    # Calculate FTE Required using utility function
                    new_fte_req = calculate_fte_required(forecast, config, new_cph)

                    # Calculate Capacity using utility function
                    new_capacity = calculate_capacity(fte_avail, config, new_cph)

                    # Update using utility function for column name lookup
                    setattr(
                        forecast_row,
                        get_forecast_column_name('fte_req', suffix),
                        new_fte_req
                    )
                    setattr(
                        forecast_row,
                        get_forecast_column_name('capacity', suffix),
                        new_capacity
                    )

                forecast_rows_affected += 1

            cph_records_updated += 1

        # Commit all updates
        session.commit()
        logger.info(
            f"Updated {cph_records_updated} CPH records, "
            f"affected {forecast_rows_affected} forecast rows"
        )

    return (cph_records_updated, forecast_rows_affected)
