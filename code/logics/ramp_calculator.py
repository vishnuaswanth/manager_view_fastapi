"""
Ramp calculation logic for weekly staffing ramp-ups on forecast rows.

Provides preview and apply operations that compute capacity impact from
per-week employee ramp schedules and persist results to ForecastModel + RampModel.

Capacity formula (per week):
    capacity = employees × target_cph × work_hours × (1 - shrinkage) × working_days
    Note: occupancy is NOT used in capacity calculations.

Apply approach (base + recompute):
    base = current_db_value - sum(all_existing_ramp_contributions)
    final = base + sum(all_new_ramp_contributions)
This ensures edits to existing ramps produce correct results (not additive stacking).
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

    Returns:
        Unique ramp name string, e.g. "Ramp-20260110-a1b2c3d4"
    """
    return f"Ramp-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8]}"


def _compute_ramp_totals(weeks: List, config: Dict, target_cph: float) -> Tuple[float, int]:
    """
    Compute total capacity and max ramp employees across all weeks.

    Capacity per week = employees × target_cph × work_hours × (1 - shrinkage) × working_days
    Note: occupancy is NOT used in this calculation.

    Args:
        weeks: List of RampWeek Pydantic objects (with rampEmployees, workingDays attributes)
        config: Month config dict with shrinkage, work_hours keys
        target_cph: Cases per hour from ForecastModel

    Returns:
        Tuple of (total_ramp_capacity: float, max_ramp_employees: int)
    """
    per_week = [
        w.rampEmployees * target_cph * config["work_hours"]
        * (1 - config["shrinkage"]) * w.workingDays
        for w in weeks
    ]
    total_ramp_capacity = sum(per_week)
    max_ramp_employees = max((w.rampEmployees for w in weeks), default=0)
    return total_ramp_capacity, max_ramp_employees


def _compute_old_ramp_contributions(
    rows_data: List[Dict],
    config: Dict,
    target_cph: float,
) -> Tuple[Dict[str, Dict], int, float]:
    """
    Group existing DB rows by ramp_name and compute FTE + capacity contributions.

    Uses the same formula as _compute_ramp_totals (no occupancy):
        capacity = employee_count × target_cph × work_hours × (1 - shrinkage) × working_days

    Args:
        rows_data: List of dicts with keys: ramp_name, employee_count, working_days
        config: Month config dict with shrinkage, work_hours keys
        target_cph: Cases per hour from ForecastModel

    Returns:
        stats: {ramp_name: {"fte": int, "cap": float}}
        total_fte: sum of max-employee-count per ramp group
        total_cap: sum of capacity contribution per ramp group
    """
    grouped = defaultdict(list)
    for r in rows_data:
        grouped[r["ramp_name"]].append(r)

    stats = {}
    total_fte = 0
    total_cap = 0.0

    for rn, rows in grouped.items():
        g_fte = max(r["employee_count"] for r in rows)
        g_cap = sum(
            r["employee_count"] * target_cph * config["work_hours"]
            * (1 - config["shrinkage"]) * r["working_days"]
            for r in rows
        )
        stats[rn] = {"fte": g_fte, "cap": g_cap}
        total_fte += g_fte
        total_cap += g_cap

    return stats, total_fte, total_cap


def _load_ramp_rows_as_dicts(session, forecast_id: int, month_key: str) -> List[Dict]:
    """
    Load all RampModel rows for (forecast_id, month_key) and return as plain dicts.

    Using dicts avoids DetachedInstanceError when the session closes.

    Returns:
        List of dicts with keys: ramp_name, employee_count, working_days
    """
    rows = session.query(RampModel).filter(
        RampModel.forecast_id == forecast_id,
        RampModel.month_key == month_key
    ).all()
    return [
        {
            "ramp_name": r.ramp_name,
            "employee_count": r.employee_count,
            "working_days": r.working_days,
        }
        for r in rows
    ]


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

    # Verify forecast row exists
    forecast_db_manager = core_utils.get_db_manager(ForecastModel, limit=1, skip=0, select_columns=None)
    with forecast_db_manager.SessionLocal() as fsession:
        _get_forecast_row(forecast_id, fsession)

    with db_manager.SessionLocal() as session:
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


