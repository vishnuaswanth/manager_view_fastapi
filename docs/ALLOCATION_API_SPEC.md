# Allocation API Specification

## Overview

The Allocation API provides endpoints for downloading allocation reports and tracking allocation execution history. Reports are generated during the allocation process and linked to specific execution runs via `execution_id`.

**Base URL:** `/api` (or root `/` for legacy endpoints)

**Report Types:**
- `bucket_summary` - Bucket structure with vendor distribution details
- `bucket_after_allocation` - Post-allocation bucket state showing allocated vs unallocated vendors
- `roster_allotment` - Vendor-level allocation assignments per month

---

## Table of Contents

1. [Report Download Endpoints (by execution_id)](#report-download-endpoints-by-execution_id)
2. [Report Download Endpoints (by month/year - Legacy)](#report-download-endpoints-by-monthyear---legacy)
3. [Execution Tracking Endpoints](#execution-tracking-endpoints)
4. [Data Models](#data-models)
5. [Error Responses](#error-responses)

---

## Report Download Endpoints (by execution_id)

### 1. Download Bucket Summary Report

Download bucket summary allocation report for a specific execution.

**Endpoint:** `GET /api/allocation/executions/{execution_id}/reports/bucket_summary`

**Path Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| execution_id | string (UUID) | Yes | Unique execution identifier |

**Response:**
- **Content-Type:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **File Format:** Excel (.xlsx)
- **Sheets:**
  - `Bucket_Summary` - Overview of all buckets with vendor counts
  - `Vendor_Details` - Detailed vendor information per bucket

**Response Headers:**
```
Content-Disposition: attachment; filename=bucket_summary_{execution_id}.xlsx
```

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/allocation/executions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/reports/bucket_summary" \
  -H "accept: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" \
  --output bucket_summary.xlsx
```

**Status Codes:**
- `200 OK` - Report downloaded successfully
- `404 Not Found` - Report not found for execution_id
- `500 Internal Server Error` - Server error during report generation

---

### 2. Download Bucket After Allocation Report

Download post-allocation bucket state report for a specific execution.

**Endpoint:** `GET /api/allocation/executions/{execution_id}/reports/bucket_after_allocation`

**Path Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| execution_id | string (UUID) | Yes | Unique execution identifier |

**Response:**
- **Content-Type:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **File Format:** Excel (.xlsx)
- **Sheet Content:** Allocation status per bucket (allocated vs unallocated counts)

**Response Headers:**
```
Content-Disposition: attachment; filename=buckets_after_allocation_{execution_id}.xlsx
```

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/allocation/executions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/reports/bucket_after_allocation" \
  -H "accept: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" \
  --output buckets_after_allocation.xlsx
```

**Status Codes:**
- `200 OK` - Report downloaded successfully
- `404 Not Found` - Report not found for execution_id
- `500 Internal Server Error` - Server error during report generation

---

### 3. Download Roster Allotment Report

Download vendor-level allocation assignments for a specific execution.

**Endpoint:** `GET /api/allocation/executions/{execution_id}/reports/roster_allotment`

**Path Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| execution_id | string (UUID) | Yes | Unique execution identifier |

**Response:**
- **Content-Type:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **File Format:** Excel (.xlsx)
- **Sheet Content:** Per-vendor allocation details with monthly assignments

**Response Headers:**
```
Content-Disposition: attachment; filename=roster_allotment_{execution_id}.xlsx
```

**Roster Allotment Columns:**
- Vendor identification: `FirstName`, `LastName`, `CN`
- Work details: `PrimaryPlatform`, `NewWorkType`, `Location`, `State`
- Status: `Status` (Allocated/Not Allocated)
- Per-month details: `{Month}_LOB`, `{Month}_State`, `{Month}_Worktype`

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/allocation/executions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/reports/roster_allotment" \
  -H "accept: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" \
  --output roster_allotment.xlsx
```

**Status Codes:**
- `200 OK` - Report downloaded successfully
- `404 Not Found` - Report not found for execution_id
- `500 Internal Server Error` - Server error during report generation

---

## Report Download Endpoints (by month/year - Legacy)

**⚠️ Backward Compatibility:** These endpoints fetch the **latest execution's report** for the specified month/year.

**Recommended:** Use execution_id-based endpoints for accessing specific execution reports.

---

### 4. Download Bucket Summary Report (Legacy)

**Endpoint:** `GET /download_allocation_report/bucket_summary`

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| month | string | Yes | Month name (e.g., "January", "February") |
| year | integer | Yes | Year (e.g., 2025) |

**Response:** Same as execution_id-based endpoint

**Response Headers:**
```
Content-Disposition: attachment; filename=bucket_summary_{month}_{year}.xlsx
```

**Example Request:**
```bash
curl -X GET "http://localhost:8000/download_allocation_report/bucket_summary?month=January&year=2025" \
  -H "accept: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" \
  --output bucket_summary_jan_2025.xlsx
```

**Status Codes:**
- `200 OK` - Report downloaded successfully (latest execution)
- `404 Not Found` - No reports found for month/year
- `500 Internal Server Error` - Server error during report generation

---

### 5. Download Bucket After Allocation Report (Legacy)

**Endpoint:** `GET /download_allocation_report/bucket_after_allocation`

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| month | string | Yes | Month name (e.g., "January", "February") |
| year | integer | Yes | Year (e.g., 2025) |

**Response:** Same as execution_id-based endpoint

**Response Headers:**
```
Content-Disposition: attachment; filename=buckets_after_allocation_{month}_{year}.xlsx
```

**Example Request:**
```bash
curl -X GET "http://localhost:8000/download_allocation_report/bucket_after_allocation?month=January&year=2025" \
  -H "accept: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" \
  --output buckets_after_allocation_jan_2025.xlsx
```

---

### 6. Download Roster Allotment Report (Legacy)

**Endpoint:** `GET /download_allocation_report/roster_allotment`

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| month | string | Yes | Month name (e.g., "January", "February") |
| year | integer | Yes | Year (e.g., 2025) |

**Response:** Same as execution_id-based endpoint

**Response Headers:**
```
Content-Disposition: attachment; filename=roster_allotment_{month}_{year}.xlsx
```

**Example Request:**
```bash
curl -X GET "http://localhost:8000/download_allocation_report/roster_allotment?month=January&year=2025" \
  -H "accept: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" \
  --output roster_allotment_jan_2025.xlsx
```

---

## Execution Tracking Endpoints

### 7. List Allocation Executions

List allocation execution history with filtering and pagination.

**Endpoint:** `GET /api/allocation/executions`

**Query Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| month | string | No | - | Filter by month (e.g., "January") |
| year | integer | No | - | Filter by year (e.g., 2025) |
| status | string[] | No | - | Filter by status (can specify multiple): PENDING, IN_PROGRESS, SUCCESS, FAILED, PARTIAL_SUCCESS |
| uploaded_by | string | No | - | Filter by username |
| limit | integer | No | 50 | Max records to return (max: 100) |
| offset | integer | No | 0 | Pagination offset |

**Multiple Status Filtering:**

You can filter by multiple statuses by specifying the `status` parameter multiple times:

```bash
# Filter by SUCCESS or FAILED status
GET /api/allocation/executions?status=SUCCESS&status=FAILED

# Filter by all active statuses (PENDING and IN_PROGRESS)
GET /api/allocation/executions?status=PENDING&status=IN_PROGRESS
```

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "execution_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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

**Cache:**
- **TTL:** 30 seconds
- **Key:** `allocation_executions:v1:{month}:{year}:{status}:{uploaded_by}:{limit}:{offset}`
  - For multiple statuses, key uses comma-separated sorted values: `status1,status2`

**Example Requests:**
```bash
# List all successful executions for January 2025
curl -X GET "http://localhost:8000/api/allocation/executions?month=January&year=2025&status=SUCCESS&limit=20&offset=0" \
  -H "accept: application/json"

# List both successful and failed executions
curl -X GET "http://localhost:8000/api/allocation/executions?month=January&year=2025&status=SUCCESS&status=FAILED&limit=20&offset=0" \
  -H "accept: application/json"

# List all active/in-progress executions
curl -X GET "http://localhost:8000/api/allocation/executions?status=PENDING&status=IN_PROGRESS" \
  -H "accept: application/json"
```

**Status Codes:**
- `200 OK` - Executions retrieved successfully
- `500 Internal Server Error` - Server error

---

### 8. Get Execution Details

Get detailed information about a specific allocation execution.

**Endpoint:** `GET /api/allocation/executions/{execution_id}`

**Path Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| execution_id | string (UUID) | Yes | Unique execution identifier |

**Response:**
```json
{
  "success": true,
  "data": {
    "execution_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "month": "January",
    "year": 2025,
    "status": "SUCCESS",
    "start_time": "2025-01-15T10:30:00",
    "end_time": "2025-01-15T10:35:00",
    "duration_seconds": 300.5,
    "forecast_filename": "forecast_jan_2025.xlsx",
    "roster_filename": "roster_jan_2025.xlsx",
    "roster_month_used": "January",
    "roster_year_used": 2025,
    "roster_was_fallback": false,
    "uploaded_by": "john.doe",
    "records_processed": 1250,
    "records_failed": 0,
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
            "occupancy": 0.95,
            "shrinkage": 0.10,
            "work_hours": 9
          }
        }
      }
    },
    "created_datetime": "2025-01-15T10:30:00"
  }
}
```

**Cache:**
- **TTL (Dynamic):**
  - `PENDING`/`IN_PROGRESS`: 5 seconds (active monitoring)
  - `SUCCESS`/`FAILED`: 1 hour (immutable data)
- **Key:** `allocation_execution_detail:v1:{execution_id}`

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/allocation/executions/a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -H "accept: application/json"
```

**Status Codes:**
- `200 OK` - Execution details retrieved successfully
- `404 Not Found` - Execution not found
- `500 Internal Server Error` - Server error

---

## Data Models

### Execution Status

| Status | Description |
|--------|-------------|
| PENDING | Execution created but not started |
| IN_PROGRESS | Allocation process running |
| SUCCESS | Allocation completed successfully |
| FAILED | Allocation failed with errors |
| PARTIAL_SUCCESS | Allocation completed with warnings |

### Report Types

| Type | Description | File Sheets |
|------|-------------|-------------|
| bucket_summary | Bucket structure overview | Bucket_Summary, Vendor_Details |
| bucket_after_allocation | Post-allocation bucket state | Single sheet |
| roster_allotment | Vendor allocation assignments | Single sheet |

---

## Error Responses

All endpoints follow a consistent error response format:

```json
{
  "success": false,
  "message": "Error description",
  "error": "Detailed error message (optional)"
}
```

### Common Error Codes

| Status Code | Description | Common Causes |
|-------------|-------------|---------------|
| 400 Bad Request | Invalid request parameters | Invalid month name, year out of range |
| 404 Not Found | Resource not found | Execution_id doesn't exist, no reports for month/year |
| 500 Internal Server Error | Server processing error | Database connection issues, file generation errors |

### Example Error Responses

**404 - Report Not Found:**
```json
{
  "success": false,
  "message": "No bucket_summary report found for execution a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**404 - Execution Not Found:**
```json
{
  "success": false,
  "message": "Execution with ID a1b2c3d4-e5f6-7890-abcd-ef1234567890 not found"
}
```

**500 - Internal Server Error:**
```json
{
  "success": false,
  "message": "Failed to download report",
  "error": "Database connection timeout"
}
```

---

## Usage Workflow

### Recommended Flow

1. **Upload Forecast File** → Triggers allocation process → Returns `execution_id`

2. **Monitor Execution Progress:**
   ```bash
   GET /api/allocation/executions/{execution_id}
   # Check status until SUCCESS or FAILED
   ```

3. **Download Reports (once status = SUCCESS):**
   ```bash
   GET /api/allocation/executions/{execution_id}/reports/bucket_summary
   GET /api/allocation/executions/{execution_id}/reports/bucket_after_allocation
   GET /api/allocation/executions/{execution_id}/reports/roster_allotment
   ```

### Historical Access

**View execution history:**
```bash
GET /api/allocation/executions?month=January&year=2025&status=SUCCESS
# Returns list of executions with execution_ids
```

**Download historical report:**
```bash
GET /api/allocation/executions/{historical_execution_id}/reports/roster_allotment
```

---

## Rate Limiting & Caching

- **Execution List:** Cached for 30 seconds
- **Execution Details:**
  - In-progress: 5 seconds (frequent updates)
  - Completed: 1 hour (immutable)
- **Report Downloads:** No caching (streaming response)

---

## Retention Policy

Reports are automatically cleaned up to prevent unbounded storage growth:

- **Policy:** Keep last **10 executions** per month/year
- **Trigger:** After successful allocation completion
- **Behavior:** Older execution reports are deleted automatically

**Example:** If you run allocation 15 times for January 2025, only the 10 most recent execution reports are retained.

---

## Notes

1. **execution_id Format:** UUID v4 (36 characters including hyphens)
   - Example: `a1b2c3d4-e5f6-7890-abcd-ef1234567890`

2. **Month Names:** Full month names required (e.g., "January", not "Jan")

3. **File Encoding:** All Excel files use UTF-8 encoding

4. **Timestamps:** ISO 8601 format with timezone (e.g., `2025-01-15T10:30:00`)

5. **Backward Compatibility:** Legacy month/year endpoints will continue to work but always return the latest execution's reports

---

## Support

For API issues or questions, contact the development team or check the main project documentation.

**Last Updated:** 2025-01-04
