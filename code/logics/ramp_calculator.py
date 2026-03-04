"""
Ramp calculation logic for weekly staffing ramp-ups on forecast rows.

Provides preview and apply operations that compute additive capacity impact
from per-week employee ramp schedules and persist results to ForecastModel + RampModel.
"""

import logging
import uuid
from calendar import month_abbr as cal_month_abbr
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from code.api.dependencies import get_core_utils, get_logger
from code.cache import clear_all_caches
from code.logics.config.change_types import CHANGE_TYPE_RAMP_CALCULATION
from code.logics.db import ForecastModel, MonthConfigurationModel, RampModel
from code.logics.edit_view_utils import (
    get_forecast_column_name,
    get_months_dict,
    parse_month_label,
)
from code.logics.history_logger import create_complete_history_log

logger = get_logger(__name__)
core_utils = get_core_utils()

# ============================================================================
# INTERNAL HELPERS
# ============================================================================


def _parse_month_key_to_label(month_key: str) -> str:
    """
    Convert "YYYY-MM" to abbreviated label "Mon-YY".

    Args:
        month_key: Date string in "YYYY-MM" format (e.g., "2026-01")

    Returns:
        Abbreviated label (e.g., "Jan-26")
    """
    dt = datetime.strptime(month_key, "%Y-%m")
    return f"{cal_month_abbr[dt.month]}-{str(dt.year)[-2:]}"


def _get_forecast_row(forecast_id: int, session) -> ForecastModel:
    """
    Fetch ForecastModel by primary key.

    Args:
        forecast_id: Primary key of the forecast row
        session: Active SQLAlchemy session

    Returns:
        ForecastModel instance

    Raises:
        HTTPException 404: If forecast row not found
    """
    row = session.get(ForecastModel, forecast_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error": f"Forecast row with id={forecast_id} not found",
                "recommendation": "Verify the forecast_id is correct"
            }
        )
    return row


def _resolve_month_suffix(
    row: ForecastModel,
    month_key: str,
) -> Tuple[str, str]:
    """
    Resolve the month suffix ("1"-"6") and label ("Mon-YY") for a given month_key.

    Args:
        row: ForecastModel row (provides Month/Year for report period lookup)
        month_key: Target month in "YYYY-MM" format

    Returns:
        Tuple of (suffix, month_label) e.g. ("1", "Jan-26")

    Raises:
        HTTPException 400: If month_key is not in the forecast report period
    """
    months_dict = get_months_dict(row.Month, row.Year, core_utils)
    target_label = _parse_month_key_to_label(month_key)

    # Search dict values for matching label
    for key, label in months_dict.items():
        if label == target_label:
            # key is "month1" .. "month6"; extract numeric suffix
            suffix = key.replace("month", "")
            return suffix, target_label

    raise HTTPException(
        status_code=400,
        detail={
            "success": False,
            "error": f"Month '{target_label}' (from month_key='{month_key}') is not in this report period",
            "recommendation": (
                f"Report period for {row.Month} {row.Year} contains: "
                + ", ".join(months_dict.values())
            )
        }
    )


def _get_ramp_month_config(
    month_label: str,
    main_lob: str,
    case_type: str,
) -> Dict:
    """
    Fetch MonthConfigurationModel for a given month/LOB combination.

    Falls back to default values if configuration is not found.

    Args:
        month_label: Abbreviated label (e.g., "Jan-26")
        main_lob: Forecast row's main LOB string
        case_type: Forecast row's case type

    Returns:
        Dict with keys: working_days, occupancy, shrinkage, work_hours
    """
    from code.logics.cph_update_transformer import _get_work_type_from_main_lob

    full_month, full_year = parse_month_label(month_label)
    work_type = _get_work_type_from_main_lob(main_lob, case_type)

    db_manager = core_utils.get_db_manager(
        MonthConfigurationModel,
        limit=1,
        skip=0,
        select_columns=None
    )

    with db_manager.SessionLocal() as session:
        config_row = session.query(MonthConfigurationModel).filter(
            MonthConfigurationModel.Month == full_month,
            MonthConfigurationModel.Year == full_year,
            MonthConfigurationModel.WorkType == work_type
        ).first()

        if config_row is None:
            logger.warning(
                f"No MonthConfiguration found for {full_month} {full_year} {work_type}. "
                "Using default values."
            )
            return {
                "working_days": 21,
                "occupancy": 0.95,
                "shrinkage": 0.10,
                "work_hours": 9.0
            }

        return {
            "working_days": config_row.WorkingDays,
            "occupancy": config_row.Occupancy,
            "shrinkage": config_row.Shrinkage,
            "work_hours": config_row.WorkHours
        }