def preview_ramp(
    forecast_id: int,
    month_key: str,
    weeks: List,
    ramp_name: str = "Default",
) -> Dict:
    """
    Preview the impact of applying/replacing a named ramp without writing to the database.

    Uses aggregate delta approach:
        delta = new_contribution(for this ramp_name) - old_contribution(for this ramp_name)
        projected = current_db_value + delta

    This correctly handles edits to existing ramps (replacing, not stacking).

    Args:
        forecast_id: ForecastModel primary key
        month_key: Target month in "YYYY-MM" format
        weeks: List of RampWeek Pydantic objects
        ramp_name: Name of the ramp being previewed (default "Default")

    Returns:
        Dict with current, projected, and diff values
    """
    db_manager = core_utils.get_db_manager(ForecastModel, limit=1, skip=0, select_columns=None)
    ramp_db_manager = core_utils.get_db_manager(RampModel, limit=10000, skip=0, select_columns=None)

    # Read forecast row fields
    with db_manager.SessionLocal() as session:
        row = _get_forecast_row(forecast_id, session)
        suffix, month_label = _resolve_month_suffix(row, month_key)

        target_cph = float(row.Centene_Capacity_Plan_Target_CPH or 0)
        main_lob = row.Centene_Capacity_Plan_Main_LOB or ""
        case_type = row.Centene_Capacity_Plan_Case_Type or ""

        forecast_col = get_forecast_column_name("forecast", suffix)
        fte_req_col = get_forecast_column_name("fte_req", suffix)
        fte_avail_col = get_forecast_column_name("fte_avail", suffix)
        capacity_col = get_forecast_column_name("capacity", suffix)

        current_forecast = getattr(row, forecast_col) or 0
        current_fte_req = getattr(row, fte_req_col) or 0
        current_fte_avail = getattr(row, fte_avail_col) or 0
        current_capacity = getattr(row, capacity_col) or 0

    # Get config once (used for both old reverse-calc and new forward-calc)
    config = _get_ramp_month_config(month_label, main_lob, case_type)

    # Load existing rows for THIS ramp_name only
    with ramp_db_manager.SessionLocal() as session:
        old_rows_data = [
            {"ramp_name": r.ramp_name, "employee_count": r.employee_count, "working_days": r.working_days}
            for r in session.query(RampModel).filter(
                RampModel.forecast_id == forecast_id,
                RampModel.month_key == month_key,
                RampModel.ramp_name == ramp_name
            ).all()
        ]

    # Compute old contribution for this ramp_name
    old_fte = max((r["employee_count"] for r in old_rows_data), default=0)
    old_cap = sum(
        r["employee_count"] * target_cph * config["work_hours"]
        * (1 - config["shrinkage"]) * r["working_days"]
        for r in old_rows_data
    )

    # Compute new contribution from payload
    new_cap, new_fte = _compute_ramp_totals(weeks, config, target_cph)

    # Aggregate delta
    delta_fte = new_fte - old_fte
    delta_cap = new_cap - old_cap

    projected_fte_avail = current_fte_avail + delta_fte
    projected_capacity = round(current_capacity + delta_cap, 2)
    current_gap = round(current_capacity - current_forecast, 2)
    projected_gap = round(projected_capacity - current_forecast, 2)

    return {
        "success": True,
        "forecast_id": forecast_id,
        "month_key": month_key,
        "month_label": month_label,
        "ramp_name": ramp_name,
        "config_used": config,
        "ramp_summary": {
            "total_ramp_capacity": round(new_cap, 2),
            "max_ramp_employees": new_fte,
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
            "fte_available": delta_fte,
            "capacity": round(delta_cap, 2),
            "gap": round(projected_gap - current_gap, 2),
        }
    }


