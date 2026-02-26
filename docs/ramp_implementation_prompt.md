# Claude Code Prompt — Ramp Calculation FastAPI Implementation

## Task

Plan and implement the Ramp Calculation feature for the `manager_view_fastapi` FastAPI backend.
The full API spec is at: `docs/ramp_calculation_api_spec.md` — read it first.

---

## What to Implement

Three new REST endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/forecasts/{forecast_id}/months/{month_key}/ramp` | Retrieve applied ramp |
| `POST` | `/api/v1/forecasts/{forecast_id}/months/{month_key}/ramp/preview` | Preview ramp impact (no DB write) |
| `POST` | `/api/v1/forecasts/{forecast_id}/months/{month_key}/ramp/apply` | Apply ramp → update DB + history |

---

## Codebase Context

### Project root: `/Users/aswanthvishnu/Projects/manager_view_fastapi/`

### Key files to read before planning:

| File | Why |
|------|-----|
| `code/logics/db.py` | `ForecastModel`, `ForecastMonthsModel`, `MonthConfigurationModel` column names |
| `code/api/routers/edit_view_router.py` | Pattern for preview/apply endpoints |
| `code/logics/history_logger.py` | `create_complete_history_log()` signature |
| `code/logics/config/change_types.py` | Existing constants; add `CHANGE_TYPE_RAMP_CALCULATION = "Ramp Calculation"` |
| `code/logics/cph_update_transformer.py` | Example: how a transformer fetches current DB values and builds preview diffs |
| `code/logics/forecast_updater.py` | Reference for column-level DB writes on `ForecastModel` |
| `code/logics/cache_utils.py` | Cache invalidation helpers to call after apply |
| `main.py` | Where to register the new router |

### Patterns to follow:

1. **Router**: Plain `APIRouter()`, registered in `main.py` via `app.include_router()`.
2. **Pydantic models**: `class Config: extra = "forbid"`. Use `Field(ge=0)`, `Field(min_length=1)`, etc.
3. **Error shape**: `{"success": false, "error": "...", "recommendation": "..."}` via `HTTPException(status_code=N, detail={...})`.
4. **DB session**: `core_utils.get_db_manager(...)` → `with db_manager.SessionLocal() as session:`.
5. **History log**: `create_complete_history_log(month, year, change_type, user, user_notes, modified_records, months_dict, summary_data)`.
6. **Singleton**: `core_utils = get_core_utils()` and `logger = get_logger(__name__)` at module level.

---

## New Files to Create

| File | Purpose |
|------|---------|
| `code/api/routers/ramp_router.py` | 3 endpoint definitions + Pydantic request/response models |
| `code/logics/ramp_calculator.py` | Pure logic: month-key → MonthN resolution, per-week capacity calc, preview computation, DB update, `RampModel` upsert |

## Existing Files to Modify

| File | Change |
|------|--------|
| `code/logics/db.py` | Add `RampModel` SQLModel table (see spec for schema) |
| `code/logics/config/change_types.py` | Add `CHANGE_TYPE_RAMP_CALCULATION = "Ramp Calculation"` + add to `CHANGE_TYPES` list |
| `main.py` | Register `ramp_router` with prefix `/api/v1` |

---

## Calculation Spec

### Month Key → MonthN resolution

`month_key = "2026-01"` → parse year=2026, month=1 → query `ForecastMonthsModel` for `Year=2026`, `Month="January"` → get the MonthN index (e.g., `Month3`) → column suffix is `3`.

### Preview calculation

```
# Per-week capacity  (Occupancy, Shrinkage, Work_Hours from MonthConfigurationModel)
week_capacity = week.rampEmployees × Target_CPH × Work_Hours × Occupancy × (1 - Shrinkage) × week.workingDays

total_ramp_capacity = sum(week_capacity for each week)
max_ramp_employees  = max(week.rampEmployees for week in weeks)