def _generate_ramp_name() -> str:
    """
    Generate a unique ramp name using UTC date and a UUID fragment.

    Format: "Ramp-YYYYMMDD-xxxxxxxx" where the suffix is the first 8 hex chars of a UUID4.
    Uniqueness is guaranteed by the UUID component even when multiple ramps are created
    on the same day for the same (forecast_id, month_key).

    Returns:
        Unique ramp name string, e.g. "Ramp-20260110-a1b2c3d4"
    """
    return f"Ramp-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8]}"


def _compute_ramp_totals(weeks: List, config: Dict, target_cph: float) -> Tuple[float, int]:
    """
    Compute total additive capacity and max ramp employees across all weeks.

    Capacity per week = employees × target_cph × work_hours × occupancy × (1 - shrinkage) × working_days

    Args:
        weeks: List of RampWeek Pydantic objects
        config: Month config dict with working_days, occupancy, shrinkage, work_hours
        target_cph: Cases per hour from ForecastModel

    Returns:
        Tuple of (total_ramp_capacity: float, max_ramp_employees: int)
    """
    per_week = [
        w.rampEmployees * target_cph * config["work_hours"]
        * config["occupancy"] * (1 - config["shrinkage"]) * w.workingDays
        for w in weeks
    ]
    total_ramp_capacity = sum(per_week)
    max_ramp_employees = max((w.rampEmployees for w in weeks), default=0)
    return total_ramp_capacity, max_ramp_employees


# ============================================================================
# PUBLIC API
# ============================================================================


def get_applied_ramp(forecast_id: int, month_key: str) -> Dict:
    """
    Get previously applied ramp data for a forecast row and month.

    Groups results by ramp_name to support multiple named ramps per (forecast_id, month_key).

    Args:
        forecast_id: ForecastModel primary key
        month_key: Target month in "YYYY-MM" format

    Returns:
        Dict with ramp_applied flag and ramps (list of {ramp_name, weeks} dicts)
    """
    db_manager = core_utils.get_db_manager(
        RampModel,
        limit=10000,
        skip=0,
        select_columns=None
    )

    with db_manager.SessionLocal() as session:
        # Verify forecast row exists
        _get_forecast_row(forecast_id, session)

        ramp_rows = session.query(RampModel).filter(
            RampModel.forecast_id == forecast_id,
            RampModel.month_key == month_key
        ).order_by(RampModel.ramp_name, RampModel.start_date).all()

        if not ramp_rows:
            return {
                "success": True,
                "forecast_id": forecast_id,
                "month_key": month_key,
                "ramp_applied": False,
                "ramps": []
            }

        grouped = defaultdict(list)
        for r in ramp_rows:
            grouped[r.ramp_name].append({
                "id": r.id,
                "week_label": r.week_label,
                "start_date": r.start_date,
                "end_date": r.end_date,
                "working_days": r.working_days,
                "ramp_percent": r.ramp_percent,
                "employee_count": r.employee_count,
                "applied_at": r.applied_at.isoformat() if r.applied_at else None,
                "applied_by": r.applied_by
            })

        ramps = [
            {"ramp_name": name, "weeks": weeks}
            for name, weeks in grouped.items()
        ]

        return {
            "success": True,
            "forecast_id": forecast_id,
            "month_key": month_key,
            "ramp_applied": True,
            "ramps": ramps
        }


