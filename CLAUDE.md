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
