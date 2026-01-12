# History Router Separation - Refactoring Documentation

## Summary

Separated history log related API endpoints from `edit_view_router.py` into a dedicated `history_router.py` file to improve code organization and maintainability.

## Motivation

The `edit_view_router.py` file was handling multiple concerns:
1. Bench allocation preview and updates
2. CPH (Cases Per Hour) updates
3. History log viewing and downloads

This refactoring follows the **Single Responsibility Principle** by separating history log concerns into their own router module.

## Changes Made

### 1. Created New Router: `code/api/routers/history_router.py`

**New file with 2 endpoints:**

#### Endpoint 1: `GET /api/history-log`
- **Purpose:** List history logs with filters and pagination
- **Query Parameters:**
  - `month` (optional): Filter by month name
  - `year` (optional): Filter by year
  - `change_types` (optional): Filter by change types (OR logic)
  - `page` (default: 1): Page number (1-indexed)
  - `limit` (default: 25, max: 100): Records per page
- **Returns:** Paginated list of history log entries
- **Status Codes:** 200 OK, 400 Bad Request, 500 Internal Server Error

#### Endpoint 2: `GET /api/history-log/{history_log_id}/download`
- **Purpose:** Download history log as Excel file
- **Path Parameters:**
  - `history_log_id`: UUID of the history log entry
- **Returns:** Excel file (StreamingResponse)
- **File Format:** `history_log_{change_type}_{month}_{year}_{id}.xlsx`
- **Status Codes:** 200 OK, 404 Not Found, 500 Internal Server Error

**Dependencies:**
```python
from code.logics.history_logger import (
    list_history_logs,
    get_history_log_with_changes
)
from code.logics.history_excel_generator import generate_history_excel
from code.logics.config.change_types import validate_change_type
```

### 2. Modified `code/api/routers/edit_view_router.py`

**Removed:**
- History log listing endpoint (`GET /api/history-log`)
- History log download endpoint (`GET /api/history-log/{history_log_id}/download`)
- Unused imports:
  - `list_history_logs`
  - `get_history_log_with_changes`
  - `generate_history_excel`
  - `validate_change_type`

**Updated:**
- Renumbered remaining endpoints (Endpoint 4→4, Endpoint 7→5, Endpoint 8→6)

**Remaining Endpoints:**
1. `GET /api/allocation-reports` - Get allocation reports
2. `POST /api/bench-allocation/preview` - Preview bench allocation
3. `POST /api/bench-allocation/update` - Apply bench allocation
4. `GET /api/edit-view/target-cph/data/` - Get CPH data
5. `POST /api/edit-view/target-cph/preview/` - Preview CPH changes
6. `POST /api/edit-view/target-cph/update/` - Apply CPH changes

### 3. Modified `code/main.py`

**Added:**
```python
from code.api.routers.history_router import router as history_router

# Register history router
app.include_router(history_router, tags=["History Log"])
```

**Router Registration Order:**
1. File Management (`upload_router`)
2. Manager View (`manager_view_router`)
3. Forecast Filters (`forecast_router`)
4. Allocation (`allocation_router`)
5. Month Configuration (`month_config_router`)
6. Edit View (`edit_view_router`)
7. **History Log (`history_router`)** ← New

## File Structure

```
code/
├── main.py                           # Updated: Added history_router import and registration
├── api/
│   └── routers/
│       ├── edit_view_router.py       # Modified: Removed history endpoints
│       └── history_router.py         # Created: New history log router
└── logics/
    ├── history_logger.py             # Used by history_router
    ├── history_excel_generator.py    # Used by history_router
    └── config/
        └── change_types.py           # Used by history_router
```

## API Documentation Changes

### Swagger/OpenAPI UI

When you navigate to `/docs`, you'll now see a new section:

**Before:**
- File Management
- Manager View
- Forecast Filters
- Allocation
- Month Configuration
- Edit View (contained 8 endpoints including history)

**After:**
- File Management
- Manager View
- Forecast Filters
- Allocation
- Month Configuration
- Edit View (now 6 endpoints - bench allocation and CPH only)
- **History Log** (2 endpoints - list and download)

### Endpoint URLs (Unchanged)

All endpoint URLs remain the same:
- ✅ `GET /api/history-log` (moved but URL unchanged)
- ✅ `GET /api/history-log/{history_log_id}/download` (moved but URL unchanged)