def preview_ramp(forecast_id: int, month_key: str, weeks: List) -> Dict:
    """
    Preview the impact of a ramp without writing to the database.

    Computes projected FTE_Avail and Capacity values for the target month.

    Args:
        forecast_id: ForecastModel primary key
        month_key: Target month in "YYYY-MM" format
        weeks: List of RampWeek Pydantic objects

    Returns:
        Dict with current, projected, and diff values
    """
    db_manager = core_utils.get_db_manager(
        ForecastModel,
        limit=1,
        skip=0,
        select_columns=None
    )

    with db_manager.SessionLocal() as session:
        row = _get_forecast_row(forecast_id, session)
        suffix, month_label = _resolve_month_suffix(row, month_key)

        target_cph = float(row.Centene_Capacity_Plan_Target_CPH or 0)
        main_lob = row.Centene_Capacity_Plan_Main_LOB or ""
        case_type = row.Centene_Capacity_Plan_Case_Type or ""

    config = _get_ramp_month_config(month_label, main_lob, case_type)
    total_ramp_capacity, max_ramp_employees = _compute_ramp_totals(weeks, config, target_cph)

    # Re-open session to read current values (avoids detached instance)
    with db_manager.SessionLocal() as session:
        row = _get_forecast_row(forecast_id, session)

        forecast_col = get_forecast_column_name("forecast", suffix)
        fte_req_col = get_forecast_column_name("fte_req", suffix)
        fte_avail_col = get_forecast_column_name("fte_avail", suffix)
        capacity_col = get_forecast_column_name("capacity", suffix)

        current_forecast = getattr(row, forecast_col) or 0
        current_fte_req = getattr(row, fte_req_col) or 0
        current_fte_avail = getattr(row, fte_avail_col) or 0
        current_capacity = getattr(row, capacity_col) or 0

    projected_fte_avail = current_fte_avail + max_ramp_employees
    projected_capacity = round(current_capacity + total_ramp_capacity, 2)
    current_gap = round(current_capacity - current_forecast, 2)
    projected_gap = round(projected_capacity - current_forecast, 2)

    return {
        "success": True,
        "forecast_id": forecast_id,
        "month_key": month_key,
        "month_label": month_label,
        "config_used": config,
        "ramp_summary": {
            "total_ramp_capacity": round(total_ramp_capacity, 2),
            "max_ramp_employees": max_ramp_employees,
            "weeks_count": len(weeks)
        },
        "current": {
            "forecast": current_forecast,
            "fte_required": current_fte_req,
            "fte_available": current_fte_avail,
            "capacity": current_capacity,
            "gap": current_gap,
        },
        "projected": {
            "forecast": current_forecast,
            "fte_required": current_fte_req,
            "fte_available": projected_fte_avail,
            "capacity": projected_capacity,
            "gap": projected_gap,
        },
        "diff": {
            "forecast": 0,
            "fte_required": 0,
            "fte_available": max_ramp_employees,
            "capacity": round(total_ramp_capacity, 2),
            "gap": round(projected_gap - current_gap, 2),
        }
    }


