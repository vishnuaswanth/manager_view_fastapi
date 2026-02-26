# Ramp Calculation API Spec

## Overview

Three endpoints to support weekly staffing ramp calculations for individual forecast rows.
A "ramp" adds incremental capacity for a target month: capacity is calculated independently for each week using that week's ramp employees and working days, then summed across all weeks. The effective FTE increase is the maximum ramp-employee count across any single week, added on top of the existing `FTE_Avail`.

**Router prefix:** `/api/v1`
**Change type constant:** `CHANGE_TYPE_RAMP_CALCULATION = "Ramp Calculation"`

---

## Data Model Reference

`ForecastModel` stores data in flat columns:
- `Client_Forecast_Month1` – `Client_Forecast_Month6`
- `FTE_Required_Month1` – `FTE_Required_Month6`
- `FTE_Avail_Month1` – `FTE_Avail_Month6`
- `Capacity_Month1` – `Capacity_Month6`

`ForecastMonthsModel` maps `Month1`–`Month6` to actual month labels (e.g., `"Apr-25"`).

`MonthConfigurationModel` stores per-month config: `WorkingDays`, `Occupancy`, `Shrinkage`, `WorkHours`.

`RampModel` stores one row per ramp week per `(forecast_id, month_key)`.

The target forecast row is identified by its integer primary key (`id` on `ForecastModel`).

**Month key format:** `"YYYY-MM"` (e.g., `"2026-01"` for January 2026).

---

## Pydantic Request Models

```python
class RampWeek(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)          # "Jan-1-2026"
    startDate: str = Field(min_length=10)     # "2026-01-01" ISO date
    endDate: str = Field(min_length=10)       # "2026-01-04" ISO date
    workingDays: int = Field(ge=0)            # count of working days in range
    rampPercent: float = Field(ge=0, le=100)  # 0-100
    rampEmployees: int = Field(ge=0)          # employees for this week


class RampPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weeks: List[RampWeek] = Field(min_length=1)
    totalRampEmployees: int = Field(ge=0)     # must equal sum(week.rampEmployees)


class RampApplyRequest(RampPreviewRequest):
    model_config = ConfigDict(extra="forbid")

    user_notes: Optional[str] = Field(None, max_length=1000)
```

**Business validation (400 before DB):**
- `all(w.rampEmployees == 0 for w in weeks)` → 400 "All rampEmployees are zero"
- `totalRampEmployees != sum(w.rampEmployees)` → 400 "totalRampEmployees does not match sum"

---

## Endpoint 1 — GET Applied Ramp

### `GET /api/v1/forecasts/{forecast_id}/months/{month_key}/ramp`

Retrieves all ramp week records stored for a specific forecast row and month.

**Path Parameters:**
| Param | Type | Example | Description |
|-------|------|---------|-------------|
| `forecast_id` | int | `42` | `ForecastModel.id` (DB primary key) |
| `month_key` | str | `2026-01` | Format: `YYYY-MM` — validated by path regex |

**No Ramp Applied — `200`:**

```json
{
  "success": true,
  "forecast_id": 42,
  "month_key": "2026-01",
  "ramp_applied": false,
  "ramp_data": null
}
```

**Ramp Applied — `200`:**

`ramp_data` is a list of week objects (one per `RampModel` row), ordered by `start_date`.
Week fields are **snake_case** and include audit timestamps.

```json
{
  "success": true,
  "forecast_id": 42,
  "month_key": "2026-01",
  "ramp_applied": true,
  "ramp_data": [
    {
      "week_label": "Jan-1-2026",
      "start_date": "2026-01-01",
      "end_date": "2026-01-04",
      "working_days": 2,
      "ramp_percent": 50.0,
      "employee_count": 4,
      "applied_at": "2026-01-10T08:30:00",
      "applied_by": "system"
    },
    {
      "week_label": "Jan-5-2026",
      "start_date": "2026-01-05",
      "end_date": "2026-01-11",
      "working_days": 5,
      "ramp_percent": 80.0,
      "employee_count": 9,
      "applied_at": "2026-01-10T08:30:00",
      "applied_by": "system"
    }
  ]
}
```

**Error Responses:**
| Status | Condition |
|--------|-----------|
| `404` | `forecast_id` not found |
| `400` | `month_key` not in this report's 6 months |
| `422` | Malformed `month_key` (not `YYYY-MM`) |
| `500` | Database error |

---

## Endpoint 2 — Preview Ramp Calculation

### `POST /api/v1/forecasts/{forecast_id}/months/{month_key}/ramp/preview`

Calculates the projected impact of applying a ramp **without persisting** anything.

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

**Calculation Logic:**

```
# Per-week capacity (config from MonthConfigurationModel)
week_capacity = rampEmployees × target_cph × work_hours
                × occupancy × (1 − shrinkage) × workingDays

total_ramp_capacity = sum(week_capacity for each week)
max_ramp_employees  = max(week.rampEmployees for week in weeks)

projected_fte_available = current_fte_available + max_ramp_employees
projected_capacity      = current_capacity + total_ramp_capacity
projected_gap           = projected_capacity − forecast
```

**Success Response — `200`:**

`current`/`projected`/`diff` are returned **at root level** (not nested under a `"preview"` key).
`config_used` reflects the `MonthConfigurationModel` values used for the calculation (falls back to defaults if no config found for that month).