**No breaking changes for API consumers.**

## Benefits

### 1. **Better Code Organization**
- History log concerns separated from edit view concerns
- Clearer module boundaries and responsibilities
- Easier to locate history-related code

### 2. **Improved Maintainability**
- Changes to history functionality isolated to history_router.py
- Reduced risk of unintended side effects
- Smaller, more focused router files

### 3. **Better API Documentation**
- Clearer grouping in Swagger UI
- Easier to find history-related endpoints
- Logical separation of concerns visible to API consumers

### 4. **Scalability**
- Easy to add more history-related endpoints
- Can add middleware specific to history operations
- Simpler to test history functionality in isolation

### 5. **Follows Best Practices**
- Single Responsibility Principle
- Separation of Concerns
- Domain-Driven Design (history as a bounded context)

## Testing

### Compilation Tests
All files compile successfully:
```bash
✓ history_router.py compiled successfully
✓ edit_view_router.py compiled successfully
✓ main.py compiled successfully
```

### Integration Testing

Test the history endpoints:

```bash
# Start the server
python3 -m uvicorn code.main:app --reload

# Test listing history logs
curl "http://localhost:8000/api/history-log?page=1&limit=10"

# Test listing with filters
curl "http://localhost:8000/api/history-log?month=April&year=2025&change_types=Bench%20Allocation"

# Test downloading history Excel
curl "http://localhost:8000/api/history-log/{history_log_id}/download" \
  --output history.xlsx
```

### Verify Swagger Documentation

Visit `http://localhost:8000/docs` and verify:
- [x] "History Log" section appears in the sidebar
- [x] GET /api/history-log is under "History Log"
- [x] GET /api/history-log/{history_log_id}/download is under "History Log"
- [x] Edit View section no longer contains history endpoints

## Migration Notes

### No Breaking Changes

- All endpoint URLs remain unchanged
- Request/response formats unchanged
- No API consumer updates required

### Code Updates Required

If you have internal code that imports history endpoints from `edit_view_router`:

**Before:**
```python
from code.api.routers.edit_view_router import get_history_log, download_history_excel
```

**After:**
```python
from code.api.routers.history_router import get_history_log, download_history_excel
```

However, this is unlikely since these are endpoint handlers, not utility functions.

## Future Improvements

### 1. Additional History Endpoints
Now that history has its own router, we can easily add:
- `GET /api/history-log/{history_log_id}` - Get single history log details
- `DELETE /api/history-log/{history_log_id}` - Delete history log
- `GET /api/history-log/stats` - Get history statistics
- `POST /api/history-log/rollback/{history_log_id}` - Rollback changes

### 2. History-Specific Middleware
Add middleware for:
- Audit logging of history access
- Rate limiting for history downloads
- Caching for frequently accessed history logs

### 3. Versioning
Add API versioning to history endpoints:
- `/api/v1/history-log`
- `/api/v2/history-log` (with enhanced features)

### 4. Batch Operations
- `POST /api/history-log/batch-download` - Download multiple history logs as ZIP
- `POST /api/history-log/batch-delete` - Delete multiple history logs

## Dependencies Between Routers

### History Router Dependencies
- **Independent of:** edit_view_router, allocation_router
- **Depends on:** history_logger, history_excel_generator, change_types

### Edit View Router Dependencies
- **Independent of:** history_router
- **Depends on:** bench_allocation, cph_update_transformer, forecast_updater, update_handler

This separation ensures clean dependency boundaries and reduces coupling.

## Rollback Instructions

If you need to revert this change:

1. Copy history endpoints from `history_router.py` back to `edit_view_router.py`
2. Remove `history_router.py`
3. Remove history router import and registration from `main.py`
4. Restore removed imports in `edit_view_router.py`:
   - `list_history_logs`
   - `get_history_log_with_changes`
   - `generate_history_excel`
   - `validate_change_type`
5. Restore original endpoint numbering (4→4, 5→7, 6→8)

## Summary

This refactoring improves code organization by separating history log concerns into a dedicated router, making the codebase more maintainable and scalable while maintaining full backward compatibility for API consumers.

**Files Created:** 1 (`history_router.py`)
**Files Modified:** 2 (`edit_view_router.py`, `main.py`)
**Files Deleted:** 0
**Breaking Changes:** None
**API Endpoints Affected:** 2 (moved, URLs unchanged)
