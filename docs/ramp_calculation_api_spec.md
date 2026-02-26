# Ramp Calculation API Spec

## Overview

Three new endpoints to support weekly staffing ramp calculations for individual forecast rows.
A "ramp" adds incremental capacity for a target month: capacity is calculated independently for each week using that week's ramp employees and working days, then summed across all weeks. The effective FTE increase is the maximum ramp-employee count across any single week, which is added on top of the existing `FTE_Avail`.

**Change type constant to add:** `CHANGE_TYPE_RAMP_CALCULATION = "Ramp Calculation"`

---

## Data Model Reference

The `ForecastModel` stores data in flat columns:
- `Client_Forecast_Month1` – `Client_Forecast_Month6`
- `FTE_Required_Month1` – `FTE_Required_Month6`
- `FTE_Avail_Month1` – `FTE_Avail_Month6`
- `Capacity_Month1` – `Capacity_Month6`

The `ForecastMonthsModel` maps `Month1`–`Month6` to their actual month labels (e.g., `"Apr-25"`).

The `MonthConfigurationModel` stores per-month config:
- `Working_Days`, `Occupancy`, `Shrinkage`, `Work_Hours` — used for FTE recalculation.

The target forecast row is identified by its integer primary key (`id` on `ForecastModel`).

**Month key format:** `"YYYY-MM"` (e.g., `"2026-01"` for January 2026).
The backend must resolve this to the correct MonthN column by joining `ForecastMonthsModel`.

---

## Endpoint 1 — GET Applied Ramp

### `GET /api/v1/forecasts/{forecast_id}/months/{month_key}/ramp`

Retrieves all ramp week records stored for a specific forecast row and month.
The response is assembled by querying all `RampModel` rows matching `(forecast_id, month_key)`:
- `maxRampEmployees` = `max(employee_count)` across those rows
- `totalRampEmployees` = `sum(employee_count)` across those rows
- `ramp_applied` = `true` when at least one matching row exists

**Path Parameters:**
| Param | Type | Example | Description |
|-------|------|---------|-------------|
| `forecast_id` | int | `42` | `ForecastModel.id` |
| `month_key` | str | `2026-01` | Format: `YYYY-MM` |

**Success Response `200`:**

```json
{
  "success": true,
  "forecast_id": 42,
  "month_key": "2026-01",
  "month_label": "Jan-26",
  "row_label": "Amisys Medicaid Domestic / Claims Processing / CA",
  "ramp_applied": true,
  "ramp_data": {
    "maxRampEmployees": 9,
    "totalRampEmployees": 13,
    "weeks": [
      {
        "label": "Jan-1-2026",
        "startDate": "2026-01-01",
        "endDate": "2026-01-04",
        "workingDays": 2,
        "rampPercent": 50,
        "rampEmployees": 4
      },
      {
        "label": "Jan-5-2026",
        "startDate": "2026-01-05",
        "endDate": "2026-01-11",
        "workingDays": 5,
        "rampPercent": 80,
        "rampEmployees": 9
      }
    ]
  }
}
```

**No Ramp Applied Response `200`:**

```json
{
  "success": true,
  "forecast_id": 42,
  "month_key": "2026-01",
  "month_label": "Jan-26",
  "row_label": "Amisys Medicaid Domestic / Claims Processing / CA",
  "ramp_applied": false,
  "ramp_data": null
}
```

**Error Responses:**

| Status | Condition | `error` field |
|--------|-----------|---------------|
| `404` | `forecast_id` not found | `"Forecast record {id} not found"` |
| `400` | `month_key` not in this report's 6 months | `"Month '2026-01' is not in this report period"` |
| `422` | Malformed `month_key` (not YYYY-MM) | validation error |
| `500` | DB error | `"Database operation failed"` |

---

## Endpoint 2 — Preview Ramp Calculation

### `POST /api/v1/forecasts/{forecast_id}/months/{month_key}/ramp/preview`

Calculates the projected impact of applying a ramp without persisting anything.
Returns current values, projected values, and the diff for user confirmation.

**Path Parameters:** Same as Endpoint 1.

**Request Body:**

```json
{
  "weeks": [
    {
      "label": "Jan-1-2026",
      "startDate": "2026-01-01",
      "endDate": "2026-01-04",
      "workingDays": 2,
      "rampPercent": 50,
      "rampEmployees": 4
    },
    {
      "label": "Jan-5-2026",
      "startDate": "2026-01-05",
      "endDate": "2026-01-11",
      "workingDays": 5,
      "rampPercent": 80,
      "rampEmployees": 9
    }
  ],
  "totalRampEmployees": 13
}
```

**Request Body Pydantic Model:**

