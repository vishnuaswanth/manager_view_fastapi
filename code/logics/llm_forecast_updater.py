"""
LLM Forecast Update Utilities.

Provides utility functions for LLM-specific forecast updates,
including single-record target CPH updates with automatic
recalculation of FTE_Required and Capacity.
"""

import logging
import calendar
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from sqlalchemy import and_, func

from code.logics.db import ForecastModel, ForecastMonthsModel
from code.logics.capacity_calculations import calculate_fte_required, calculate_capacity
from code.logics.month_config_utils import get_specific_config
from code.logics.llm_utils import determine_locality
from code.logics.history_logger import create_history_log, add_history_changes
from code.logics.config.change_types import CHANGE_TYPE_CPH_UPDATE


logger = logging.getLogger(__name__)


def _get_month_label(month_name: str, year: int) -> str:
    """
    Convert month name and year to label format (e.g., "Apr-25").

    Args:
        month_name: Full month name (e.g., "April")
        year: Year (e.g., 2025)

    Returns:
        Month label (e.g., "Apr-25")
    """
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
    year_short = str(year)[2:]

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
    """
    month_to_num = {month: idx for idx, month in enumerate(calendar.month_name) if month}

    report_month_num = month_to_num.get(report_month, 1)
    forecast_month_num = month_to_num.get(forecast_month, 1)

    return report_year + 1 if forecast_month_num < report_month_num else report_year


def update_single_record_target_cph(
    report_month: str,
    report_year: int,
    main_lob: str,
    state: str,
    case_type: str,
    new_target_cph: int,
    user_notes: Optional[str],
    core_utils: Any
) -> Dict[str, Any]:
    """
    Update target_CPH for all forecast records matching the criteria
    and recalculate derived fields.

    This function:
    1. Finds all matching forecast records (by main_lob, state, case_type, month, year)
    2. Updates Centene_Capacity_Plan_Target_CPH
    3. Recalculates FTE_Required_Month1-6 and Capacity_Month1-6
    4. Creates a history log entry

    Args:
        report_month: Report month name (e.g., "March")
        report_year: Report year (e.g., 2025)
        main_lob: Main LOB (e.g., "Amisys Medicaid Domestic")
        state: State code (e.g., "LA", "N/A")
        case_type: Case type (e.g., "Claims Processing")
        new_target_cph: New target CPH value (must be > 0 and <= 200)
        user_notes: Optional notes about the change
        core_utils: CoreUtils instance for database operations

    Returns:
        Dict with success status, old/new values, recalculated_totals, and history_log_id

    Raises:
        ValueError: If validation fails
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Step 1: Get database manager and find matching records
    db_manager = core_utils.get_db_manager(
        ForecastModel,
        limit=1000,
        skip=0,
        select_columns=None
    )

    with db_manager.SessionLocal() as session:
        # Query for matching records
        query = session.query(ForecastModel).filter(
            and_(
                func.lower(func.trim(ForecastModel.Centene_Capacity_Plan_Main_LOB)) == main_lob.lower().strip(),
                func.lower(func.trim(ForecastModel.Centene_Capacity_Plan_State)) == state.lower().strip(),
                func.lower(func.trim(ForecastModel.Centene_Capacity_Plan_Case_Type)) == case_type.lower().strip(),
                func.trim(ForecastModel.Month) == report_month.strip().capitalize(),
                ForecastModel.Year == report_year
            )
        )

        records = query.all()

        if not records:
            logger.warning(
                f"[update_single_record_target_cph] No records found for "
                f"{main_lob} | {state} | {case_type} ({report_month} {report_year})"
            )
            return {
                "success": False,
                "error": "Forecast record not found",
                "status_code": 404,
                "report_month": report_month,
                "report_year": report_year,
                "main_lob": main_lob,
                "state": state,
                "case_type": case_type,
                "recommendation": "Use /api/llm/forecast/filter-options to verify valid values",
                "timestamp": timestamp
            }

        # Get old target CPH (should be same for all matching records)
        old_target_cph = records[0].Centene_Capacity_Plan_Target_CPH or 0

        # Step 2: Get forecast months mapping
        first_record = records[0]
        uploaded_file = first_record.UploadedFile

        forecast_months_record = session.query(ForecastMonthsModel).filter(
            ForecastMonthsModel.UploadedFile == uploaded_file
        ).order_by(ForecastMonthsModel.CreatedDateTime.desc()).first()

        if not forecast_months_record:
            logger.error(
                f"[update_single_record_target_cph] No forecast months mapping found for file {uploaded_file}"
            )
            return {
                "success": False,
                "error": "Forecast month mapping not found",
                "status_code": 500,
                "report_month": report_month,
                "report_year": report_year,
                "timestamp": timestamp
            }

        # Build month mapping
        month_names = [
            forecast_months_record.Month1,
            forecast_months_record.Month2,
            forecast_months_record.Month3,
            forecast_months_record.Month4,
            forecast_months_record.Month5,
            forecast_months_record.Month6
        ]

        # Determine locality for config lookup
        locality = determine_locality(main_lob, case_type)

        # Step 3: Get month configs and prepare recalculation
        recalculated_totals = {}
        missing_configs = []

        for i, month_name in enumerate(month_names, start=1):
            if not month_name:
                continue

            forecast_year = _get_year_for_month(report_month, report_year, month_name)
            month_label = _get_month_label(month_name, forecast_year)

            # Get config for this month
            config = get_specific_config(month_name, forecast_year, locality)
            if not config:
                missing_configs.append(f"{month_name} {forecast_year} ({locality})")
                continue

            recalculated_totals[month_label] = {
                "month_index": i,
                "month_name": month_name,
                "forecast_year": forecast_year,
                "config": {
                    "working_days": config["working_days"],
                    "work_hours": config["work_hours"],
                    "shrinkage": config["shrinkage"]
                },
                "fte_required": {"old": 0, "new": 0, "change": 0},
                "capacity": {"old": 0.0, "new": 0.0, "change": 0.0}
            }

        if missing_configs:
            logger.error(
                f"[update_single_record_target_cph] Missing configs: {missing_configs}"
            )
            return {
                "success": False,
                "error": f"Month configuration missing for: {', '.join(missing_configs)}",
                "status_code": 400,
                "report_month": report_month,
                "report_year": report_year,
                "main_lob": main_lob,
                "state": state,
                "case_type": case_type,
                "recommendation": "Configure month settings before updating CPH",
                "timestamp": timestamp
            }

        # Step 4: Update records and recalculate
        history_changes = []

        for record in records:
            case_id = record.Centene_Capacity_Plan_Call_Type_ID or ""

            # Update target CPH
            record.Centene_Capacity_Plan_Target_CPH = new_target_cph
            record.UpdatedBy = "llm_api"
            record.UpdatedDateTime = datetime.now()

            # Track CPH change
            history_changes.append({
                "main_lob": main_lob,
                "state": state,
                "case_type": case_type,
                "case_id": case_id,
                "field_name": "target_cph",
                "old_value": old_target_cph,
                "new_value": new_target_cph,
                "delta": new_target_cph - old_target_cph,
                "month_label": None
            })

            # Recalculate for each month
            for month_label, month_data in recalculated_totals.items():
                i = month_data["month_index"]
                config = month_data["config"]

                # Get current values
                forecast_val = getattr(record, f"Client_Forecast_Month{i}", 0) or 0
                fte_avail_val = getattr(record, f"FTE_Avail_Month{i}", 0) or 0
                old_fte_req = getattr(record, f"FTE_Required_Month{i}", 0) or 0
                old_capacity = getattr(record, f"Capacity_Month{i}", 0) or 0.0

                # Calculate new values
                new_fte_req = calculate_fte_required(forecast_val, config, new_target_cph)
                new_capacity = calculate_capacity(fte_avail_val, config, new_target_cph)

                # Update record
                setattr(record, f"FTE_Required_Month{i}", new_fte_req)
                setattr(record, f"Capacity_Month{i}", int(new_capacity))

                # Aggregate totals
                month_data["fte_required"]["old"] += old_fte_req
                month_data["fte_required"]["new"] += new_fte_req
                month_data["capacity"]["old"] += old_capacity
                month_data["capacity"]["new"] += new_capacity

                # Track changes for history
                if old_fte_req != new_fte_req:
                    history_changes.append({
                        "main_lob": main_lob,
                        "state": state,
                        "case_type": case_type,
                        "case_id": case_id,
                        "field_name": f"{month_label}.fte_req",
                        "old_value": old_fte_req,
                        "new_value": new_fte_req,
                        "delta": new_fte_req - old_fte_req,
                        "month_label": month_label
                    })

                if old_capacity != new_capacity:
                    history_changes.append({
                        "main_lob": main_lob,
                        "state": state,
                        "case_type": case_type,
                        "case_id": case_id,
                        "field_name": f"{month_label}.capacity",
                        "old_value": old_capacity,
                        "new_value": new_capacity,
                        "delta": new_capacity - old_capacity,
                        "month_label": month_label
                    })

        # Commit changes
        session.commit()

        # Calculate change deltas for response
        for month_label, month_data in recalculated_totals.items():
            month_data["fte_required"]["change"] = (
                month_data["fte_required"]["new"] - month_data["fte_required"]["old"]
            )
            month_data["capacity"]["change"] = (
                month_data["capacity"]["new"] - month_data["capacity"]["old"]
            )
            # Remove internal fields from response
            del month_data["month_index"]
            del month_data["month_name"]
            del month_data["forecast_year"]
            del month_data["config"]

    # Step 5: Create history log
    history_log_id = None
    try:
        summary_data = {
            "old_target_cph": old_target_cph,
            "new_target_cph": new_target_cph,
            "records_updated": len(records),
            "months_affected": list(recalculated_totals.keys())
        }

        history_log_id = create_history_log(
            month=report_month,
            year=report_year,
            change_type=CHANGE_TYPE_CPH_UPDATE,
            user="llm_api",
            description=user_notes,
            records_modified=len(records),
            summary_data=summary_data
        )

        if history_changes:
            add_history_changes(history_log_id, history_changes)

        logger.info(
            f"[update_single_record_target_cph] Created history log {history_log_id} "
            f"with {len(history_changes)} changes"
        )
    except Exception as e:
        logger.error(f"[update_single_record_target_cph] Failed to create history log: {e}")
        # Don't fail the whole operation if history logging fails

    logger.info(
        f"[update_single_record_target_cph] Updated {len(records)} records for "
        f"{main_lob} | {state} | {case_type} ({report_month} {report_year}): "
        f"CPH {old_target_cph} -> {new_target_cph}"
    )

    return {
        "success": True,
        "message": "Target CPH updated successfully",
        "report_month": report_month,
        "report_year": report_year,
        "main_lob": main_lob,
        "state": state,
        "case_type": case_type,
        "old_target_cph": old_target_cph,
        "new_target_cph": new_target_cph,
        "records_updated": len(records),
        "history_log_id": history_log_id,
        "recalculated_totals": recalculated_totals,
        "timestamp": timestamp
    }
