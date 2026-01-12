# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Centene Forecasting API - A FastAPI application for forecast management, resource allocation, and manager view reporting. The system handles capacity planning by matching forecast demands with resource rosters, supporting both domestic and global workforces across multiple platforms (Amisys, Facets).

## Common Commands

### Running the Application

**Development Mode (SQLite):**
```bash
# Ensure MODE=DEBUG in code/config.ini
python3 -m uvicorn code.main:app --reload
```

**Production Mode (MSSQL):**
```bash
# Ensure MODE=PRODUCTION in code/config.ini
python3 -m uvicorn code.main:app --host 0.0.0.0 --port 8000
```

### Testing

**Run specific test file:**
```bash
python3 -m pytest code/logics/test_bench_allocation_comprehensive.py -v
```

**Run all tests:**
```bash
python3 -m pytest code/logics/ -v
```

**Run test with detailed output:**
```bash
python3 code/logics/test_bench_allocation_comprehensive.py
```

### Database Operations

The application uses SQLAlchemy/SQLModel with two database modes:
- **DEBUG**: SQLite (`code/test.db`)
- **PRODUCTION**: MSSQL Server (configured in `code/config.ini`)

Database URL is determined at startup based on `MODE` setting in `code/config.ini`.

## Architecture Overview

### Core Application Structure

```
code/
├── main.py                  # FastAPI app entry point, router registration
├── settings.py              # Configuration loading (MODE, DB URLs, cache TTLs)
├── cache.py                 # In-memory TTL cache implementation
├── api/
│   ├── routers/            # API endpoints (RESTful routes)
│   │   ├── upload_router.py       # File uploads (forecast, roster)
│   │   ├── manager_view_router.py # Hierarchical reporting
│   │   ├── forecast_router.py     # Forecast filters & cascade
│   │   ├── allocation_router.py   # Allocation execution tracking & reports
│   │   └── month_config_router.py # Month configuration CRUD
│   ├── dependencies.py     # Shared dependencies (DB sessions)
│   └── utils/
│       ├── responses.py    # Standard response wrappers
│       └── validators.py   # Input validation helpers
└── logics/
    ├── db.py                       # SQLModel database models
    ├── core_utils.py               # DB utilities, preprocessing
    ├── allocation.py               # Primary allocation algorithm
    ├── bench_allocation.py         # Bench (unallocated) resource allocation
    ├── manager_view.py             # Hierarchical categorization
    ├── month_config_utils.py       # Month config helpers
    ├── allocation_tracker.py       # Execution tracking
    ├── allocation_validity.py      # Validation logic
    ├── export_utils.py             # Report generation helpers
    ├── summary_utils.py            # Summary calculations
    ├── cascade_filters.py          # Dynamic filter cascading
    └── config/
        └── forecast_grouping_rules.json  # Category hierarchy rules
```

### Key Architectural Patterns

**1. Allocation Flow (Two-Phase Process)**

Phase 1 (`allocation.py`):
- Reads forecast demands and roster availability
- Matches vendors to forecast rows based on:
  - Platform (Amisys/Facets)
  - Locality (Domestic/Global)
  - Skills (case types)
  - State compatibility
- Calculates capacity using month-specific configurations (working days, occupancy, shrinkage)
- Creates `AllocationExecutionModel` records to track execution status
- Generates three report types in `AllocationReportsModel`:
  - `bucket_summary` - Vendor distribution by bucket
  - `bucket_after_allocation` - Post-allocation bucket state
  - `roster_allotment` - Vendor assignments per month

Phase 2 (`bench_allocation.py`):
- Allocates remaining unallocated (bench) vendors
- Uses proportional distribution (Largest Remainder Method)
- Whole FTEs only (no decimals)
- Fills gaps first, then distributes excess
- Generates Excel exports with allocation changes

**2. Month Configuration System**

Month configurations are stored per month+year in `MonthConfigurationModel`:
```json
{
  "January 2025": {
    "Domestic": {"working_days": 21, "occupancy": 0.95, "shrinkage": 0.10, "work_hours": 9},
    "Global": {"working_days": 21, "occupancy": 0.90, "shrinkage": 0.15, "work_hours": 9}
  }
}
```

Capacity calculation formula:
```
Capacity = FTE × working_days × work_hours × occupancy × (1 - shrinkage) × target_cph
```

**3. Hierarchical Categorization (Manager View)**

Categories are defined in `code/logics/config/forecast_grouping_rules.json`:
- Up to 5 levels of nesting
- Rule-based matching on forecast fields: `platform`, `market`, `state`, `locality`, `worktype_id`, `worktype`
- Bottom-up aggregation: parent metrics = sum of children
- Cached with 5-minute TTL (filters) and 60-second TTL (data)