def apply_ramp(
    forecast_id: int,
    month_key: str,
    weeks: List,
    user_notes: Optional[str],
    ramp_name: str = "Default",
) -> Dict:
    """
    Apply a named ramp: update ForecastModel and persist RampModel rows.

    Uses base + recompute approach:
        1. Load ALL existing RampModel rows → compute total_old contributions
        2. base = current_db - total_old  (strips all prior ramp contributions)
        3. Delete rows for this ramp_name; insert new rows
        4. Load ALL remaining rows → compute total_new contributions
        5. final = base + total_new

    This correctly handles both new ramps and edits to existing ramps.

    Args:
        forecast_id: ForecastModel primary key
        month_key: Target month in "YYYY-MM" format
        weeks: List of RampWeek Pydantic objects
        user_notes: Optional user description for audit trail
        ramp_name: Name of the ramp (default "Default"). Existing rows with this
                   name are replaced; other ramps in the same month are untouched.

    Returns:
        Dict with success flag, ramp_name, fields_updated, and history_log_id
    """
    db_manager = core_utils.get_db_manager(ForecastModel, limit=1, skip=0, select_columns=None)
    ramp_db_manager = core_utils.get_db_manager(RampModel, limit=10000, skip=0, select_columns=None)

    # --- Step 1: Read forecast row ---
    with db_manager.SessionLocal() as session:
        row = _get_forecast_row(forecast_id, session)
        suffix, month_label = _resolve_month_suffix(row, month_key)

        target_cph = float(row.Centene_Capacity_Plan_Target_CPH or 0)
        main_lob = row.Centene_Capacity_Plan_Main_LOB or ""
        case_type = row.Centene_Capacity_Plan_Case_Type or ""
        report_month = row.Month
        report_year = row.Year
        # Capture for history log (avoid DetachedInstanceError later)
        row_state = row.Centene_Capacity_Plan_State or ""
        row_case_id = str(row.Centene_Capacity_Plan_Call_Type_ID or row.id)

        fte_avail_col = get_forecast_column_name("fte_avail", suffix)
        capacity_col = get_forecast_column_name("capacity", suffix)
        forecast_col = get_forecast_column_name("forecast", suffix)
        fte_req_col = get_forecast_column_name("fte_req", suffix)

        snapshot_before = {col: (getattr(row, col) or 0) for col in METRIC_COLUMNS}
        before_fte = snapshot_before[fte_avail_col]
        before_cap = snapshot_before[capacity_col]

    # --- Step 2: Get config once ---
    config = _get_ramp_month_config(month_label, main_lob, case_type)

    # --- Step 3: Load ALL existing rows to compute base ---
    with ramp_db_manager.SessionLocal() as session:
        existing_rows_data = _load_ramp_rows_as_dicts(session, forecast_id, month_key)

    _, total_old_fte, total_old_cap = _compute_old_ramp_contributions(
        existing_rows_data, config, target_cph
    )

    # base = current_db - total_old (strips all prior ramp contributions)
    base_fte = before_fte - total_old_fte
    base_cap = before_cap - total_old_cap

    if base_fte < 0:
        logger.warning(
            f"apply_ramp: base_fte={base_fte} < 0 for forecast_id={forecast_id}, "
            f"month_key={month_key}. Data inconsistency — clamping to 0."
        )
        base_fte = 0
    if base_cap < 0:
        logger.warning(
            f"apply_ramp: base_cap={base_cap} < 0 for forecast_id={forecast_id}, "
            f"month_key={month_key}. Data inconsistency — clamping to 0."
        )
        base_cap = 0

    # --- Step 4: Delete old rows for this ramp_name; insert new rows ---
    with ramp_db_manager.SessionLocal() as session:
        session.query(RampModel).filter(
            RampModel.forecast_id == forecast_id,
            RampModel.month_key == month_key,
            RampModel.ramp_name == ramp_name
        ).delete(synchronize_session=False)

        for w in weeks:
            session.add(RampModel(
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
            ))
        session.commit()

    # --- Step 5: Load ALL remaining rows → compute total_new ---
    with ramp_db_manager.SessionLocal() as session:
        remaining_rows_data = _load_ramp_rows_as_dicts(session, forecast_id, month_key)

    _, total_new_fte, total_new_cap = _compute_old_ramp_contributions(
        remaining_rows_data, config, target_cph
    )

    # final = base + total_new
    final_fte = base_fte + total_new_fte
    final_cap = round(base_cap + total_new_cap, 2)

    # --- Step 6: Write ForecastModel ---
    with db_manager.SessionLocal() as session:
        row = _get_forecast_row(forecast_id, session)
        setattr(row, fte_avail_col, final_fte)
        setattr(row, capacity_col, final_cap)
        session.add(row)
        session.commit()

    # --- Step 7: Write history log ---
    months_dict = get_months_dict(report_month, report_year, core_utils)

    month_data_for_record = {
        "fte_avail": final_fte,
        "fte_avail_change": final_fte - before_fte,
        "capacity": final_cap,
        "capacity_change": round(final_cap - before_cap, 2),
        "forecast": snapshot_before.get(forecast_col, 0),
        "forecast_change": 0,
        "fte_req": snapshot_before.get(fte_req_col, 0),
        "fte_req_change": 0
    }

    record = {
        "main_lob": main_lob,
        "state": row_state,
        "case_type": case_type,
        "case_id": row_case_id,
        "ramp_name": ramp_name,
        "modified_fields": [f"{month_label}.fte_avail", f"{month_label}.capacity"],
        month_label: month_data_for_record
    }

    summary_data = {
        "forecast_id": forecast_id,
        "month_key": month_key,
        "month_label": month_label,
        "ramp_name": ramp_name,
        "fte_avail_before": before_fte,
        "fte_avail_after": final_fte,
        "capacity_before": round(before_cap, 2),
        "capacity_after": final_cap,
        "total_ramp_fte_delta": final_fte - before_fte,
        "total_ramp_cap_delta": round(final_cap - before_cap, 2),
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
        "fte_avail_before": before_fte,
        "fte_avail_after": final_fte,
        "capacity_before": round(before_cap, 2),
        "capacity_after": final_cap,
        "history_log_id": history_log_id
    }


