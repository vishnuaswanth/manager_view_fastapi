# Edit View API Specification

## Overview
APIs for bench allocation and Target CPH management with preview/approval workflow and history tracking.

---

## 1. Get Allocation Reports

**Endpoint**: `GET /api/allocation-reports`

**Purpose**: Retrieve available allocation reports for dropdown selection

**Query Parameters**: None

**Success Response** (200):
```json
{
    "success": true,
    "data": [
        {"value": "2025-04", "display": "April 2025"},
        {"value": "2025-03", "display": "March 2025"}
    ],
    "total": 6
}
```

**Error Response** (500):
```json
{
    "success": false,
    "error": "Failed to retrieve allocation reports"
}
```

---

## 2. Get Bench Allocation Preview

**Endpoint**: `POST /api/bench-allocation/preview`

**Purpose**: Calculate bench allocation changes (modified records only)

**Request Body**:
```json
{
    "month": "April",
    "year": 2025
}
```

**Success Response** (200):
```json
{
    "success": true,
    "months": {
        "month1": "Jun-25",
        "month2": "Jul-25",
        "month3": "Aug-25",
        "month4": "Sep-25",
        "month5": "Oct-25",
        "month6": "Nov-25"
    },

    "month": "April",
    "year": 2025,
    "modified_records": [
        {
            "main_lob": "Amisys Medicaid DOMESTIC",
            "state": "LA",
            "case_type": "Claims Processing",
            "case_id": "CL-001",
            "target_cph": 50,
            "target_cph_change": 5,
            "Jun-25": {
                "forecast": 12500,
                "fte_req": 25.5,
                "fte_avail": 28.0,
                "capacity": 1400,
                "fte_req_change": 0,
                "fte_avail_change": 3,
                "capacity_change": 150
            },
            "Jul-25": {
                "forecast": 13000,
                "fte_req": 26.0,
                "fte_avail": 28.0,
                "capacity": 1400,
                "fte_req_change": 0,
                "fte_avail_change": 0,
                "capacity_change": 0
            },
            "Aug-25": {
                "forecast": 13500,
                "fte_req": 27.0,
                "fte_avail": 30.0,
                "capacity": 1500,
                "fte_req_change": 2,
                "fte_avail_change": 3,
                "capacity_change": 100
            },
            "Sep-25": {
                "forecast": 14000,
                "fte_req": 28.0,
                "fte_avail": 30.0,
                "capacity": 1500,
                "fte_req_change": 0,
                "fte_avail_change": 0,
                "capacity_change": 0
            },
            "Oct-25": {
                "forecast": 14500,
                "fte_req": 29.0,
                "fte_avail": 32.0,
                "capacity": 1600,
                "fte_req_change": 1,
                "fte_avail_change": 2,
                "capacity_change": 100
            },
            "Nov-25": {
                "forecast": 15000,
                "fte_req": 30.0,
                "fte_avail": 32.0,
                "capacity": 1600,
                "fte_req_change": 0,
                "fte_avail_change": 0,
                "capacity_change": 0
            },
            "modified_fields": ["target_cph", "Jun-25.fte_avail", "Jun-25.capacity", "Aug-25.fte_req", "Aug-25.fte_avail", "Aug-25.capacity", "Oct-25.fte_req", "Oct-25.fte_avail", "Oct-25.capacity"]
        }
    ],
    "total_modified": 15,
    "summary": {
        "total_fte_change": 45.5,
        "total_capacity_change": 2250
    },
    "message": null
}
```

**Error Response** (400/500):
```json
{
    "success": false,
    "months": null,
    "modified_records": [],
    "total_modified": 0,
    "summary": null,
    "message": "No bench capacity available for allocation"
}
```

**Notes**:
- Returns `months` object mapping month indices (month1-month6) to actual month labels (Jun-25, Jul-25, etc.)
- Only returns records with changes in `modified_records`
- Each record includes month data directly (not nested) for all 6 months
- Each month object includes `*_change` fields showing deltas
- `modified_fields` array uses DOT notation (e.g., "Jun-25.fte_avail", "target_cph")
- Field names: `forecast`, `fte_req`, `fte_avail`, `capacity` (not cf, fte_required, fte_available)

