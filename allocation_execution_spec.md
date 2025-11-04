# Allocation Execution API Specification

## Overview
This document describes the API endpoints for managing and monitoring allocation executions in the Manager View FastAPI application.

**Base URL:** `http://your-domain.com`

**Version:** v1

---

## Table of Contents
1. [List Allocation Executions](#1-list-allocation-executions)
2. [Get Execution Details](#2-get-execution-details)
3. [Get Execution KPIs](#3-get-execution-kpis)
4. [Status Workflow](#status-workflow)
5. [Example Use Cases](#example-use-cases)
6. [Performance Notes](#performance-notes)

---

## 1. List Allocation Executions

### Endpoint
```http
GET /api/allocation/executions
```

### Description
List allocation executions with filtering and pagination. Returns minimal data optimized for table views.

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `month` | string | No | - | Filter by month name (e.g., "January") |
| `year` | integer | No | - | Filter by year (e.g., 2025) |
| `status` | string[] | No | - | Filter by status (can specify multiple): `PENDING`, `IN_PROGRESS`, `SUCCESS`, `FAILED`, `PARTIAL_SUCCESS` |
| `uploaded_by` | string | No | - | Filter by username |
| `limit` | integer | No | 50 | Max records per page (max: 100) |
| `offset` | integer | No | 0 | Pagination offset |

**Multiple Status Filtering:**

You can filter by multiple statuses by specifying the `status` parameter multiple times:

```bash
# Filter by SUCCESS or FAILED status
GET /api/allocation/executions?status=SUCCESS&status=FAILED

# Filter by all active statuses (PENDING and IN_PROGRESS)
GET /api/allocation/executions?status=PENDING&status=IN_PROGRESS
```

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "data": [
    {
      "execution_id": "550e8400-e29b-41d4-a716-446655440000",
      "month": "January",
      "year": 2025,
      "status": "SUCCESS",
      "start_time": "2025-01-15T10:30:00",
      "end_time": "2025-01-15T10:35:00",
      "duration_seconds": 300.5,
      "uploaded_by": "john.doe",
      "forecast_filename": "forecast_jan_2025.xlsx",
      "allocation_success_rate": 0.95,
      "error_type": null
    }
  ],
  "pagination": {
    "total": 150,
    "limit": 50,
    "offset": 0,
    "count": 50,
    "has_more": true
  }
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `execution_id` | string (UUID) | Unique execution identifier |
| `month` | string | Target month for allocation |
| `year` | integer | Target year for allocation |
| `status` | string | Current status: PENDING, IN_PROGRESS, SUCCESS, FAILED, PARTIAL_SUCCESS |
| `start_time` | string (ISO 8601) | When execution started |
| `end_time` | string (ISO 8601) | When execution completed (null if in progress) |
| `duration_seconds` | float | Duration in seconds (null if in progress) |
| `uploaded_by` | string | Username who triggered the execution |
| `forecast_filename` | string | Name of forecast file used |
| `allocation_success_rate` | float | Success rate (0.0-1.0) |
| `error_type` | string | Error category if failed (null if successful) |

### Example Requests

**Get all executions (default pagination):**
```bash
GET /api/allocation/executions
```

**Filter by month and year:**
```bash
GET /api/allocation/executions?month=January&year=2025
```

**Filter by single status:**
```bash
GET /api/allocation/executions?status=SUCCESS
```

**Filter by multiple statuses:**
```bash
# Get both successful and failed executions
GET /api/allocation/executions?status=SUCCESS&status=FAILED

# Get all active executions
GET /api/allocation/executions?status=PENDING&status=IN_PROGRESS
```

**Filter by user:**
```bash
GET /api/allocation/executions?uploaded_by=john.doe
```

**Combined filters with pagination:**
```bash
GET /api/allocation/executions?month=January&year=2025&status=SUCCESS&limit=20&offset=40
```

**Get only failed executions:**
```bash
GET /api/allocation/executions?status=FAILED
```

**Get in-progress executions (for monitoring):**
```bash
GET /api/allocation/executions?status=IN_PROGRESS
```

**Get completed executions (successful or failed):**
```bash
GET /api/allocation/executions?status=SUCCESS&status=FAILED&status=PARTIAL_SUCCESS
```

### Error Responses

**400 Bad Request** - Invalid parameters
```json
{
  "success": false,
  "error": "Invalid pagination parameters",
  "status_code": 400
}
```

**500 Internal Server Error**
```json
{
  "success": false,
  "error": "Failed to list executions",
  "status_code": 500
}
```

### Ordering
Results are ordered by **start time descending** (newest first, oldest last).

### Caching
- **TTL:** 30 seconds
- **Cache Key:** `allocation_executions:v1:{month}:{year}:{status}:{uploaded_by}:{limit}:{offset}`
  - For multiple statuses, the key uses comma-separated sorted values (e.g., `FAILED,SUCCESS`)
  - Example: `allocation_executions:v1:January:2025:FAILED,SUCCESS:john.doe:50:0`
- **Invalidation:** Automatically cleared when new executions are created or statuses change

---

## 2. Get Execution Details

### Endpoint
```http
GET /api/allocation/executions/{execution_id}
```

### Description
Get detailed information about a specific allocation execution including configuration snapshot, error details, and statistics.

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `execution_id` | string (UUID) | Yes | Unique execution identifier |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "data": {
    "execution_id": "550e8400-e29b-41d4-a716-446655440000",
    "month": "January",
    "year": 2025,
    "status": "SUCCESS",
    "start_time": "2025-01-15T10:30:00",
    "end_time": "2025-01-15T10:35:00",
    "duration_seconds": 300.5,
    "forecast_filename": "forecast_jan_2025.xlsx",
    "roster_filename": "roster_dec_2024.xlsx",
    "roster_month_used": "December",
    "roster_year_used": 2024,
    "roster_was_fallback": false,
    "uploaded_by": "john.doe",
    "records_processed": 1250,
    "records_failed": 62,
    "allocation_success_rate": 0.95,
    "error_message": null,
    "error_type": null,
    "stack_trace": null,
    "config_snapshot": {
      "month_config": {
        "January 2025": {
          "Domestic": {
            "working_days": 21,
            "occupancy": 0.95,
            "shrinkage": 0.10,
            "work_hours": 9
          },
          "Global": {
            "working_days": 21,
            "occupancy": 0.90,
            "shrinkage": 0.15,
            "work_hours": 9
          }
        },
        "February 2025": {
          "Domestic": {
            "working_days": 20,
            "occupancy": 0.95,
            "shrinkage": 0.10,
            "work_hours": 9
          },
          "Global": {
            "working_days": 20,
            "occupancy": 0.90,
            "shrinkage": 0.15,
            "work_hours": 9
          }
        }
      }
    },
    "created_datetime": "2025-01-15T10:30:00"
  }
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `execution_id` | string (UUID) | Unique execution identifier |
| `month` | string | Target month for allocation |
| `year` | integer | Target year for allocation |
| `status` | string | PENDING, IN_PROGRESS, SUCCESS, FAILED, PARTIAL_SUCCESS |
| `start_time` | string (ISO 8601) | When execution started |
| `end_time` | string (ISO 8601) | When execution completed (null if in progress) |
| `duration_seconds` | float | Duration in seconds |
| `forecast_filename` | string | Name of forecast file used |
| `roster_filename` | string | Name of roster file used |
| `roster_month_used` | string | Actual month of roster data used |
| `roster_year_used` | integer | Actual year of roster data used |
| `roster_was_fallback` | boolean | True if roster fallback occurred |
| `uploaded_by` | string | Username who triggered execution |
| `records_processed` | integer | Total records processed |
| `records_failed` | integer | Number of failed allocations |
| `allocation_success_rate` | float | Success rate (0.0-1.0) |
| `error_message` | string | Error message if failed (null otherwise) |
| `error_type` | string | Error category if failed (null otherwise) |
| `stack_trace` | string | Full stack trace if failed (null otherwise) |
| `config_snapshot` | object | Configuration used for this execution |
| `created_datetime` | string (ISO 8601) | Record creation timestamp |

### Example Request

**Get execution details:**
```bash
GET /api/allocation/executions/550e8400-e29b-41d4-a716-446655440000
```

### Error Responses

**404 Not Found** - Execution doesn't exist
```json
{
  "success": false,
  "error": "Execution with ID 550e8400-e29b-41d4-a716-446655440000 not found",
  "status_code": 404
}
```

**500 Internal Server Error**
```json
{
  "success": false,
  "error": "Failed to get execution details",
  "status_code": 500
}
```

### Caching
- **TTL:** Dynamic based on status
  - **PENDING/IN_PROGRESS:** 5 seconds (for active monitoring)
  - **SUCCESS/FAILED:** 1 hour (immutable data)
- **Cache Key:** `allocation_execution_detail:v1:{execution_id}`
- **Invalidation:** Automatically cleared when execution status changes

---

## 3. Get Execution KPIs

### Endpoint
```http
GET /api/allocation/executions/kpi
```

### Description
Get aggregated KPI (Key Performance Indicator) metrics for allocation executions. Supports flexible filtering with any combination of filters.

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `month` | string | No | - | Filter by month name (e.g., "January") |
| `year` | integer | No | - | Filter by year (e.g., 2025) |
| `status` | string[] | No | - | Filter by status (can specify multiple): PENDING, IN_PROGRESS, SUCCESS, FAILED, PARTIAL_SUCCESS |
| `uploaded_by` | string | No | - | Filter by username |

**Flexible Filtering:**

All filters are optional and can be combined in any way:
- Just year (e.g., all 2025 executions)
- Month and year (e.g., January 2025)
- Just status(es) (e.g., all failed executions)
- Just uploaded_by (e.g., all executions by user)
- Any combination of the above

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "data": {
    "total_executions": 150,
    "success_rate": 0.85,
    "average_duration_seconds": 320.5,
    "failed_count": 12,
    "partial_success_count": 8,
    "in_progress_count": 2,
    "pending_count": 3,
    "success_count": 125,
    "total_records_processed": 187500,
    "total_records_failed": 9375
  },
  "timestamp": "2025-01-15T14:30:00Z"
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `total_executions` | integer | Total number of executions matching filters |
| `success_rate` | float | Success rate (0.0-1.0) = success_count / total_executions |
| `average_duration_seconds` | float | Average duration of completed executions (only SUCCESS, FAILED, PARTIAL_SUCCESS) |
| `failed_count` | integer | Number of FAILED executions |
| `partial_success_count` | integer | Number of PARTIAL_SUCCESS executions |
| `in_progress_count` | integer | Number of IN_PROGRESS executions |
| `pending_count` | integer | Number of PENDING executions |
| `success_count` | integer | Number of SUCCESS executions |
| `total_records_processed` | integer | Sum of all records_processed across all executions |
| `total_records_failed` | integer | Sum of all records_failed across all executions |

### Example Requests

**Get all KPIs (no filters):**
```bash
GET /api/allocation/executions/kpi
```

**Get KPIs for specific year:**
```bash
GET /api/allocation/executions/kpi?year=2025
```

**Get KPIs for specific month and year:**
```bash
GET /api/allocation/executions/kpi?month=January&year=2025
```

**Get KPIs for specific user:**
```bash
GET /api/allocation/executions/kpi?uploaded_by=john.doe
```

**Get KPIs for specific statuses:**
```bash
# Single status
GET /api/allocation/executions/kpi?status=SUCCESS

# Multiple statuses
GET /api/allocation/executions/kpi?status=SUCCESS&status=FAILED
```

**Combined filters:**
```bash
# Year + status
GET /api/allocation/executions/kpi?year=2025&status=SUCCESS

# Month + year + user
GET /api/allocation/executions/kpi?month=January&year=2025&uploaded_by=john.doe

# Multiple statuses + user
GET /api/allocation/executions/kpi?status=SUCCESS&status=FAILED&uploaded_by=john.doe
```

### Error Responses

**500 Internal Server Error**
```json
{
  "success": false,
  "error": "Failed to get execution KPIs",
  "status_code": 500
}
```

### Caching
- **TTL:** 60 seconds
- **Cache Key:** `allocation_executions_kpi:v1:{month}:{year}:{status}:{uploaded_by}`
  - For multiple statuses, key uses tuple of sorted values
- **Invalidation:** Not automatically invalidated (relies on TTL expiration)

### Use Cases

**Dashboard Summary:**
```bash
# Get overall system health
GET /api/allocation/executions/kpi

# Get monthly performance
GET /api/allocation/executions/kpi?month=January&year=2025
```

**User Performance Tracking:**
```bash
# Get user's overall performance
GET /api/allocation/executions/kpi?uploaded_by=john.doe

# Get user's monthly performance
GET /api/allocation/executions/kpi?month=January&year=2025&uploaded_by=john.doe
```

**Quality Monitoring:**
```bash
# Get only failed executions metrics
GET /api/allocation/executions/kpi?status=FAILED

# Get completed executions metrics
GET /api/allocation/executions/kpi?status=SUCCESS&status=FAILED&status=PARTIAL_SUCCESS
```

**Yearly Trends:**
```bash
# Get all 2025 metrics
GET /api/allocation/executions/kpi?year=2025

# Compare to 2024
GET /api/allocation/executions/kpi?year=2024
```

### Notes

- **Zero Results:** If no executions match the filters, all counts will be 0 and rates will be 0.0
- **Average Duration:** Only includes completed executions (SUCCESS, FAILED, PARTIAL_SUCCESS) that have a duration value
- **Success Rate:** Calculated as `success_count / total_executions`. A rate of 0.85 means 85% success rate
- **Timestamp:** Response includes ISO 8601 timestamp in UTC timezone
- **Performance:** KPI calculation is optimized but may be slower for large datasets. Use specific filters when possible

---

## Status Workflow

```
PENDING → IN_PROGRESS → SUCCESS/FAILED/PARTIAL_SUCCESS
```

### Status Definitions

| Status | Description |
|--------|-------------|
| `PENDING` | Execution created, not yet started |
| `IN_PROGRESS` | Currently processing allocation |
| `SUCCESS` | Completed successfully (all records allocated) |
| `FAILED` | Completed with fatal errors (no allocations) |
| `PARTIAL_SUCCESS` | Completed with some records failing |

### Valid Status Values
Use these exact values for the `status` query parameter:
- `PENDING`
- `IN_PROGRESS`
- `SUCCESS`
- `FAILED`
- `PARTIAL_SUCCESS`

---

## Example Use Cases

### Use Case 1: Monitoring Active Executions
Poll every 10 seconds for in-progress executions and get their details:

```bash
# List active executions (both pending and in-progress)
GET /api/allocation/executions?status=PENDING&status=IN_PROGRESS

# List only in-progress executions
GET /api/allocation/executions?status=IN_PROGRESS

# Get details of a specific active execution
GET /api/allocation/executions/550e8400-e29b-41d4-a716-446655440000
```

**Frontend Implementation:**
```javascript
// Poll for active executions every 10 seconds
setInterval(async () => {
  // Get both pending and in-progress executions
  const response = await fetch('/api/allocation/executions?status=PENDING&status=IN_PROGRESS');
  const data = await response.json();

  // Update UI with active executions
  updateActiveExecutions(data.data);
}, 10000);
```

---

### Use Case 2: Execution History Table
Implement paginated table with 20 records per page:

```bash
# First page
GET /api/allocation/executions?limit=20&offset=0

# Second page
GET /api/allocation/executions?limit=20&offset=20

# Filter by date
GET /api/allocation/executions?month=January&year=2025&limit=20&offset=0
```

**Pagination Logic:**
```
Page 1: offset=0,  limit=20  (records 1-20)
Page 2: offset=20, limit=20  (records 21-40)
Page 3: offset=40, limit=20  (records 41-60)
...
Page N: offset=(N-1)*20, limit=20
```

---

### Use Case 3: Error Investigation
Identify and debug failed executions:

```bash
# Step 1: Get all failed executions
GET /api/allocation/executions?status=FAILED

# Step 2: Get details of failed execution
GET /api/allocation/executions/{execution_id}

# Step 3: Analyze error fields
# - error_message: Human-readable error
# - error_type: Error category
# - stack_trace: Full Python traceback
# - config_snapshot: Configuration used at execution time
```

---

### Use Case 4: Multiple Status Filtering
Filter by multiple statuses to get combined results:

```bash
# Get all completed executions (success and failed)
GET /api/allocation/executions?status=SUCCESS&status=FAILED&status=PARTIAL_SUCCESS

# Get all non-active executions for review
GET /api/allocation/executions?status=SUCCESS&status=FAILED

# Get all executions that need attention (failed or in-progress)
GET /api/allocation/executions?status=FAILED&status=IN_PROGRESS

# Combined with date filter - get all January 2025 completed executions
GET /api/allocation/executions?month=January&year=2025&status=SUCCESS&status=FAILED&status=PARTIAL_SUCCESS
```

**Use Cases:**
- **Dashboard Summary**: Show all completed executions (success + failed + partial)
- **Audit Review**: Review all non-successful executions (failed + partial_success)
- **Active Monitoring**: Track all active states (pending + in_progress)
- **Health Dashboard**: Show success vs failure rates by filtering both statuses

**Frontend Example:**
```javascript
// Get completion statistics
async function getCompletionStats(month, year) {
  // Get all completed executions
  const response = await fetch(
    `/api/allocation/executions?month=${month}&year=${year}&status=SUCCESS&status=FAILED&status=PARTIAL_SUCCESS&limit=100`
  );
  const data = await response.json();

  // Calculate statistics
  const total = data.pagination.total;
  const success = data.data.filter(e => e.status === 'SUCCESS').length;
  const failed = data.data.filter(e => e.status === 'FAILED').length;
  const partial = data.data.filter(e => e.status === 'PARTIAL_SUCCESS').length;

  return { total, success, failed, partial };
}
```

---

### Use Case 5: User Activity Report
Generate reports for specific users:

```bash
# Get all executions by a specific user
GET /api/allocation/executions?uploaded_by=john.doe

# Get successful executions by user
GET /api/allocation/executions?uploaded_by=john.doe&status=SUCCESS

# Get failed executions by user (for audit)
GET /api/allocation/executions?uploaded_by=john.doe&status=FAILED
```

---

### Use Case 6: Monthly Execution Summary
Get all executions for a specific month/year:

```bash
# All January 2025 executions
GET /api/allocation/executions?month=January&year=2025

# Successful January 2025 executions
GET /api/allocation/executions?month=January&year=2025&status=SUCCESS

# All completed January 2025 executions (for reporting)
GET /api/allocation/executions?month=January&year=2025&status=SUCCESS&status=FAILED&status=PARTIAL_SUCCESS

# Get statistics by iterating through all pages
GET /api/allocation/executions?month=January&year=2025&limit=100&offset=0
```

---

## Performance Notes

### 1. Caching Strategy

**List Endpoint:**
- Cached for 30 seconds
- Cache invalidated when:
  - New execution is created
  - Any execution status changes
  - Execution completes

**Detail Endpoint:**
- Active executions (PENDING/IN_PROGRESS): 5 seconds TTL
- Completed executions (SUCCESS/FAILED): 1 hour TTL
- Cache invalidated when specific execution status changes

**Benefits:**
- Reduced database load
- Faster response times for frequently accessed data
- Active executions stay fresh for monitoring
- Completed executions cached longer (immutable)

---

### 2. Pagination

**Default Settings:**
- Default limit: 50 records
- Maximum limit: 100 records
- Minimum offset: 0

**Best Practices:**
- Use smaller page sizes (20-50) for better performance
- Implement lazy loading for infinite scroll UIs
- Cache page results on frontend for back/forward navigation

---

### 3. Filtering

**All filters can be combined:**
```bash
# Single status filter
GET /api/allocation/executions?month=January&year=2025&status=SUCCESS&uploaded_by=john.doe&limit=20&offset=0

# Multiple status filter
GET /api/allocation/executions?month=January&year=2025&status=SUCCESS&status=FAILED&uploaded_by=john.doe&limit=20&offset=0
```

**Filter Validation:**
- Month: Must be valid month name (January-December)
- Year: Must be in range 2020-2100
- Status: Must be one of the valid status values (can specify multiple)
  - Multiple statuses are combined with OR logic (returns executions matching ANY status)
  - Example: `?status=SUCCESS&status=FAILED` returns executions that are either SUCCESS OR FAILED
- All filters are optional

**Multiple Status Benefits:**
- Reduce API calls - get multiple statuses in one request
- Flexible filtering for dashboards and reports
- Better performance than making multiple requests

---

### 4. Ordering

**Results are always ordered by StartTime DESC:**
- Newest executions appear first
- Most relevant for monitoring and audit trails
- No custom ordering options (keeps API simple)

---

### 5. Query Optimization

**Database Indexes:**
Ensure the following indexes exist for optimal performance:
- `idx_start_time` on `StartTime` (for ordering)
- `idx_month_year` on `(Month, Year)` (for date filtering)
- `idx_status` on `Status` (for status filtering)
- `idx_uploaded_by` on `UploadedBy` (for user filtering)

**Query Performance:**
- List query: ~50ms (with indexes)
- Detail query: ~10ms (UUID primary key lookup)
- Cache hit: ~1ms

---

## Notes

### Roster Fallback
When `roster_was_fallback` is `true`, it means:
- The requested roster for the target month/year was not found
- System automatically used the latest available roster
- Check `roster_month_used` and `roster_year_used` for actual roster used
- This is normal behavior, not an error

### Configuration Snapshot
The `config_snapshot` field captures the exact configuration used at execution time:
- **Structure**: Organized by month-year (e.g., "January 2025", "February 2025")
- **Per-Month Configs**: Each month contains both Domestic and Global configurations
- **Parameters**: Working days, occupancy, shrinkage, work hours for each work type
- **Multi-Month Support**: Captures all months processed in a single execution
- **Use Cases**:
  - Allows exact reproduction of results
  - Useful for debugging and audit trails
  - Track configuration changes over time
  - Identify discrepancies between months
- **Storage**: Stored as JSON in database `ConfigSnapshot` column

### Error Handling
All errors include:
- `success: false` flag
- `error` message string
- `status_code` HTTP status code
- Optional additional error details in `detail` field

### Rate Limiting
Consider implementing rate limiting for:
- Monitoring endpoints (10 requests/second)
- List endpoints (100 requests/minute)
- Detail endpoints (200 requests/minute)

---

## Changelog

### Version 1.2.0 (2025-01-04)
- **NEW**: Added KPI endpoint (`GET /api/allocation/executions/kpi`)
  - Provides aggregated metrics: total executions, success rate, average duration, status breakdowns
  - Supports flexible filtering: year only, month+year, status(es), uploaded_by, or any combination
  - Includes total records processed and failed across all matching executions
  - Cached for 60 seconds for better performance
  - Perfect for dashboards, user performance tracking, and quality monitoring
- Added comprehensive KPI endpoint documentation with examples
- Updated Table of Contents to include KPI endpoint section

### Version 1.1.0 (2025-01-04)
- **NEW**: Added multiple status filtering support
  - `status` parameter now accepts multiple values (e.g., `?status=SUCCESS&status=FAILED`)
  - Enables filtering by multiple statuses in a single request
  - Uses OR logic - returns executions matching ANY of the specified statuses
  - Cache key updated to handle multiple statuses (comma-separated sorted values)
- Updated examples and use cases for multiple status filtering
- Added Use Case 4: Multiple Status Filtering with practical examples

### Version 1.0.0 (2025-01-03)
- Initial API specification
- Added list executions endpoint
- Added get execution details endpoint
- Implemented caching with dynamic TTL
- Added comprehensive filtering and pagination
