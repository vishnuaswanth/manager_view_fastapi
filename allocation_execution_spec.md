# Allocation Execution API Specification

## Overview
This document describes the API endpoints for managing and monitoring allocation executions in the Manager View FastAPI application.

**Base URL:** `http://your-domain.com`

**Version:** v1

---

## Table of Contents
1. [List Allocation Executions](#1-list-allocation-executions)
2. [Get Execution Details](#2-get-execution-details)
3. [Status Workflow](#status-workflow)
4. [Example Use Cases](#example-use-cases)
5. [Performance Notes](#performance-notes)

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
| `status` | string | No | - | Filter by status: `PENDING`, `IN_PROGRESS`, `SUCCESS`, `FAILED`, `PARTIAL_SUCCESS` |
| `uploaded_by` | string | No | - | Filter by username |
| `limit` | integer | No | 50 | Max records per page (max: 100) |
| `offset` | integer | No | 0 | Pagination offset |

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

**Filter by status:**
```bash
GET /api/allocation/executions?status=SUCCESS
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
# List active executions
GET /api/allocation/executions?status=IN_PROGRESS

# Get details of a specific active execution
GET /api/allocation/executions/550e8400-e29b-41d4-a716-446655440000
```

**Frontend Implementation:**
```javascript
// Poll for active executions every 10 seconds
setInterval(async () => {
  const response = await fetch('/api/allocation/executions?status=IN_PROGRESS');
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

### Use Case 4: User Activity Report
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

### Use Case 5: Monthly Execution Summary
Get all executions for a specific month/year:

```bash
# All January 2025 executions
GET /api/allocation/executions?month=January&year=2025

# Successful January 2025 executions
GET /api/allocation/executions?month=January&year=2025&status=SUCCESS

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
GET /api/allocation/executions?month=January&year=2025&status=SUCCESS&uploaded_by=john.doe&limit=20&offset=0
```

**Filter Validation:**
- Month: Must be valid month name (January-December)
- Year: Must be in range 2020-2100
- Status: Must be one of the valid status values
- All filters are optional

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
- Month configuration (working days, occupancy, shrinkage, work hours)
- Allows reproduction of results
- Useful for debugging and audit trails
- Stored as JSON in database

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

### Version 1.0.0 (2025-01-03)
- Initial API specification
- Added list executions endpoint
- Added get execution details endpoint
- Implemented caching with dynamic TTL
- Added comprehensive filtering and pagination