---

## 3. Update Bench Allocation

**Endpoint**: `POST /api/bench-allocation/update`

**Purpose**: Save bench allocation changes and create history log entry

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
            "main_lob": "Amisys Medicaid DOMESTIC",
            "state": "LA",
            "case_type": "Claims Processing",
            "case_id": "CL-001",
            "target_cph": 50,
            "target_cph_change": 5,
            "Jun-25": {
                "forecast": 12500,
                "fte_req": 25.5,
                "fte_avail": 28.0,
                "capacity": 1400,
                "fte_req_change": 0,
                "fte_avail_change": 3,
                "capacity_change": 150
            },
            "Jul-25": {
                "forecast": 13000,
                "fte_req": 26.0,
                "fte_avail": 28.0,
                "capacity": 1400,
                "fte_req_change": 0,
                "fte_avail_change": 0,
                "capacity_change": 0
            },
            "Aug-25": {
                "forecast": 13500,
                "fte_req": 27.0,
                "fte_avail": 30.0,
                "capacity": 1500,
                "fte_req_change": 2,
                "fte_avail_change": 3,
                "capacity_change": 100
            },
            "Sep-25": {
                "forecast": 14000,
                "fte_req": 28.0,
                "fte_avail": 30.0,
                "capacity": 1500,
                "fte_req_change": 0,
                "fte_avail_change": 0,
                "capacity_change": 0
            },
            "Oct-25": {
                "forecast": 14500,
                "fte_req": 29.0,
                "fte_avail": 32.0,
                "capacity": 1600,
                "fte_req_change": 1,
                "fte_avail_change": 2,
                "capacity_change": 100
            },
            "Nov-25": {
                "forecast": 15000,
                "fte_req": 30.0,
                "fte_avail": 32.0,
                "capacity": 1600,
                "fte_req_change": 0,
                "fte_avail_change": 0,
                "capacity_change": 0
            },
            "modified_fields": ["target_cph", "Jun-25.fte_avail", "Jun-25.capacity", "Aug-25.fte_req", "Aug-25.fte_avail", "Aug-25.capacity", "Oct-25.fte_req", "Oct-25.fte_avail", "Oct-25.capacity"]
        }
    ],
    "user_notes": "Allocated excess bench capacity for Q2"
}
```

**Success Response** (200):
```json
{
    "success": true,
    "message": "Allocation updated successfully",
    "records_updated": 15
}
```

**Error Response** (400/500):
```json
{
    "success": false,
    "message": "Failed to update allocation: validation error",
    "records_updated": 0
}
```

**Notes**:
- **IMPORTANT**: Send the FULL record structure from the preview response (Section 2)
- `months` dictionary is **REQUIRED** - must be the same mapping received from preview response. Backend uses this to correctly process month data keys in records. Structure: `{"month1": "Jun-25", "month2": "Jul-25", ...}`
- Each record must include ALL 6 months (Jun-25 through Nov-25) with complete month data
- `modified_fields` array is **REQUIRED** - lists which fields changed using DOT notation (e.g., "Jun-25.fte_avail", "target_cph")
- Include `target_cph` and `target_cph_change` if CPH was modified
- Month data must include ALL fields: `forecast`, `fte_req`, `fte_avail`, `capacity`, plus corresponding `*_change` fields
- `*_change` fields show deltas from original values for audit trail and history tracking
- Frontend should send the exact structure received from the preview endpoint - DO NOT manually construct
- Creates corresponding history log entry automatically with full change details
- Should be transactional (all or nothing)
- Validator will reject requests missing `months`, `modified_fields`, or required identifier fields (`main_lob`, `state`, `case_type`, `case_id`)

**Field Reference**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `main_lob` | string | Yes | Line of business identifier |
| `state` | string | Yes | State code |
| `case_type` | string | Yes | Case type (e.g., "Claims Processing") |
| `case_id` | string | Yes | Unique case identifier |
| `months` | object | Yes | Month index mapping (month1-month6) to labels. Must match preview response. Required for backend processing. |
| `modified_fields` | array | Yes | DOT notation list of changed fields |
| `target_cph` | number | Conditional | Include if CPH changed |
| `target_cph_change` | number | Conditional | Delta from original CPH |
| `{Month}.forecast` | number | Yes | Forecast volume (read-only context) |
| `{Month}.fte_req` | number | Yes | Required FTE (calculated) |
| `{Month}.fte_avail` | number | Yes | Available FTE (modifiable) |
| `{Month}.capacity` | number | Yes | Capacity (modifiable) |
| `{Month}.fte_req_change` | number | Yes | Delta in FTE required |
| `{Month}.fte_avail_change` | number | Yes | Delta in FTE available |
| `{Month}.capacity_change` | number | Yes | Delta in capacity |

**Why Full Structure?**
- Validator requires `modified_fields` to identify changes
- Backend needs complete context for audit trail
- History log stores before/after comparison using `*_change` fields
- Ensures data consistency between preview and update operations

---

## 4. Change Types Constants

**IMPORTANT**: These change type values MUST be maintained as constants in the FastAPI backend to ensure consistency across frontend and backend.

**Standard Change Types**:

| Change Type | Description | Usage |
|-------------|-------------|-------|
| `Bench Allocation` | Bench capacity allocation changes | Used when allocating bench FTEs to cases |
| `CPH Update` | Target CPH (Claims Per Hour) updates | Used when modifying target CPH values |
| `Manual Update` | Manual adjustments by user | Ad-hoc manual modifications to any field |
| `Forecast Update` | Forecast volume changes after allocation through file uploads | Modifications to forecast values or creation of new data |

**Backend Implementation**:
```python
# FastAPI backend should define these as constants
CHANGE_TYPES = [
    "Bench Allocation",
    "CPH Update",
    "Manual Update",
    "Forecast Update"
]
```

**Notes**:
- Change type values are case-sensitive
- Must match exactly between frontend and backend
- Used for filtering in history log queries
- Used for categorizing changes in audit trail
- Frontend displays these in change type filter dropdown

---

## 5. Get History Log

**Endpoint**: `GET /api/history-log`

**Purpose**: Retrieve allocation history with pagination and filtering by change type

**Query Parameters**:
- `month` (optional): Filter by month name (e.g., "April")
- `year` (optional): Filter by year (e.g., 2025)
- `change_types` (optional): Array of change types to filter by (e.g., ["Bench Allocation", "CPH Update"])
- `page` (optional, default=1): Page number
- `limit` (optional, default=25): Records per page

**Success Response** (200):
```json
{
    "success": true,
    "data": [
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "change_type": "Bench Allocation",
            "month": "April",
            "year": 2025,
            "timestamp": "2025-04-15T14:30:00",
            "user": "john.doe",
            "description": "Allocated excess bench capacity for Q2",
            "records_modified": 15,
            "summary_data": {
                "report_month": "April",
                "report_year": 2025,
                "months": ["Jun-25", "Jul-25", "Aug-25", "Sep-25", "Oct-25", "Nov-25"],
                "totals": {
                    "Jun-25": {
                        "total_forecast": {"old": 125000, "new": 125000},
                        "total_fte_required": {"old": 250, "new": 255},
                        "total_fte_available": {"old": 275, "new": 285},
                        "total_capacity": {"old": 13750, "new": 14250}
                    },
                    "Jul-25": {
                        "total_forecast": {"old": 130000, "new": 130000},
                        "total_fte_required": {"old": 260, "new": 265},
                        "total_fte_available": {"old": 285, "new": 295},
                        "total_capacity": {"old": 14250, "new": 14750}
                    },
                    "Aug-25": {
                        "total_forecast": {"old": 135000, "new": 135000},
                        "total_fte_required": {"old": 270, "new": 275},
                        "total_fte_available": {"old": 295, "new": 305},
                        "total_capacity": {"old": 14750, "new": 15250}
                    }
                }
            }
        }
    ],
    "pagination": {
        "total": 127,
        "page": 1,
        "limit": 25,
        "has_more": true
    }
}
```

**Error Response** (500):
```json
{
    "success": false,
    "data": [],
    "pagination": null,
    "error": "Failed to retrieve history log"
}
```

**Usage Examples**:
```
GET /api/history-log?page=1&limit=25
GET /api/history-log?month=April&year=2025
GET /api/history-log?change_types=Bench%20Allocation&change_types=CPH%20Update&page=1
```

**Notes**:
- `change_types` parameter accepts multiple values (array) to filter by specific change types
- See Section 4 (Change Types Constants) for complete list of valid change types
- When multiple `change_types` filters are applied, they work together (OR logic - match any)
- When `month`, `year`, and `change_types` are combined, they use AND logic
- `summary_data` provides aggregated totals by month for frontend display
- Backend stores detailed field-level changes internally for audit trail
- All change types must match the constants defined in Section 4

**Summary Data Structure**:
- `months`: Array of month labels covered by the report
- `totals`: Object keyed by month label, containing old/new aggregate values for:
  - `total_forecast`: Total forecast volume
  - `total_fte_required`: Total required FTE
  - `total_fte_available`: Total available FTE
  - `total_capacity`: Total capacity

---

## 6. Download History Excel

**Endpoint**: `GET /api/history-log/{history_log_id}/download`

**Purpose**: Download Excel file for specific history log entry

**Path Parameters**:
- `history_log_id` (required): UUID of history log entry

**Success Response** (200):
- **Content-Type**: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **Body**: Binary Excel file stream
- **Suggested filename**: `bench_allocation_history_{history_log_id}.xlsx`

**Error Response** (404):
```json
{
    "detail": "History log entry not found"
}
```

**Error Response** (500):
```json
{
    "detail": "Failed to generate Excel file"
}
```

**Notes**:
- Should include all change details for audit purposes
- Excel should contain before/after values for transparency

---

## 7. Get Target CPH Data

**Endpoint**: `GET /api/edit-view/target-cph/data/`

**Purpose**: Retrieve Target CPH (Claims Per Hour) data for all LOB/CaseType combinations

**Query Parameters**:
- `month` (required): Month name (e.g., "April")
- `year` (required): Year (e.g., 2025)

**Success Response** (200):
```json
{
    "success": true,
    "data": [
        {
            "id": "cph_1",
            "lob": "Amisys Medicaid DOMESTIC",
            "case_type": "Claims Processing",
            "target_cph": 45.0,
            "modified_target_cph": 45.0
        },
        {
            "id": "cph_2",
            "lob": "Facets Medicare OFFSHORE",
            "case_type": "Enrollment",
            "target_cph": 52.0,
            "modified_target_cph": 52.0
        }
    ],
    "total": 55,
    "timestamp": "2025-01-07T10:30:00"
}
```

**Error Response** (400):
```json
{
    "success": false,
    "error": "Invalid month name: InvalidMonth. Must be full month name (e.g., 'April')"
}
```

**Error Response** (500):
```json
{
    "success": false,
    "error": "Failed to retrieve CPH data"
}
```

**Notes**:
- Returns CPH records for all LOB/CaseType combinations
- `modified_target_cph` initially equals `target_cph` (user can modify in UI)
- Used to populate the CPH update table in frontend
- Pagination handled client-side (typical: 55 records total)
- Configuration: `TargetCPHConfig.RECORDS_PER_PAGE = 20`

**Field Reference**:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique CPH record identifier (e.g., "cph_1") |
| `lob` | string | Line of business (e.g., "Amisys Medicaid DOMESTIC") |
| `case_type` | string | Case type (e.g., "Claims Processing", "Enrollment") |
| `target_cph` | number | Current target CPH value (2 decimal places) |
| `modified_target_cph` | number | Modified CPH value (editable by user, 2 decimal places) |

---

## 8. Get Target CPH Preview (Forecast Impact)

**Endpoint**: `POST /api/edit-view/target-cph/preview/`

**Purpose**: Calculate forecast impact of CPH changes before committing (preview only modified records)

**Request Body**:
```json
{
    "month": "April",
    "year": 2025,
    "modified_records": [
        {
            "id": "cph_1",
            "lob": "Amisys Medicaid DOMESTIC",
            "case_type": "Claims Processing",
            "target_cph": 45.0,
            "modified_target_cph": 50.0
        },
        {
            "id": "cph_2",
            "lob": "Facets Medicare OFFSHORE",
            "case_type": "Enrollment",
            "target_cph": 52.0,
            "modified_target_cph": 55.0
        }
    ]
}
```

**Success Response** (200):
```json
{
    "success": true,
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
            "id": "uuid-string",
            "main_lob": "Amisys Medicaid DOMESTIC",
            "state": "MO",
            "case_type": "Claims Processing",
            "case_id": "CASE-123",
            "modified_fields": ["Jun-25.fte_req", "Jun-25.capacity"],
            "Jun-25": {
                "forecast": 12500,
                "fte_req": 10.5,
                "fte_req_change": 2.3,
                "fte_avail": 8.2,
                "fte_avail_change": 1.5,
                "capacity": 0.78,
                "capacity_change": 0.05
            },
            "Jul-25": {
                "forecast": 13000,
                "fte_req": 11.0,
                "fte_req_change": 2.5,
                "fte_avail": 8.5,
                "fte_avail_change": 1.2,
                "capacity": 0.80,
                "capacity_change": 0.03
            }
        }
    ],
    "total_modified": 15,
    "summary": {
        "total_fte_change": 45.5,
        "total_capacity_change": 2250
    },
    "message": "Preview shows forecast impact of 2 CPH changes"
}
```

**Error Response** (400):
```json
{
    "success": false,
    "error": "No actual CPH changes detected. All modified_target_cph values match target_cph."
}
```

**Error Response** (500):
```json
{
    "success": false,
    "error": "Failed to calculate CPH preview"
}
```

**Notes**:
- **IMPORTANT**: Uses SAME standardized format as bench allocation preview (Section 2)
- Returns `months` object mapping month indices (month1-month6) to actual month labels
- Only returns forecast records affected by CPH changes in `modified_records`
- Each affected forecast record includes month data directly (not nested) for all 6 months
- Each month object includes `*_change` fields showing deltas
- `modified_fields` array uses DOT notation (e.g., "Jun-25.fte_req", "Jul-25.capacity")
- Field names: `forecast`, `fte_req`, `fte_avail`, `capacity` (standardized format)
- **KEY DIFFERENCE from Bench Allocation**: CPH preview includes `case_id` but does NOT include `target_cph` or `target_cph_change` fields
- Validates that modified_target_cph differs from target_cph (filters unchanged records)
- Cache TTL: 5 minutes (configurable: `TargetCPHConfig.CPH_PREVIEW_TTL`)

**Request Validation**:
- `month` must be full month name (e.g., "April")
- `year` must be integer between 2020-2030
- `modified_records` must be non-empty list
- Each record must have: id, lob, case_type, target_cph, modified_target_cph
- CPH values must be between 0.0 and 10000.0 (configurable)
- Raises ValidationError if no actual changes (target_cph == modified_target_cph for all records)

**Field Reference for Modified Records**:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique forecast record identifier |
| `main_lob` | string | Line of business identifier |
| `state` | string | State code |
| `case_type` | string | Case type (e.g., "Claims Processing") |
| `case_id` | string | Case identifier (included for CPH preview) |
| `modified_fields` | array | DOT notation list of changed fields |
| `{Month}.forecast` | number | Forecast volume (read-only context) |
| `{Month}.fte_req` | number | Required FTE (calculated, impacted by CPH change) |
| `{Month}.fte_req_change` | number | Delta in FTE required |
| `{Month}.fte_avail` | number | Available FTE |
| `{Month}.fte_avail_change` | number | Delta in FTE available |
| `{Month}.capacity` | number | Capacity (impacted by CPH change) |
| `{Month}.capacity_change` | number | Delta in capacity |

---

## 9. Update Target CPH

**Endpoint**: `POST /api/edit-view/target-cph/update/`

**Purpose**: Save CPH changes and create history log entry

**Request Body**:
```json
{
    "month": "April",
    "year": 2025,
    "modified_records": [
        {
            "id": "cph_1",
            "lob": "Amisys Medicaid DOMESTIC",
            "case_type": "Claims Processing",
            "target_cph": 45.0,
            "modified_target_cph": 50.0
        },
        {
            "id": "cph_2",
            "lob": "Facets Medicare OFFSHORE",
            "case_type": "Enrollment",
            "target_cph": 52.0,
            "modified_target_cph": 55.0
        }
    ],
    "user_notes": "Updated CPH values for Q2 optimization"
}
```

**Success Response** (200):
```json
{
    "success": true,
    "message": "CPH updated successfully",
    "records_updated": 2,
    "cph_changes_applied": 2,
    "forecast_rows_affected": 15,
    "timestamp": "2025-01-07T10:30:00"
}
```

**Error Response** (400):
```json
{
    "success": false,
    "message": "Validation error: CPH value cannot exceed 10000.0, got 15000.0"
}
```

**Error Response** (500):
```json
{
    "success": false,
    "message": "Failed to update CPH"
}
```

**Notes**:
- Send the same `modified_records` array from the GET CPH data endpoint (with user modifications)
- **DO NOT** send the preview response records - use the original CPH records structure
- Only records where `target_cph != modified_target_cph` are processed
- Creates corresponding history log entry automatically with change type "CPH Update"
- Should be transactional (all or nothing)
- Validator filters out unchanged records before processing
- No cache (write operation)

**Field Reference**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `month` | string | Yes | Month name (e.g., "April") |
| `year` | number | Yes | Year (e.g., 2025) |
| `modified_records` | array | Yes | Array of CPH records with changes |
| `user_notes` | string | No | User-provided description (max 500 chars) |

**Modified Records Structure**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | CPH record identifier |
| `lob` | string | Yes | Line of business |
| `case_type` | string | Yes | Case type |
| `target_cph` | number | Yes | Original CPH value |
| `modified_target_cph` | number | Yes | New CPH value (must differ from target_cph) |

**Validation Rules**:
- `month`: Must be full month name (January-December)
- `year`: Must be integer between 2020-2030
- `modified_records`: Must be non-empty array
- CPH values: Must be between 0.0 and 10000.0 (configurable: `TargetCPHConfig.MIN_CPH_VALUE`, `MAX_CPH_VALUE`)
- CPH precision: Rounded to 2 decimal places (configurable: `TargetCPHConfig.CPH_DECIMAL_PLACES`)
- `user_notes`: Optional, max 500 characters (configurable: `TargetCPHConfig.MAX_USER_NOTES_LENGTH`)
- At least one record must have actual change (target_cph != modified_target_cph)

**Response Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Operation success status |
| `message` | string | Success/error message |
| `records_updated` | number | Number of CPH records updated |
| `cph_changes_applied` | number | Number of CPH changes applied |
| `forecast_rows_affected` | number | Number of forecast rows impacted by CPH changes |
| `timestamp` | string | Update timestamp (ISO format) |

---

## Configuration Notes

From `EditViewConfig` in config.py:
- **Preview Cache TTL**: 300 seconds (5 minutes)
- **History Cache TTL**: 180 seconds (3 minutes)
- **Preview Timeout**: 60 seconds
- **Update Timeout**: 120 seconds
- **Download Timeout**: 180 seconds

From `TargetCPHConfig` in config.py:
- **CPH Data Cache TTL**: 900 seconds (15 minutes)
- **CPH Preview Cache TTL**: 300 seconds (5 minutes)
- **Records Per Page**: 20 records
- **Min CPH Value**: 0.0
- **Max CPH Value**: 10000.0
- **CPH Decimal Places**: 2
- **Max User Notes Length**: 500 characters

---

## Error Handling

All endpoints should:
1. Return proper HTTP status codes (200, 400, 404, 500)
2. Include `success` boolean in JSON responses
3. Provide descriptive error messages in `error` or `message` fields
4. Log errors server-side for debugging