def apply_ramp(
    forecast_id: int,
    month_key: str,
    weeks: List,
    user_notes: Optional[str],
) -> Dict:
    """
    Apply ramp calculation: update ForecastModel and persist RampModel rows.

    A unique ramp_name is system-generated for each call so multiple ramps applied
    to the same (forecast_id, month_key) on the same day are never mixed up.

    Steps:
    1. Generate unique ramp_name
    2. Fetch forecast row and resolve month suffix/label
    3. Compute ramp totals (server-authoritative)
    4. Read snapshot_before from all 24 metric columns
    5. Compute snapshot_after in memory
    6. Write ForecastModel updates (FTE_Avail + Capacity for target month)
    7. Insert RampModel rows (one per week, always new — name is unique per call)
    8. Write history log with field-level changes
    9. Invalidate caches

    Args:
        forecast_id: ForecastModel primary key
        month_key: Target month in "YYYY-MM" format
        weeks: List of RampWeek Pydantic objects
        user_notes: Optional user description for audit trail

    Returns:
        Dict with success flag, ramp_name, fields_updated, and history_log_id
    """
    ramp_name = _generate_ramp_name()
    METRIC_COLUMNS = [
        "Client_Forecast_Month1", "Client_Forecast_Month2", "Client_Forecast_Month3",
        "Client_Forecast_Month4", "Client_Forecast_Month5", "Client_Forecast_Month6",
        "FTE_Required_Month1", "FTE_Required_Month2", "FTE_Required_Month3",
        "FTE_Required_Month4", "FTE_Required_Month5", "FTE_Required_Month6",
        "FTE_Avail_Month1", "FTE_Avail_Month2", "FTE_Avail_Month3",
        "FTE_Avail_Month4", "FTE_Avail_Month5", "FTE_Avail_Month6",
        "Capacity_Month1", "Capacity_Month2", "Capacity_Month3",
        "Capacity_Month4", "Capacity_Month5", "Capacity_Month6",
    ]

    db_manager = core_utils.get_db_manager(
        ForecastModel,
        limit=1,
        skip=0,
        select_columns=None
    )

    with db_manager.SessionLocal() as session:
        row = _get_forecast_row(forecast_id, session)
        suffix, month_label = _resolve_month_suffix(row, month_key)

        target_cph = float(row.Centene_Capacity_Plan_Target_CPH or 0)
        main_lob = row.Centene_Capacity_Plan_Main_LOB or ""
        case_type = row.Centene_Capacity_Plan_Case_Type or ""
        report_month = row.Month
        report_year = row.Year

        # Snapshot before
        snapshot_before = {col: (getattr(row, col) or 0) for col in METRIC_COLUMNS}

        # Compute ramp totals
        config = _get_ramp_month_config(month_label, main_lob, case_type)
        total_ramp_capacity, max_ramp_employees = _compute_ramp_totals(weeks, config, target_cph)

        # Compute snapshot after in memory
        snapshot_after = dict(snapshot_before)
        fte_avail_col = get_forecast_column_name("fte_avail", suffix)
        capacity_col = get_forecast_column_name("capacity", suffix)

        new_fte_avail = snapshot_before[fte_avail_col] + max_ramp_employees
        new_capacity = round(snapshot_before[capacity_col] + total_ramp_capacity)
        snapshot_after[fte_avail_col] = new_fte_avail
        snapshot_after[capacity_col] = new_capacity

        # Write ForecastModel updates
        setattr(row, fte_avail_col, new_fte_avail)
        setattr(row, capacity_col, new_capacity)
        session.add(row)
        session.commit()
        session.refresh(row)

    # Upsert RampModel rows
    ramp_db_manager = core_utils.get_db_manager(
        RampModel,
        limit=10000,
        skip=0,
        select_columns=None
    )

    with ramp_db_manager.SessionLocal() as session:
        for w in weeks:
            # Always insert — ramp_name is unique per apply_ramp call,
            # so there can never be a pre-existing row with this name.
            new_ramp = RampModel(
                forecast_id=forecast_id,
                month_key=month_key,
                ramp_name=ramp_name,
                week_label=w.label,
                start_date=w.startDate,
                end_date=w.endDate,
                working_days=w.workingDays,
                ramp_percent=w.rampPercent,
                employee_count=w.rampEmployees,
                applied_by="system"
            )
            session.add(new_ramp)

        session.commit()

    # Build history record
    months_dict = get_months_dict(report_month, report_year, core_utils)

    # Find the label key for the target month
    target_month_key = None
    for k, v in months_dict.items():
        if v == month_label:
            target_month_key = k
            break

    # Collect modified_fields for the changed month
    modified_fields = [
        f"{month_label}.fte_avail",
        f"{month_label}.capacity"
    ]

    # Build month data dict for extract_specific_changes
    month_data_for_record = {
        "fte_avail": new_fte_avail,
        "fte_avail_change": max_ramp_employees,
        "capacity": new_capacity,
        "capacity_change": round(total_ramp_capacity),
        "forecast": snapshot_before.get(get_forecast_column_name("forecast", suffix), 0),
        "forecast_change": 0,
        "fte_req": snapshot_before.get(get_forecast_column_name("fte_req", suffix), 0),
        "fte_req_change": 0
    }

    record = {
        "main_lob": main_lob,
        "state": row.Centene_Capacity_Plan_State or "",
        "case_type": case_type,
        "case_id": str(row.Centene_Capacity_Plan_Call_Type_ID or row.id),
        "modified_fields": modified_fields,
        month_label: month_data_for_record
    }

    summary_data = {
        "forecast_id": forecast_id,
        "month_key": month_key,
        "month_label": month_label,
        "fte_avail_before": snapshot_before[fte_avail_col],
        "fte_avail_after": new_fte_avail,
        "capacity_before": snapshot_before[capacity_col],
        "capacity_after": new_capacity,
        "total_ramp_capacity": round(total_ramp_capacity, 2),
        "max_ramp_employees": max_ramp_employees
    }

    try:
        history_log_id = create_complete_history_log(
            month=report_month,
            year=report_year,
            change_type=CHANGE_TYPE_RAMP_CALCULATION,
            user="system",
            user_notes=user_notes,
            modified_records=[record],
            months_dict=months_dict,
            summary_data=summary_data
        )
    except Exception as e:
        logger.error(f"History log creation failed (ramp was applied): {e}", exc_info=True)
        history_log_id = None

    # Invalidate caches
    clear_all_caches()

    return {
        "success": True,
        "forecast_id": forecast_id,
        "month_key": month_key,
        "month_label": month_label,
        "ramp_name": ramp_name,
        "fields_updated": [fte_avail_col, capacity_col],
        "fte_avail_before": snapshot_before[fte_avail_col],
        "fte_avail_after": new_fte_avail,
        "capacity_before": snapshot_before[capacity_col],
        "capacity_after": new_capacity,
        "history_log_id": history_log_id
    }