```json
{
  "success": true,
  "forecast_id": 42,
  "month_key": "2026-01",
  "month_label": "Jan-26",
  "config_used": {
    "working_days": 21,
    "occupancy": 0.95,
    "shrinkage": 0.10,
    "work_hours": 9.0
  },
  "ramp_summary": {
    "total_ramp_capacity": 7168.5,
    "max_ramp_employees": 9,
    "weeks_count": 2
  },
  "current": {
    "forecast": 12000,
    "fte_required": 15,
    "fte_available": 18,
    "capacity": 14400,
    "gap": 2400.0
  },
  "projected": {
    "forecast": 12000,
    "fte_required": 15,
    "fte_available": 27,
    "capacity": 21568.5,
    "gap": 9568.5
  },
  "diff": {
    "forecast": 0,
    "fte_required": 0,
    "fte_available": 9,
    "capacity": 7168.5,
    "gap": 7168.5
  }
}
```

**Notes on field names:**
- `fte_available` (not `fte_avail`) used throughout `current`/`projected`/`diff`
- `ramp_summary` fields are snake_case: `total_ramp_capacity`, `max_ramp_employees`, `weeks_count`
- `config_used` is always present and shows exactly which config values drove the calculation

**Error Responses:**
| Status | Condition |
|--------|-----------|
| `404` | `forecast_id` not found |
| `400` | `month_key` not in report period |
| `400` | `totalRampEmployees` ≠ sum of `rampEmployees` |
| `400` | All weeks have `rampEmployees = 0` |
| `422` | Pydantic validation failure (out-of-range, wrong type, extra fields) |
| `500` | Database / calculation error |

---

## Endpoint 3 — Apply Ramp Calculation

### `POST /api/v1/forecasts/{forecast_id}/months/{month_key}/ramp/apply`

Persists the ramp: updates `FTE_Avail_MonthN` and `Capacity_MonthN` on `ForecastModel`,
upserts `RampModel` rows, writes a history log entry, and invalidates caches.

**Request Body:**

Same as preview, plus optional notes:

```json
{
  "weeks": [...],
  "totalRampEmployees": 13,
  "user_notes": "Ramp for January cohort"
}
```

**Persistence Steps:**

1. Re-run the same calculation as preview (server-authoritative).
2. `FTE_Avail_MonthN += max_ramp_employees`
3. `Capacity_MonthN += total_ramp_capacity` (rounded to nearest int)
4. Upsert each week into `RampModel` — match key: `(forecast_id, month_key, ramp_percent, working_days)`:
   - Match found → update `employee_count`, `week_label`, `start_date`, `end_date`, `applied_at`
   - No match → insert new row with `applied_by = "system"`
5. Create history log via `create_complete_history_log()` with `CHANGE_TYPE_RAMP_CALCULATION`.
6. Call `clear_all_caches()`.

**Success Response — `200`:**

The response includes **before/after values** for both updated columns, enabling the frontend to show
the change without needing to re-fetch the forecast row.

```json
{
  "success": true,
  "forecast_id": 42,
  "month_key": "2026-01",
  "month_label": "Jan-26",
  "fields_updated": ["FTE_Avail_Month1", "Capacity_Month1"],
  "fte_avail_before": 18,
  "fte_avail_after": 27,
  "capacity_before": 14400,
  "capacity_after": 21568,
  "history_log_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Notes:**
- `history_log_id` is `null` if history logging failed (ramp was still applied — failure is logged but not propagated).
- `capacity_after` is `round(capacity_before + total_ramp_capacity)` — integer.
- Applying the same request twice adds the delta twice (additive-only; no reversal endpoint in scope).

**Error Responses:**
| Status | Condition |
|--------|-----------|
| `404` | `forecast_id` not found |
| `400` | `month_key` not in report period |
| `400` | All weeks have `rampEmployees = 0` |
| `400` | `totalRampEmployees` ≠ sum of `rampEmployees` |
| `422` | Pydantic validation failure |
| `500` | Database error |

---

## Storage — `RampModel` Table

One row per ramp week per `(forecast_id, month_key)`.

```python
class RampModel(SQLModel, table=True):
    __tablename__ = "ramp_model"

    id: Optional[int] = Field(default=None, primary_key=True)
    forecast_id: int = Field(index=True)           # ForecastModel.id
    month_key: str = Field(index=True)             # "YYYY-MM"
    week_label: str                                # "Jan-1-2026"
    start_date: str                                # "2026-01-01"
    end_date: str                                  # "2026-01-04"
    working_days: int
    ramp_percent: float
    employee_count: int
    applied_at: datetime = Field(default_factory=datetime.utcnow)
    applied_by: str = Field(default="system")

    __table_args__ = (
        Index('idx_ramp_forecast_month', 'forecast_id', 'month_key'),
    )
```

**Upsert key:** `(forecast_id, month_key, ramp_percent, working_days)`

---

## Error Response Shape

```json
{
  "success": false,
  "error": "Human-readable error message",
  "recommendation": "Optional guidance for the caller"
}
```

---

## Notes

1. **`forecast_id` is the DB primary key** (`ForecastModel.id`), not `Centene_Capacity_Plan_Call_Type_ID`. The `/api/llm/forecast` endpoint currently does not return this value — callers must obtain it via another lookup or by adding `forecast_id` to that endpoint's response.

2. **Month resolution:** `month_key` (`YYYY-MM`) is resolved to the `MonthN` column suffix by querying `ForecastMonthsModel` for the report period matching the forecast row's `Month`/`Year`.

3. **Config fallback:** If no `MonthConfigurationModel` row exists for the resolved month and work type, defaults are used: `working_days=21`, `occupancy=0.95`, `shrinkage=0.10`, `work_hours=9.0`. A warning is logged.

4. **Idempotency:** Applying twice adds the delta twice. Existing `RampModel` rows not matched by the incoming request are left untouched.

5. **History log resilience:** If `create_complete_history_log()` throws, the ramp is still committed and `history_log_id: null` is returned. The error is logged at ERROR level.