```python
class RampWeek(BaseModel):
    label: str = Field(min_length=1)          # "Jan-1-2026"
    startDate: str = Field(min_length=10)     # "2026-01-01" ISO date
    endDate: str = Field(min_length=10)       # "2026-01-04" ISO date
    workingDays: int = Field(ge=0)            # count of Mon-Fri in range
    rampPercent: float = Field(ge=0, le=100)  # 0-100
    rampEmployees: int = Field(ge=0)          # employees for this week

    class Config:
        extra = "forbid"

class RampPreviewRequest(BaseModel):
    weeks: List[RampWeek] = Field(min_items=1)
    totalRampEmployees: int = Field(ge=0)

    class Config:
        extra = "forbid"
```

**Calculation Logic:**

The preview computes capacity week by week and sums the results. FTE_Avail is increased by the peak-week headcount.

```
# Per-week capacity (MonthConfigurationModel supplies Occupancy, Shrinkage, Work_Hours)
week_capacity = week.rampEmployees * Target_CPH * Work_Hours * Occupancy
                * (1 - Shrinkage) * week.workingDays

# Aggregate ramp capacity across all weeks
total_ramp_capacity = sum(week_capacity for each week)

# Peak headcount across weeks drives the FTE adjustment
max_ramp_employees = max(week.rampEmployees for week in weeks)

# Current values come from ForecastModel columns for the target MonthN
# Projected FTE_Avail   = current_FTE_Avail + max_ramp_employees
#   (ramp headcount is additive; it does not replace existing availability)
# Projected FTE_Required = unchanged (ramp affects availability, not requirement)
# Projected Capacity    = current_Capacity + total_ramp_capacity
# Projected GAP         = Projected_Capacity - Client_Forecast
```

**Success Response `200`:**

```json
{
  "success": true,
  "forecast_id": 42,
  "month_key": "2026-01",
  "month_label": "Jan-26",
  "row_label": "Amisys Medicaid Domestic / Claims Processing / CA",
  "preview": {
    "current": {
      "forecast": 12000,
      "fte_required": 15,
      "fte_available": 18,
      "capacity": 14400,
      "gap": 2400
    },
    "projected": {
      "forecast": 12000,
      "fte_required": 15,
      "fte_available": 27,
      "capacity": 21600,
      "gap": 9600
    },
    "diff": {
      "forecast": 0,
      "fte_required": 0,
      "fte_available": 9,
      "capacity": 7200,
      "gap": 7200
    }
  },
  "ramp_summary": {
    "maxRampEmployees": 9,
    "totalRampEmployees": 13,
    "weekCount": 2,
    "totalWorkingDays": 7,
    "totalRampCapacity": 7200
  }
}
```

**Error Responses:**

| Status | Condition |
|--------|-----------|
| `404` | forecast_id not found |
| `400` | month_key not in report period |
| `400` | `totalRampEmployees` does not match sum of `rampEmployees` across weeks |
| `400` | All weeks have `rampEmployees = 0` (at least one must be > 0) |
| `422` | Validation failure (out-of-range values, or decimal `rampEmployees`) |
| `500` | DB/calculation error |

---

## Endpoint 3 — Apply Ramp Calculation

### `POST /api/v1/forecasts/{forecast_id}/months/{month_key}/ramp/apply`

Persists the ramp to the database (updates `FTE_Avail_MonthN` and `Capacity_MonthN`)
and writes to the history log.

**Path Parameters:** Same as Endpoint 1.

**Request Body:**

Same structure as the preview request, plus an optional user note:

```json
{
  "weeks": [...],
  "totalRampEmployees": 13,
  "user_notes": "Ramp for January ramp-up cohort"
}
```

**Pydantic Model:**

```python
class RampApplyRequest(RampPreviewRequest):
    user_notes: Optional[str] = Field(None, max_length=1000)

    class Config:
        extra = "forbid"
```

**Persistence Logic:**

1. Re-run the same calculation as preview (server-authoritative, not trusting frontend diff).
2. Update `FTE_Avail_MonthN` += `max(week.rampEmployees for week in weeks)` on the target `ForecastModel` row.
3. Update `Capacity_MonthN` += `total_ramp_capacity` (sum of per-week capacities) on the target `ForecastModel` row.
4. Upsert each week into `RampModel` (see Storage section below):
   - Match on `(forecast_id, month_key, ramp_percent, working_days)`.
   - If a matching row exists → update `employee_count`.
   - If no match → insert a new row.
5. Create a history log entry via `create_complete_history_log()` with `CHANGE_TYPE_RAMP_CALCULATION`.

**History Record Format:**

The history transformer snapshots the **entire** `ForecastModel` row (all 6 months × all tracked fields: `Client_Forecast`, `FTE_Required`, `FTE_Avail`, `Capacity`) before and after the update, then diffs every field. Only fields where `old_value != new_value` are emitted as change records — for a typical ramp apply this will be exactly `FTE_Avail_MonthN` and `Capacity_MonthN`, but the pattern does not hardcode this.