def bulk_preview_ramp(forecast_id: int, month_key: str, ramps: List) -> Dict:
    """
    Preview the combined impact of multiple named ramps using full aggregate delta.

    Single config fetch and single DB query for all old rows ensures consistent
    calculation across all ramps.

    Formula:
        delta = sum(new_contributions) - sum(old_contributions)
        projected = current_db_value + delta

    Args:
        forecast_id: ForecastModel primary key
        month_key: Target month in "YYYY-MM" format
        ramps: List of BulkRampEntry Pydantic objects (ramp_name, weeks, totalRampEmployees)

    Returns:
        Dict with per_ramp_previews and aggregated diff vs current DB values
    """
    db_manager = core_utils.get_db_manager(ForecastModel, limit=1, skip=0, select_columns=None)
    ramp_db_manager = core_utils.get_db_manager(RampModel, limit=10000, skip=0, select_columns=None)

    # --- Setup: read forecast row fields ---
    with db_manager.SessionLocal() as session:
        row = _get_forecast_row(forecast_id, session)
        suffix, month_label = _resolve_month_suffix(row, month_key)

        target_cph = float(row.Centene_Capacity_Plan_Target_CPH or 0)
        main_lob = row.Centene_Capacity_Plan_Main_LOB or ""
        case_type = row.Centene_Capacity_Plan_Case_Type or ""

        fte_avail_col = get_forecast_column_name("fte_avail", suffix)
        capacity_col = get_forecast_column_name("capacity", suffix)
        forecast_col = get_forecast_column_name("forecast", suffix)

        current_fte = getattr(row, fte_avail_col) or 0
        current_cap = getattr(row, capacity_col) or 0

    # --- Config once (single call for all contributions) ---
    config = _get_ramp_month_config(month_label, main_lob, case_type)

    # --- Load ALL existing DB rows in ONE query ---
    with ramp_db_manager.SessionLocal() as session:
        old_rows_data = _load_ramp_rows_as_dicts(session, forecast_id, month_key)

    old_ramp_stats, total_old_fte, total_old_cap = _compute_old_ramp_contributions(
        old_rows_data, config, target_cph
    )

    # --- Compute new totals from payload ---
    new_ramp_stats = {}
    total_new_fte = 0
    total_new_cap = 0.0

    for ramp in ramps:
        ramp_cap, ramp_max_fte = _compute_ramp_totals(ramp.weeks, config, target_cph)
        new_ramp_stats[ramp.ramp_name] = {"fte": ramp_max_fte, "cap": ramp_cap}
        total_new_fte += ramp_max_fte
        total_new_cap += ramp_cap

    # --- Compute aggregate deltas ---
    delta_fte = total_new_fte - total_old_fte
    delta_cap = total_new_cap - total_old_cap

    projected_fte = current_fte + delta_fte
    projected_cap = round(current_cap + delta_cap, 2)

    # --- Build per-ramp previews ---
    per_ramp_previews = []
    for ramp in ramps:
        old_stat = old_ramp_stats.get(ramp.ramp_name, {"fte": 0, "cap": 0.0})
        new_stat = new_ramp_stats[ramp.ramp_name]

        old_fte = old_stat["fte"]
        old_cap_val = old_stat["cap"]
        new_fte = new_stat["fte"]
        new_cap_val = new_stat["cap"]

        per_ramp_previews.append({
            "ramp_name": ramp.ramp_name,
            "current": {
                "fte_available": old_fte,
                "capacity": round(old_cap_val, 2),
            },
            "projected": {
                "fte_available": new_fte,
                "capacity": round(new_cap_val, 2),
            },
            "diff": {
                "fte_available": new_fte - old_fte,
                "capacity": round(new_cap_val - old_cap_val, 2),
            },
        })

    return {
        "success": True,
        "forecast_id": forecast_id,
        "month_key": month_key,
        "per_ramp_previews": per_ramp_previews,
        "aggregated_diff": {
            "fte_available": delta_fte,
            "capacity": round(delta_cap, 2),
        },
        "aggregated": {
            "fte_available_before": current_fte,
            "fte_available_after": projected_fte,
            "fte_available_delta": delta_fte,
            "capacity_before": round(current_cap, 2),
            "capacity_after": projected_cap,
            "capacity_delta": round(delta_cap, 2),
        }
    }