def bulk_preview_ramp(forecast_id: int, month_key: str, ramps: List) -> Dict:
    """
    Preview the combined impact of multiple named ramps.

    Calls preview_ramp() for each ramp entry and aggregates the diffs.

    Args:
        forecast_id: ForecastModel primary key
        month_key: Target month in "YYYY-MM" format
        ramps: List of BulkRampEntry Pydantic objects (ramp_name, weeks, totalRampEmployees)

    Returns:
        Dict with per_ramp_previews and aggregated_diff
    """
    per_ramp_previews = []
    agg_fte = 0.0
    agg_capacity = 0.0
    agg_gap = 0.0

    for ramp in ramps:
        result = preview_ramp(forecast_id, month_key, ramp.weeks)
        per_ramp_previews.append({
            "ramp_name": ramp.ramp_name,
            "current": result["current"],
            "projected": result["projected"],
            "diff": result["diff"],
        })
        agg_fte += result["diff"]["fte_available"]
        agg_capacity += result["diff"]["capacity"]
        agg_gap += result["diff"]["gap"]

    return {
        "success": True,
        "forecast_id": forecast_id,
        "month_key": month_key,
        "per_ramp_previews": per_ramp_previews,
        "aggregated_diff": {
            "fte_available": agg_fte,
            "capacity": round(agg_capacity, 2),
            "gap": round(agg_gap, 2),
        }
    }


def bulk_apply_ramp(forecast_id: int, month_key: str, ramps: List, user_notes: Optional[str]) -> Dict:
    """
    Apply multiple named ramps to the forecast row.

    Applies each ramp via apply_ramp() and writes a single combined history log.

    Args:
        forecast_id: ForecastModel primary key
        month_key: Target month in "YYYY-MM" format
        ramps: List of BulkRampEntry Pydantic objects (ramp_name, weeks, totalRampEmployees)
        user_notes: Optional audit notes (applied to all ramps)

    Returns:
        Dict with ramps_applied, ramps_failed, fields_updated, history_log_id
    """
    ramps_applied = []
    ramps_failed = []
    fields_updated = set()
    history_log_id = None

    for ramp in ramps:
        try:
            result = apply_ramp(
                forecast_id=forecast_id,
                month_key=month_key,
                weeks=ramp.weeks,
                user_notes=user_notes,
            )
            generated_name = result.get("ramp_name", ramp.ramp_name)
            ramps_applied.append({"label": ramp.ramp_name, "ramp_name": generated_name})
            fields_updated.update(result.get("fields_updated", []))
            # Keep the last history_log_id (apply_ramp writes individual logs)
            history_log_id = result.get("history_log_id") or history_log_id
        except Exception as e:
            logger.error(f"bulk_apply_ramp: failed for ramp '{ramp.ramp_name}': {e}", exc_info=True)
            ramps_failed.append(ramp.ramp_name)

    return {
        "success": len(ramps_failed) == 0,
        "forecast_id": forecast_id,
        "month_key": month_key,
        "ramps_applied": ramps_applied,
        "ramps_failed": ramps_failed,
        "fields_updated": sorted(fields_updated),
        "history_log_id": history_log_id,
    }