**4. Database Models Hierarchy**

Key tables:
- `ForecastModel` - Forecast demands (6 months: Month1-Month6)
- `ForecastMonthsModel` - Month name mappings for uploaded file
- `ProdTeamRosterModel` - Resource roster with skills and state lists
- `AllocationExecutionModel` - Execution tracking (status: PENDING → IN_PROGRESS → SUCCESS/FAILED/PARTIAL_SUCCESS)
- `AllocationReportsModel` - Generated reports (JSON blobs)
- `MonthConfigurationModel` - Month-specific config snapshots
- `AllocationValidityModel` - Tracks which allocation is current for a month/year

**5. Caching Strategy**

In-memory TTL cache (`cache.py`, no external services):
- Filters endpoint: 5 minutes
- Data endpoint: 60 seconds
- Execution list: 30 seconds
- Execution details: 5 seconds (active), 1 hour (completed)
- Cache keys include all query parameters for proper invalidation

### Important Implementation Details

**Month Offset in Forecast Data:**
When a forecast file is uploaded for "March 2025", the Month1-Month6 columns represent:
- Month1 = April 2025 (report month + 1)
- Month2 = May 2025
- Month3 = June 2025
- Month4 = July 2025
- Month5 = August 2025
- Month6 = September 2025

**DO NOT** generate months using date math. Always query `ForecastMonthsModel` to get actual month mappings for the uploaded file.

**State Matching:**
Vendors have `StateList` (e.g., "CA|TX|NY") and can only be allocated to forecasts where the state matches. State strings are normalized before comparison.

**Locality Normalization:**
- "Offshore"/"OFFSHORE" → "Global"
- "Onshore"/"Domestic"/"DOMESTIC" → "Domestic"

**Platform/LOB Parsing:**
The `parse_main_lob()` function extracts platform from `Main_LOB`:
- Contains "Amisys" → "Amisys"
- Contains "Facets" → "Facets"
- Otherwise → None

## Critical Configuration

**Application Startup:**
1. Validates `forecast_grouping_rules.json` at startup (app fails if invalid)
2. Loads MODE from `code/config.ini` to determine database URL
3. Registers all routers with FastAPI app
4. Initializes logging to `code/app.log`

**Required Configuration File:**
`code/config.ini` must contain:
```ini
[settings]
mode = DEBUG  # or PRODUCTION

[mysql]
user = your_user
password = your_password
host = your_host
port = your_port
database = your_database

[options]
driver = ODBC Driver 17 for SQL Server
```

## Development Guidelines

**Adding New Allocation Logic:**
- Update `allocation.py` for primary allocation changes
- Update `bench_allocation.py` for bench allocation changes
- Always create/update `AllocationExecutionModel` records
- Store results in `AllocationReportsModel` with proper `execution_id` linkage
- Use `allocation_tracker.py` functions: `start_execution()`, `update_status()`, `complete_execution()`

**Modifying Categorization:**
- Edit `code/logics/config/forecast_grouping_rules.json`
- Rules support regex patterns for flexible matching
- Changes are validated at startup (app will fail fast if invalid)
- Debug with `/api/manager-view/debug/categorization` endpoint

**Adding New API Endpoints:**
1. Create/modify router in `code/api/routers/`
2. Register router in `code/main.py` via `app.include_router()`
3. Use standardized responses from `code/api/utils/responses.py`
4. Follow existing error handling patterns (return `success: false` with `error` message)

**Database Schema Changes:**
1. Modify models in `code/logics/db.py`
2. SQLModel handles table creation automatically on first run
3. For MSSQL migrations, coordinate with DBA for ALTER statements
4. Test with DEBUG mode (SQLite) first

**Testing Allocation:**
- Use `code/logics/test_bench_allocation_comprehensive.py` as template
- Test both phases: primary allocation + bench allocation
- Verify execution tracking records are created
- Check that reports are properly linked via `execution_id`

## Coding Standards and Best Practices

### Dependency Injection Pattern

**ALWAYS use the dependency injection pattern for CoreUtils and loggers:**

```python
# CORRECT - Use dependency injection
from code.api.dependencies import get_core_utils, get_logger

logger = get_logger(__name__)
core_utils = get_core_utils()  # Singleton instance
```

```python
# WRONG - Don't create instances directly
from code.settings import MODE, SQLITE_DATABASE_URL, MSSQL_DATABASE_URL
from code.logics.core_utils import CoreUtils

if MODE.upper() == "DEBUG":
    DATABASE_URL = SQLITE_DATABASE_URL
core_utils = CoreUtils(DATABASE_URL)  # Creates duplicate instance
```