def bulk_apply_ramp(
    forecast_id: int,
    month_key: str,
    ramps: List,
    user_notes: Optional[str],
) -> Dict:
    """
    Apply multiple named ramps using delete-all + insert-all approach.

    Algorithm:
        1. Compute base = current_db - sum(all old ramp contributions)
        2. Delete ALL existing RampModel rows for (forecast_id, month_key)
        3. Insert new rows for all submitted ramps
        4. final = base + sum(all new ramp contributions)
        5. Write ForecastModel once; write ONE history log for all ramps

    Args:
        forecast_id: ForecastModel primary key
        month_key: Target month in "YYYY-MM" format
        ramps: List of BulkRampEntry Pydantic objects (ramp_name, weeks, totalRampEmployees)
        user_notes: Optional audit notes

    Returns:
        Dict with ramps_applied, ramps_failed, fields_updated, history_log_id
    """
    db_manager = core_utils.get_db_manager(ForecastModel, limit=1, skip=0, select_columns=None)
    ramp_db_manager = core_utils.get_db_manager(RampModel, limit=10000, skip=0, select_columns=None)

    # --- Step 1: Read forecast row ---
    with db_manager.SessionLocal() as session:
        row = _get_forecast_row(forecast_id, session)
        suffix, month_label = _resolve_month_suffix(row, month_key)

        target_cph = float(row.Centene_Capacity_Plan_Target_CPH or 0)
        main_lob = row.Centene_Capacity_Plan_Main_LOB or ""
        case_type = row.Centene_Capacity_Plan_Case_Type or ""
        report_month = row.Month
        report_year = row.Year
        # Capture for history log
        row_state = row.Centene_Capacity_Plan_State or ""
        row_case_id = str(row.Centene_Capacity_Plan_Call_Type_ID or row.id)

        fte_avail_col = get_forecast_column_name("fte_avail", suffix)
        capacity_col = get_forecast_column_name("capacity", suffix)
        forecast_col = get_forecast_column_name("forecast", suffix)
        fte_req_col = get_forecast_column_name("fte_req", suffix)

        snapshot_before = {col: (getattr(row, col) or 0) for col in METRIC_COLUMNS}
        before_fte = snapshot_before[fte_avail_col]
        before_cap = snapshot_before[capacity_col]

    # --- Step 2: Config once ---
    config = _get_ramp_month_config(month_label, main_lob, case_type)

    # --- Step 3: Load ALL existing rows to compute base ---
    with ramp_db_manager.SessionLocal() as session:
        existing_rows_data = _load_ramp_rows_as_dicts(session, forecast_id, month_key)

    _, total_old_fte, total_old_cap = _compute_old_ramp_contributions(
        existing_rows_data, config, target_cph
    )

    base_fte = before_fte - total_old_fte
    base_cap = before_cap - total_old_cap

    if base_fte < 0:
        logger.warning(
            f"bulk_apply_ramp: base_fte={base_fte} < 0 for forecast_id={forecast_id}, "
            f"month_key={month_key}. Data inconsistency — clamping to 0."
        )
        base_fte = 0
    if base_cap < 0:
        logger.warning(
            f"bulk_apply_ramp: base_cap={base_cap} < 0 for forecast_id={forecast_id}, "
            f"month_key={month_key}. Data inconsistency — clamping to 0."
        )
        base_cap = 0

    # --- Step 4: DELETE ALL rows; INSERT all new rows (single transaction) ---
    now = datetime.utcnow()
    with ramp_db_manager.SessionLocal() as session:
        session.query(RampModel).filter(
            RampModel.forecast_id == forecast_id,
            RampModel.month_key == month_key
        ).delete(synchronize_session=False)

        for ramp in ramps:
            for w in ramp.weeks:
                session.add(RampModel(
                    forecast_id=forecast_id,
                    month_key=month_key,
                    ramp_name=ramp.ramp_name,
                    week_label=w.label,
                    start_date=w.startDate,
                    end_date=w.endDate,
                    working_days=w.workingDays,
                    ramp_percent=w.rampPercent,
                    employee_count=w.rampEmployees,
                    applied_at=now,
                    applied_by="system"
                ))
        session.commit()

    # --- Step 5: Compute total_new directly from payload (same config) ---
    total_new_fte = 0
    total_new_cap = 0.0
    for ramp in ramps:
        ramp_cap, ramp_max_fte = _compute_ramp_totals(ramp.weeks, config, target_cph)
        total_new_fte += ramp_max_fte
        total_new_cap += ramp_cap

    # final = base + total_new
    final_fte = base_fte + total_new_fte
    final_cap = round(base_cap + total_new_cap, 2)

    # --- Step 6: Write ForecastModel (single write) ---
    with db_manager.SessionLocal() as session:
        row = _get_forecast_row(forecast_id, session)
        setattr(row, fte_avail_col, final_fte)
        setattr(row, capacity_col, final_cap)
        session.add(row)
        session.commit()

    # --- Step 7: Write ONE history log for all ramps ---
    months_dict = get_months_dict(report_month, report_year, core_utils)
    ramp_names = [r.ramp_name for r in ramps]

    month_data_for_record = {
        "fte_avail": final_fte,
        "fte_avail_change": final_fte - before_fte,
        "capacity": final_cap,
        "capacity_change": round(final_cap - before_cap, 2),
        "forecast": snapshot_before.get(forecast_col, 0),
        "forecast_change": 0,
        "fte_req": snapshot_before.get(fte_req_col, 0),
        "fte_req_change": 0
    }

    record = {
        "main_lob": main_lob,
        "state": row_state,
        "case_type": case_type,
        "case_id": row_case_id,
        "ramp_names": ramp_names,
        "modified_fields": [f"{month_label}.fte_avail", f"{month_label}.capacity"],
        month_label: month_data_for_record
    }

    summary_data = {
        "forecast_id": forecast_id,
        "month_key": month_key,
        "month_label": month_label,
        "ramp_names": ramp_names,
        "fte_avail_before": before_fte,
        "fte_avail_after": final_fte,
        "capacity_before": round(before_cap, 2),
        "capacity_after": final_cap,
        "total_ramp_fte_delta": final_fte - before_fte,
        "total_ramp_cap_delta": round(final_cap - before_cap, 2),
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
        logger.error(f"History log creation failed (bulk ramp was applied): {e}", exc_info=True)
        history_log_id = None

    # Invalidate caches
    clear_all_caches()

    return {
        "success": True,
        "forecast_id": forecast_id,
        "month_key": month_key,
        "ramps_applied": ramp_names,
        "ramps_failed": [],
        "fields_updated": [fte_avail_col, capacity_col],
        "history_log_id": history_log_id,
    }