# Additive — ramp is on top of existing values, not a replacement
projected_fte_avail = current_FTE_Avail_MonthN + max_ramp_employees
projected_capacity  = current_Capacity_MonthN + total_ramp_capacity
projected_gap       = projected_capacity - Client_Forecast_MonthN
```

Current values come from `ForecastModel` columns for the resolved MonthN.

### Apply

1. Re-run the same calculation (server-authoritative; do not trust frontend diff).
2. **Snapshot** the full `ForecastModel` row before any writes (all Month1–Month6 columns for `Client_Forecast`, `FTE_Required`, `FTE_Avail`, `Capacity`).
3. `FTE_Avail_MonthN += max_ramp_employees` on the `ForecastModel` row.
4. `Capacity_MonthN += total_ramp_capacity` on the `ForecastModel` row.
5. Upsert each week into `RampModel` — match on `(forecast_id, month_key, ramp_percent, working_days)`: update `employee_count` if found, insert otherwise.
6. Build history log from full-row diff (see **History Log Pattern** below) and call `create_complete_history_log()` with `change_type = CHANGE_TYPE_RAMP_CALCULATION`.
7. Invalidate relevant caches.

### History Log Pattern

Do **not** hardcode which fields changed. Instead, snapshot before → project after → diff all fields across all 6 months → log only fields where `old_value != new_value`.

**Step 1 — Snapshot before update:**
```python
# Read entire row into a plain dict before any DB writes
snapshot_before = {
    "FTE_Avail_Month1": row.FTE_Avail_Month1,
    "Capacity_Month1":  row.Capacity_Month1,
    # ... all Month1–Month6 for Client_Forecast, FTE_Required, FTE_Avail, Capacity
}
```

**Step 2 — Project after update (in memory):**
```python
snapshot_after = dict(snapshot_before)
snapshot_after[f"FTE_Avail_Month{suffix}"] += max_ramp_employees
snapshot_after[f"Capacity_Month{suffix}"]  += total_ramp_capacity
```

**Step 3 — Diff and build `modified_records`:**

Iterate all tracked fields across all 6 months. Collect only fields where `old != new`. Build the `modified_records` entry in the format `extract_specific_changes()` expects — dot-notation `modified_fields` list, plus per-month data dicts with `field_value` and `field_change`:

```python
TRACKED_FIELDS = ["forecast", "fte_req", "fte_avail", "capacity"]
COL_MAP = {
    "forecast": "Client_Forecast_Month{n}",
    "fte_req":  "FTE_Required_Month{n}",
    "fte_avail":"FTE_Avail_Month{n}",
    "capacity": "Capacity_Month{n}",
}

month_data = {}        # e.g. {"Jan-26": {"fte_avail": 27, "fte_avail_change": 9, ...}}
modified_fields = []   # e.g. ["Jan-26.fte_avail", "Jan-26.capacity"]

for suffix, month_label in months_dict.items():   # months_dict from ForecastMonthsModel
    n = suffix.replace("month", "")               # "month1" → "1"
    month_entry = {}
    for field, col_tpl in COL_MAP.items():
        col = col_tpl.format(n=n)
        old = snapshot_before[col]
        new = snapshot_after[col]
        delta = new - old
        month_entry[field]            = new
        month_entry[f"{field}_change"]= delta
        if delta != 0:
            modified_fields.append(f"{month_label}.{field}")
    month_data[month_label] = month_entry

record = {
    "main_lob":        row.Centene_Capacity_Plan_Main_LOB,
    "state":           row.Centene_Capacity_Plan_State,
    "case_type":       row.Centene_Capacity_Plan_Case_Type,
    "case_id":         str(row.id),
    "modified_fields": modified_fields,
    **month_data,     # spreads {"Jan-26": {...}, "Feb-26": {...}, ...}
}
```

Pass `[record]` as `modified_records` to `create_complete_history_log()`. The function calls `extract_specific_changes()` internally, which iterates `modified_fields` to emit one history change row per changed field. For a typical ramp apply this will be exactly two entries (`Jan-26.fte_avail` and `Jan-26.capacity`), but the pattern handles edge cases without hardcoding.

---

## Validation Rules

- `month_key` format: `YYYY-MM` (validate via `datetime.strptime` or regex).
- `forecast_id` must exist in `ForecastModel`.
- Resolved month label must be one of the 6 months in the forecast row's report period.
- `totalRampEmployees` must exactly equal `sum(w.rampEmployees for w in weeks)`.
- `rampPercent` per week: `0 ≤ value ≤ 100`.
- `rampEmployees` per week: `≥ 0` and must be a whole number (integer, no decimals) — Pydantic `int` field enforces this at `422`.
- `workingDays` per week: `≥ 0`.
- At least 1 week required.
- At least one week must have `rampEmployees > 0` — all-zero submissions are rejected with `400`.

---

## Important Constraints

- **No auth middleware** — use `user="system"` in history log.
- **No `UpdateOperation`** — implement the apply flow directly (direct session writes + `create_complete_history_log()`).
- **DB migrations**: `SQLModel.metadata.create_all(engine)` runs on startup — adding `RampModel` to `db.py` is sufficient.
- **Do not break existing endpoints** — the new router is additive only.

---

## Deliverable

1. Present an implementation plan: files to create/modify, function signatures, calculation flow, DB schema.
2. Await approval, then implement all files.
3. After implementation, verify endpoints are registered in `main.py` and `RampModel` is importable from `code.logics.db`.