Each emitted change record follows the dot-notation format used by `extract_specific_changes()`:

```python
# One entry per changed field, e.g.:
{
    "main_lob":   row.Centene_Capacity_Plan_Main_LOB,
    "state":      row.Centene_Capacity_Plan_State,
    "case_type":  row.Centene_Capacity_Plan_Case_Type,
    "case_id":    str(row.id),
    "field_name": "Jan-26.fte_avail",   # dot-notation: month_label.field_name
    "old_value":  current_fte_avail,
    "new_value":  projected_fte_avail,
    "delta":      projected_fte_avail - current_fte_avail
}
```

See the implementation prompt (`docs/ramp_implementation_prompt.md`) for the full snapshot → diff → `modified_records` construction pattern.

**Success Response `200`:**

```json
{
  "success": true,
  "message": "Ramp calculation applied successfully",
  "forecast_id": 42,
  "month_key": "2026-01",
  "month_label": "Jan-26",
  "fields_updated": ["FTE_Avail_Month1", "Capacity_Month1"],
  "history_log_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Error Responses:**

| Status | Condition |
|--------|-----------|
| `404` | forecast_id not found |
| `400` | month_key not in report period |
| `400` | All weeks have `rampEmployees = 0` (at least one must be > 0) |
| `400` | `totalRampEmployees` does not match sum of `rampEmployees` across weeks |
| `422` | Validation failure (out-of-range values, or decimal `rampEmployees`) |
| `500` | DB error (rollback automatic) |

---

## Storage — New `RampModel` Table

The table is **normalised**: one row per week entry per `(forecast_id, month_key)`.
Multiple ramp weeks for the same forecast+month are stored as separate rows.

```python
class RampModel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    forecast_id: int = Field(index=True)          # FK to ForecastModel.id
    month_key: str = Field(index=True)            # "YYYY-MM"
    week_label: str                               # "Jan-1-2026"
    start_date: str                               # "2026-01-01" ISO date
    end_date: str                                 # "2026-01-04" ISO date
    working_days: int                             # Mon-Fri count in [start_date, end_date]
    ramp_percent: float                           # 0-100
    employee_count: int                           # ramp employees for this week
    applied_at: datetime = Field(default_factory=datetime.utcnow)
    applied_by: str = Field(default="system")

    class Config:
        table_name = "ramp_model"
```

**Upsert key:** `(forecast_id, month_key, ramp_percent, working_days)`

- If a row already exists with the same `(forecast_id, month_key, ramp_percent, working_days)` → **update** `employee_count` (and `applied_at`, `applied_by`).
- Otherwise → **insert** a new row.

This means re-applying a ramp with a changed employee count for the same week type updates that record in place, while a week with a distinct `ramp_percent` or `working_days` creates an additional record.

---

## URL Registration

Add the new router to `main.py` (or the existing routing module):

```python
from code.api.routers import ramp_router
app.include_router(ramp_router.router, prefix="/api/v1", tags=["Ramp Calculation"])
```

Create the router at: `code/api/routers/ramp_router.py`

Create the transformer/logic at: `code/logics/ramp_calculator.py`

---

## Error Response Shape (Consistent with Existing)

All error responses follow the existing pattern:

```json
{
  "success": false,
  "error": "Human-readable error message",
  "recommendation": "Optional guidance for the caller"
}
```

---

## Notes for Implementer

1. **No `UpdateOperation` required** for the apply endpoint — the ramp apply is simpler (only updates 2 columns per row) and adds its own `RampModel` upsert. Use `execute_update_operation` only if you want to reuse the history-logging orchestration; otherwise, implement directly with the existing session pattern.

2. **Month resolution:** The `month_key` (`YYYY-MM`) must be converted to the `MonthN` column suffix by querying `ForecastMonthsModel` for the report period matching the forecast row's month/year.

3. **`totalRampEmployees` validation:** Reject if `abs(totalRampEmployees - sum(w.rampEmployees)) > 0`. The field is informational/validation only; the calculation uses `max(rampEmployees)` for FTE and per-week capacity for total capacity.

4. **Working days validation:** If `workingDays` for any week does not match the actual Mon-Fri count for `[startDate, endDate]`, log a warning but do not reject (frontend supplies these; the server uses the frontend-supplied value for the per-week capacity calculation).

5. **Idempotency:** Each apply call upserts week rows individually and adds its delta to `FTE_Avail`/`Capacity`. Existing rows not matched by the incoming request are left untouched. Submitting the same request twice will insert duplicate capacity deltas — callers are responsible for not double-applying. A full ramp reset (delete + reverse) is out of scope and should be handled via a separate endpoint if needed.

6. **Cache invalidation:** After successful apply, invalidate any cached forecast data for the affected month/year (follow the existing `clear_*_cache()` pattern used in `forecast_updater.py`).