**Why:** Ensures single CoreUtils instance, consistent error handling, follows project patterns.

**Files:** All routers and logic modules should use `get_core_utils()` and `get_logger()`.

---

### Error Handling

**Use specific exception types instead of broad catches:**

```python
# CORRECT - Specific exception handling
from sqlalchemy.exc import SQLAlchemyError

try:
    # Database operations
    pass
except (ValueError, KeyError, AttributeError) as e:
    # Data validation errors → 400 Bad Request
    logger.error(f"Data validation error: {e}", exc_info=True)
    raise HTTPException(status_code=400, detail={...})
except SQLAlchemyError as e:
    # Database errors → 500 Internal Server Error
    logger.error(f"Database error: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail={...})
except Exception as e:
    # Unexpected errors → log as CRITICAL
    logger.critical(f"Unexpected error: {e}", exc_info=True)
    raise
```

```python
# WRONG - Too broad
try:
    # operations
except Exception as e:
    logger.error(f"Error: {e}")
    raise
```

**Why:** Better HTTP status codes, improved debugging, clearer error messages.

**Files:** All API routers should use specific exception types.

---

### Input Validation

**Add validation BEFORE database operations:**

```python
# CORRECT - Validate first
def _validate_change_record(change: Dict, index: int) -> None:
    """Validate change dict structure."""
    if not isinstance(change, dict):
        raise ValueError(f"Change at index {index} is not a dict")

    required_keys = ['main_lob', 'state', 'case_type']
    missing = [k for k in required_keys if k not in change]
    if missing:
        raise ValueError(f"Missing keys: {missing}")

# Then validate all records before DB operations
for i, change in enumerate(changes):
    _validate_change_record(change, i)
```

**Why:** Prevents KeyError crashes, catches malformed data early, better error messages.

**Files:** All data transformation and history logging functions.

---

### Utility Functions - DRY Principle

**Use centralized utility functions instead of duplicating code:**

```python
# CORRECT - Use utility functions
from code.logics.edit_view_utils import parse_field_path, get_forecast_column_name
from code.logics.capacity_calculations import calculate_fte_required, calculate_capacity

month_label, field_name = parse_field_path("Jun-25.fte_avail")
column_name = get_forecast_column_name('forecast', '1')
fte = calculate_fte_required(forecast, config, target_cph)
capacity = calculate_capacity(fte_avail, config, target_cph)
```

```python
# WRONG - Manual parsing and calculations
if "." in field_path:
    month_label, field_name = field_path.split(".", 1)

column_name = f'Client_Forecast_Month{suffix}'  # Hardcoded

fte = math.ceil(forecast / (working_days * work_hours * (1-shrinkage) * target_cph))
```

**Why:** Centralized logic, easier to maintain, consistent behavior, eliminates duplication.

**Available Utilities:**
- `code/logics/edit_view_utils.py` - Field parsing, column name mapping, validation
- `code/logics/capacity_calculations.py` - FTE and capacity formulas

---

### Pydantic Models for Request Validation

**Use strongly-typed Pydantic models instead of `Dict[str, Any]`:**

```python
# CORRECT - Strongly typed
class MonthData(BaseModel):
    forecast: float = Field(ge=0, description="Client forecast")
    fte_req: int = Field(ge=0, description="FTE Required")

    class Config:
        extra = "forbid"  # Reject unknown fields

class CPHRecord(BaseModel):
    lob: str = Field(min_length=1)
    target_cph: float = Field(gt=0, le=200)
```

```python
# WRONG - Too permissive
class Request(BaseModel):
    modified_records: List[Dict[str, Any]]  # No validation!
```

**Why:** Input validation at API boundary, security, auto-generated API docs with constraints.

**Files:** All API request models in routers.

---

### Database Session Management

**Trust SQLAlchemy context managers for rollback:**

```python
# CORRECT - Context manager handles rollback
with db_manager.SessionLocal() as session:
    try:
        # Database operations
        session.commit()  # Explicit commit if needed
    except Exception as e:
        # Context manager will rollback automatically
        logger.error(f"Transaction failed: {e}")
        raise
```

```python
# WRONG - Redundant manual rollback
with db_manager.SessionLocal() as session:
    try:
        # operations
    except Exception as e:
        session.rollback()  # REDUNDANT!
        raise
```

**Why:** Cleaner code, SQLAlchemy handles it automatically, avoid duplicate cleanup logic.

---

### Helper Functions for Repeated Operations

**Extract helper functions to eliminate code duplication:**

