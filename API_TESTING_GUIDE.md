# Edit View & History API Testing Guide

Complete guide for testing Edit View and History APIs using curl or Postman.

**Base URL**: `http://localhost:8888`

---

## Table of Contents
1. [Bench Allocation APIs](#bench-allocation-apis)
2. [CPH (Cases Per Hour) Update APIs](#cph-update-apis)
3. [History Log APIs](#history-log-apis)
4. [Common Error Responses](#common-error-responses)

---

## Bench Allocation APIs

### 1. Get Available Allocation Reports

**Endpoint**: `GET /api/allocation-reports`

**Description**: Retrieve list of available allocation executions with report availability status.

**Query Parameters**:
- `month` (optional): Filter by month name (e.g., "April")
- `year` (optional): Filter by year (e.g., 2025)

**Example curl**:
```bash
curl -X GET "http://localhost:8888/api/allocation-reports?month=April&year=2025"
```

**Example Response**:
```json
{
  "success": true,
  "data": [
    {
      "execution_id": "550e8400-e29b-41d4-a716-446655440000",
      "month": "April",
      "year": 2025,
      "status": "SUCCESS",
      "created_at": "2025-01-12T10:30:00",
      "reports_available": {
        "bucket_summary": true,
        "bucket_after_allocation": true,
        "roster_allotment": true
      },
      "bench_allocation_completed": false
    }
  ]
}
```

---

### 2. Preview Bench Allocation

**Endpoint**: `POST /api/bench-allocation/preview`

**Description**: Preview bench allocation changes before applying them. Calculates how unallocated vendors will be distributed across forecast demands.

**Request Body**:
```json
{
  "month": "April",
  "year": 2025
}
```

**Example curl**:
```bash
curl -X POST "http://localhost:8888/api/bench-allocation/preview" \
  -H "Content-Type: application/json" \
  -d '{
    "month": "April",
    "year": 2025
  }'
```

**Example Response**:
```json
{
  "success": true,
  "modified_records": [
    {
      "case_id": "CASE-001",
      "main_lob": "Amisys Medicaid Domestic",
      "state": "CA",
      "case_type": "Claims Processing",
      "target_cph": 25.5,
      "target_cph_change": 0,
      "Jun-25": {
        "forecast": 10000,
        "fte_req": 20,
        "fte_avail": 15,
        "capacity": 7500,
        "forecast_change": 0,
        "fte_req_change": 0,
        "fte_avail_change": 5,
        "capacity_change": 2500
      },
      "modified_fields": ["Jun-25.fte_avail", "Jun-25.capacity"]
    }
  ],
  "months": {
    "month1": "Jun-25",
    "month2": "Jul-25",
    "month3": "Aug-25",
    "month4": "Sep-25",
    "month5": "Oct-25",
    "month6": "Nov-25"
  },
  "summary": {
    "total_records_modified": 15,
    "Jun-25": {
      "total_fte_available": {
        "old": 150,
        "new": 175
      }
    }
  }
}
```

---

### 3. Apply Bench Allocation

**Endpoint**: `POST /api/bench-allocation/update`

**Description**: Apply bench allocation changes to the forecast database. Creates a history log for tracking.

**Request Body**:
```json
{
  "month": "April",
  "year": 2025,
  "months": {
    "month1": "Jun-25",
    "month2": "Jul-25",
    "month3": "Aug-25",
    "month4": "Sep-25",
    "month5": "Oct-25",
    "month6": "Nov-25"
  },
  "modified_records": [
    {
      "case_id": "CASE-001",
      "main_lob": "Amisys Medicaid Domestic",
      "state": "CA",
      "case_type": "Claims Processing",
      "target_cph": 25.5,
      "target_cph_change": 0,
      "Jun-25": {
        "forecast": 10000,
        "fte_req": 20,
        "fte_avail": 18,
        "capacity": 9000,
        "forecast_change": 0,
        "fte_req_change": 0,
        "fte_avail_change": 3,
        "capacity_change": 1500
      },
      "modified_fields": ["Jun-25.fte_avail", "Jun-25.capacity"]
    }
  ],
  "user_notes": "Applied bench allocation for April 2025 - distributed 50 bench vendors"
}
```

**Example curl**:
```bash
curl -X POST "http://localhost:8888/api/bench-allocation/update" \
  -H "Content-Type: application/json" \
  -d '{
    "month": "April",
    "year": 2025,
    "months": {
      "month1": "Jun-25",
      "month2": "Jul-25",
      "month3": "Aug-25",
      "month4": "Sep-25",
      "month5": "Oct-25",
      "month6": "Nov-25"
    },
    "modified_records": [
      {
        "case_id": "CASE-001",
        "main_lob": "Amisys Medicaid Domestic",
        "state": "CA",
        "case_type": "Claims Processing",
        "target_cph": 25.5,
        "target_cph_change": 0,
        "Jun-25": {
          "forecast": 10000,
          "fte_req": 20,
          "fte_avail": 18,
          "capacity": 9000,
          "forecast_change": 0,
          "fte_req_change": 0,
          "fte_avail_change": 3,
          "capacity_change": 1500
        },
        "modified_fields": ["Jun-25.fte_avail"]
      }
    ],
    "user_notes": "Applied bench allocation"
  }'
```

**Example Response**:
```json
{
  "success": true,
  "message": "Bench allocation completed successfully",
  "history_log_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "records_modified": 15,
  "execution_id": "550e8400-e29b-41d4-a716-446655440000",
  "bench_allocation_completed_at": "2025-01-12T14:30:00"
}
```

---

## CPH (Cases Per Hour) Update APIs

### 4. Get Target CPH Data

**Endpoint**: `GET /api/edit-view/target-cph/data/`

**Description**: Retrieve current Target CPH values for all forecast records.

**Query Parameters**:
- `month` (required): Month name
- `year` (required): Year

**Example curl**:
```bash
curl -X GET "http://localhost:8888/api/edit-view/target-cph/data/?month=April&year=2025"
```

**Example Response**:
```json
{
  "success": true,
  "data": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "lob": "Amisys Medicaid Domestic",
      "case_type": "Claims Processing",
      "target_cph": 25.5
    },
    {
      "id": "660e8400-e29b-41d4-a716-446655440111",
      "lob": "Facets Medicare Global",
      "case_type": "Enrollment",
      "target_cph": 30.0
    }
  ],
  "month": "April",
  "year": 2025
}
```

---

### 5. Preview CPH Changes

**Endpoint**: `POST /api/edit-view/target-cph/preview/`

**Description**: Preview the impact of Target CPH changes on forecast calculations.

**Request Body**:
```json
{
  "month": "April",
  "year": 2025,
  "modified_records": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "lob": "Amisys Medicaid Domestic",
      "case_type": "Claims Processing",
      "target_cph": 25.5,
      "modified_target_cph": 28.0
    }
  ]
}
```

**Example curl**:
```bash
curl -X POST "http://localhost:8888/api/edit-view/target-cph/preview/" \
  -H "Content-Type: application/json" \
  -d '{
    "month": "April",
    "year": 2025,
    "modified_records": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "lob": "Amisys Medicaid Domestic",
        "case_type": "Claims Processing",
        "target_cph": 25.5,
        "modified_target_cph": 28.0
      }
    ]
  }'
```

**Example Response**:
```json
{
  "success": true,
  "modified_records": [
    {
      "case_id": "CASE-001",
      "main_lob": "Amisys Medicaid Domestic",
      "state": "CA",
      "case_type": "Claims Processing",
      "target_cph": 28.0,
      "target_cph_change": 2.5,
      "Jun-25": {
        "forecast": 10000,
        "fte_req": 18,
        "fte_avail": 15,
        "capacity": 8400,
        "forecast_change": 0,
        "fte_req_change": -2,
        "fte_avail_change": 0,
        "capacity_change": 900
      },
      "modified_fields": ["target_cph", "Jun-25.fte_req", "Jun-25.capacity"]
    }
  ],
  "months": {
    "month1": "Jun-25",
    "month2": "Jul-25",
    "month3": "Aug-25",
    "month4": "Sep-25",
    "month5": "Oct-25",
    "month6": "Nov-25"
  }
}
```

---

### 6. Apply CPH Changes

**Endpoint**: `POST /api/edit-view/target-cph/update/`

**Description**: Apply Target CPH changes and update forecast calculations in the database.

**Request Body**:
```json
{
  "month": "April",
  "year": 2025,
  "months": {
    "month1": "Jun-25",
    "month2": "Jul-25",
    "month3": "Aug-25",
    "month4": "Sep-25",
    "month5": "Oct-25",
    "month6": "Nov-25"
  },
  "modified_records": [
    {
      "case_id": "CASE-001",
      "main_lob": "Amisys Medicaid Domestic",
      "state": "CA",
      "case_type": "Claims Processing",
      "target_cph": 28.0,
      "target_cph_change": 2.5,
      "Jun-25": {
        "forecast": 10000,
        "fte_req": 18,
        "fte_avail": 15,
        "capacity": 8400,
        "forecast_change": 0,
        "fte_req_change": -2,
        "fte_avail_change": 0,
        "capacity_change": 900
      },
      "modified_fields": ["target_cph", "Jun-25.fte_req", "Jun-25.capacity"]
    }
  ],
  "user_notes": "Updated Target CPH for Claims Processing to improve accuracy"
}
```

**Example curl**:
```bash
curl -X POST "http://localhost:8888/api/edit-view/target-cph/update/" \
  -H "Content-Type: application/json" \
  -d '{
    "month": "April",
    "year": 2025,
    "months": {
      "month1": "Jun-25",
      "month2": "Jul-25",
      "month3": "Aug-25",
      "month4": "Sep-25",
      "month5": "Oct-25",
      "month6": "Nov-25"
    },
    "modified_records": [
      {
        "case_id": "CASE-001",
        "main_lob": "Amisys Medicaid Domestic",
        "state": "CA",
        "case_type": "Claims Processing",
        "target_cph": 28.0,
        "target_cph_change": 2.5,
        "Jun-25": {
          "forecast": 10000,
          "fte_req": 18,
          "fte_avail": 15,
          "capacity": 8400,
          "forecast_change": 0,
          "fte_req_change": -2,
          "fte_avail_change": 0,
          "capacity_change": 900
        },
        "modified_fields": ["target_cph"]
      }
    ],
    "user_notes": "Updated Target CPH"
  }'
```

**Example Response**:
```json
{
  "success": true,
  "message": "CPH update completed successfully",
  "history_log_id": "8d0e7780-8536-51ef-b058-f18ed2g01bf8",
  "records_modified": 5
}
```

---

## History Log APIs

### 7. List History Logs

**Endpoint**: `GET /api/history-log`

**Description**: Retrieve paginated list of history logs with optional filters.

**Query Parameters**:
- `month` (optional): Filter by month name
- `year` (optional): Filter by year
- `change_types` (optional): Filter by change types (can specify multiple)
- `page` (optional, default=1): Page number (1-indexed)
- `limit` (optional, default=25, max=100): Records per page

**Example curl - Get all history logs**:
```bash
curl -X GET "http://localhost:8888/api/history-log?page=1&limit=25"
```

**Example curl - Filter by month and year**:
```bash
curl -X GET "http://localhost:8888/api/history-log?month=April&year=2025&page=1&limit=10"
```

**Example curl - Filter by change types**:
```bash
curl -X GET "http://localhost:8888/api/history-log?change_types=Bench%20Allocation&change_types=CPH%20Update&page=1&limit=25"
```

**Example Response**:
```json
{
  "success": true,
  "data": [
    {
      "history_log_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "month": "April",
      "year": 2025,
      "change_type": "Bench Allocation",
      "user": "system",
      "created_at": "2025-01-12T14:30:00",
      "description": "Applied bench allocation for April 2025",
      "records_modified": 15,
      "summary_data": {
        "Jun-25": {
          "total_fte_available": {
            "old": 150,
            "new": 175
          }
        }
      }
    },
    {
      "history_log_id": "8d0e7780-8536-51ef-b058-f18ed2g01bf8",
      "month": "April",
      "year": 2025,
      "change_type": "CPH Update",
      "user": "system",
      "created_at": "2025-01-12T15:45:00",
      "description": "Updated Target CPH values",
      "records_modified": 5,
      "summary_data": {
        "total_cph_changes": 5
      }
    }
  ],
  "total": 2,
  "page": 1,
  "limit": 25,
  "has_more": false
}
```

---

### 8. Download History Log as Excel

**Endpoint**: `GET /api/history-log/{history_log_id}/download`

**Description**: Download a specific history log as an Excel file with detailed change information.

**Path Parameters**:
- `history_log_id` (required): UUID of the history log

**Example curl**:
```bash
curl -X GET "http://localhost:8888/api/history-log/7c9e6679-7425-40de-944b-e07fc1f90ae7/download" \
  --output history_log.xlsx
```

**Response**: Excel file download with two sheets:
- **Summary Sheet**: Change metadata (month, year, user, timestamp, records modified)
- **Changes Sheet**: Field-level modifications (field name, old value, new value, delta)

---

## Common Error Responses

### 400 Bad Request
```json
{
  "success": false,
  "error": "modified_records cannot be empty"
}
```

### 404 Not Found
```json
{
  "success": false,
  "error": "History log entry not found"
}
```

### 500 Internal Server Error
```json
{
  "success": false,
  "error": "Database operation failed"
}
```

---

## Testing Workflow

### Complete Bench Allocation Workflow:
```bash
# Step 1: Preview bench allocation
curl -X POST "http://localhost:8888/api/bench-allocation/preview" \
  -H "Content-Type: application/json" \
  -d '{"month": "April", "year": 2025}'

# Step 2: Apply bench allocation (use response from preview)
curl -X POST "http://localhost:8888/api/bench-allocation/update" \
  -H "Content-Type: application/json" \
  -d '{ ... use preview response data ... }'

# Step 3: Verify history log created
curl -X GET "http://localhost:8888/api/history-log?month=April&year=2025"
```

### Complete CPH Update Workflow:
```bash
# Step 1: Get current CPH data
curl -X GET "http://localhost:8888/api/edit-view/target-cph/data/?month=April&year=2025"

# Step 2: Preview CPH changes
curl -X POST "http://localhost:8888/api/edit-view/target-cph/preview/" \
  -H "Content-Type: application/json" \
  -d '{ ... with modified_target_cph values ... }'

# Step 3: Apply CPH changes (use response from preview)
curl -X POST "http://localhost:8888/api/edit-view/target-cph/update/" \
  -H "Content-Type: application/json" \
  -d '{ ... use preview response data ... }'

# Step 4: Download history log
curl -X GET "http://localhost:8888/api/history-log/{history_log_id}/download" \
  --output history.xlsx
```

---

## Notes

1. **Month Names**: Use full month names (e.g., "April", "January") - case-sensitive
2. **Years**: Must be between 2020-2050
3. **State Codes**: Use 2-letter uppercase codes (e.g., "CA", "TX", "NY")
4. **Target CPH**: Must be > 0 and ≤ 200
5. **Modified Records**: Must have at least 1 record and include all required fields
6. **User Notes**: Optional but recommended for tracking change reasons (max 1000 characters)

---

## Change Types

Valid change types for history log filtering:
- `Bench Allocation`
- `CPH Update`
- `Forecast Update`

---

**Last Updated**: January 2026