```python
# CORRECT - Use helper function
from code.logics.history_logger import create_complete_history_log

history_log_id = create_complete_history_log(
    month=request.month,
    year=request.year,
    change_type=CHANGE_TYPE_BENCH_ALLOCATION,
    user="system",
    user_notes=request.user_notes,
    modified_records=modified_records_dict,
    months_dict=request.months,
    summary_data=summary_data
)
```

```python
# WRONG - Duplicated code
changes = extract_specific_changes(modified_records_dict, request.months)
history_log_id = create_history_log(...)
add_history_changes(history_log_id, changes)
```

**Why:** Reduces duplication, centralizes logic, easier to modify.

**Available Helpers:**
- `create_complete_history_log()` - Creates history log with changes in one call
- `calculate_fte_required()` - Standardized FTE calculation
- `calculate_capacity()` - Standardized capacity calculation

---

### Comprehensive Error Handling in Transformers

**ALL data transformation functions must have error handling:**

```python
# CORRECT - Input validation + error handling
def transform_data(allocation_result, month, year, core_utils):
    """Transform with error handling."""
    try:
        # Validate inputs
        if not allocation_result:
            raise ValueError("allocation_result cannot be None")

        if not hasattr(allocation_result, 'allocations'):
            raise ValueError("Missing 'allocations' attribute")

        # Process with defensive checks
        for i, record in enumerate(allocation_result.allocations):
            if not hasattr(record, 'forecast_row'):
                raise AttributeError(f"Record {i} missing 'forecast_row'")
            # ...

    except KeyError as e:
        logger.error(f"Missing key: {e}", exc_info=True)
        raise ValueError(f"Invalid data structure: {e}")
    except AttributeError as e:
        logger.error(f"Missing attribute: {e}", exc_info=True)
        raise ValueError(f"Invalid record structure: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise
```

**Why:** Prevents runtime crashes, clear error messages with context, better debugging.

**Files:** All transformer modules in `code/logics/`.

---

### Testing Requirements

**Create unit tests for all utility modules:**

```python
# Test file: code/logics/test_capacity_calculations.py

class TestCalculateFTERequired:
    def test_basic_calculation(self):
        config = {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10}
        result = calculate_fte_required(1000, config, 50.0)
        assert result == 1

    def test_zero_forecast_returns_zero(self):
        result = calculate_fte_required(0, config, 50.0)
        assert result == 0

    def test_negative_forecast_raises_error(self):
        with pytest.raises(ValueError):
            calculate_fte_required(-100, config, 50.0)
```

**Coverage Requirements:**
- Test valid inputs
- Test edge cases (zero, negative, boundary values)
- Test error conditions (missing keys, invalid types)
- Test integration scenarios

**Run tests:**
```bash
python3 -m pytest code/logics/test_capacity_calculations.py -v
```

## API Documentation

Full API specifications are available in:
- `api-spec.md` - Manager View API
- `allocation_execution_spec.md` - Allocation Execution Tracking API
- `docs/ALLOCATION_API_SPEC.md` - Allocation Report Downloads
- `CASCADE_FILTERS_API_SPEC.md` - Cascade Filters API
- `month_config_spec.md` - Month Configuration API

Key endpoints:
- `GET /api/manager-view/filters` - Get dropdown options
- `GET /api/manager-view/data` - Get hierarchical data
- `GET /api/allocation/executions` - List executions with filtering
- `GET /api/allocation/executions/{execution_id}` - Get execution details
- `GET /api/allocation/executions/kpi` - Get aggregated KPIs
- `POST /api/upload/roster` - Upload roster file
- `POST /api/upload/forecast` - Upload forecast file

## Debugging Guides

Several debugging guides are available in the repository root:
- `ALLOCATION_DEBUG_GUIDE.md` - Allocation troubleshooting
- `BUCKET_DEBUG_EXPORTS.md` - Bucket export debugging
- `DEBUG_EXCEL_OUTPUTS.md` - Excel output debugging
- `EVERY_VENDOR_HAS_NA.md` - State matching issues
- `STATE_MAPPING_LOGIC.md` - State mapping details

## Known Issues and Workarounds

**Issue: Month Mapping in Bench Allocation**
See `PLAN.md` for details on the month offset bug and dataclass refactoring plan. When working on bench allocation, always query `ForecastMonthsModel` instead of calculating months.

**Issue: State List Parsing**
StateList in roster is pipe-delimited (e.g., "CA|TX|NY"). Always split and normalize before comparing.

**Issue: Configuration Snapshot**
Each execution stores a `ConfigSnapshot` in `AllocationExecutionModel`. This captures the exact month config used at execution time for reproducibility.
