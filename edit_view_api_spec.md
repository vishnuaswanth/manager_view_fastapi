# Edit View API Specification

## Overview
APIs for bench allocation, Target CPH management, and Forecast Reallocation with preview/approval workflow and history tracking.

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
            "target_cph_change": 0,
            "modified_fields": ["target_cph", "Jun-25.forecast", "Jun-25.fte_req", "Jun-25.fte_avail", "Jun-25.capacity", "Aug-25.forecast", "Aug-25.fte_req", "Aug-25.fte_avail", "Aug-25.capacity", "Oct-25.forecast", "Oct-25.fte_req", "Oct-25.fte_avail", "Oct-25.capacity"],
            "months": {
                "Jun-25": {
                    "forecast": 12500,
                    "fte_req": 25,
                    "fte_avail": 28,
                    "capacity": 1400,
                    "forecast_change": 0,
                    "fte_req_change": 0,
                    "fte_avail_change": 3,
                    "capacity_change": 150
                },
                "Jul-25": {
                    "forecast": 13000,
                    "fte_req": 26,
                    "fte_avail": 28,
                    "capacity": 1400,
                    "forecast_change": 0,
                    "fte_req_change": 0,
                    "fte_avail_change": 0,
                    "capacity_change": 0
                },
                "Aug-25": {
                    "forecast": 13500,
                    "fte_req": 27,
                    "fte_avail": 30,
                    "capacity": 1500,
                    "forecast_change": 0,
                    "fte_req_change": 0,
                    "fte_avail_change": 3,
                    "capacity_change": 100
                },
                "Sep-25": {
                    "forecast": 14000,
                    "fte_req": 28,
                    "fte_avail": 30,
                    "capacity": 1500,
                    "forecast_change": 0,
                    "fte_req_change": 0,
                    "fte_avail_change": 0,
                    "capacity_change": 0
                },
                "Oct-25": {
                    "forecast": 14500,
                    "fte_req": 29,
                    "fte_avail": 32,
                    "capacity": 1600,
                    "forecast_change": 0,
                    "fte_req_change": 0,
                    "fte_avail_change": 2,
                    "capacity_change": 100
                },
                "Nov-25": {
                    "forecast": 15000,
                    "fte_req": 30,
                    "fte_avail": 32,
                    "capacity": 1600,
                    "forecast_change": 0,
                    "fte_req_change": 0,
                    "fte_avail_change": 0,
                    "capacity_change": 0
                }
            }
        }
    ],
    "total_modified": 15,
    "summary": {
        "total_fte_change": 45,
        "total_capacity_change": 2250
    },
    "message": null
}
```

**Success Response with No Changes** (200):
```json
{
    "success": true,
    "total_modified": 0,
    "modified_records": [],
    "info_message": "No bench capacity available for allocation"
}
```

**Error Response** (400/500):
```json
{
    "success": false,
    "error": "Bench allocation has already been completed for April 2025",
    "completed_at": "2025-04-15T14:30:00",
    "execution_id": "550e8400-e29b-41d4-a716-446655440000",
    "recommendation": "To modify bench allocation, you must re-run the primary allocation first."
}
```

**Notes**:
- Returns `months` object mapping month indices (month1-month6) to actual month labels (Jun-25, Jul-25, etc.)
- Only returns records with changes in `modified_records`
- Each record includes a `months` object containing month-specific data for all 6 months
- Each month object includes both current values AND `*_change` fields showing deltas
- All numeric fields are integers (not decimals)
- Change fields: `forecast_change`, `fte_req_change`, `fte_avail_change`, `capacity_change`
- `modified_fields` array uses DOT notation (e.g., "Jun-25.fte_avail", "target_cph")
- Field names: `forecast`, `fte_req`, `fte_avail`, `capacity` (standardized format)
- **Option 1 Implementation**: When ANY field changes for a month, ALL 4 fields for that month are included in `modified_fields` (e.g., if only `fte_avail` changes for Jun-25, the array includes `Jun-25.forecast`, `Jun-25.fte_req`, `Jun-25.fte_avail`, and `Jun-25.capacity`)
- This provides a complete snapshot of the record state at the time of modification for audit purposes
- For bench allocation: `target_cph_change` is typically 0 (CPH doesn't change during bench allocation)

**Validation Checks**:
1. **Allocation Validity**: Validates that a valid allocation exists for the selected month/year
2. **Bench Allocation Status**: Checks if bench allocation has already been completed for this execution
   - If already completed, returns 400 error with `completed_at` timestamp and `recommendation`
   - To re-run bench allocation, user must first re-run the primary allocation

**Response Variants**:
- **Success with changes**: Returns `modified_records` array with allocation changes
- **Success without changes**: Returns `info_message` explaining why no changes (e.g., no bench capacity)
- **Error - Already completed**: Returns 400 with `completed_at`, `execution_id`, and `recommendation`
- **Error - No valid allocation**: Returns 400 with validation error details

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
            "target_cph_change": 0,
            "modified_fields": ["target_cph", "Jun-25.forecast", "Jun-25.fte_req", "Jun-25.fte_avail", "Jun-25.capacity", "Aug-25.forecast", "Aug-25.fte_req", "Aug-25.fte_avail", "Aug-25.capacity", "Oct-25.forecast", "Oct-25.fte_req", "Oct-25.fte_avail", "Oct-25.capacity"],
            "months": {
                "Jun-25": {
                    "forecast": 12500,
                    "fte_req": 25,
                    "fte_avail": 28,
                    "capacity": 1400,
                    "forecast_change": 0,
                    "fte_req_change": 0,
                    "fte_avail_change": 3,
                    "capacity_change": 150
                },
                "Jul-25": {
                    "forecast": 13000,
                    "fte_req": 26,
                    "fte_avail": 28,
                    "capacity": 1400,
                    "forecast_change": 0,
                    "fte_req_change": 0,
                    "fte_avail_change": 0,
                    "capacity_change": 0
                },
                "Aug-25": {
                    "forecast": 13500,
                    "fte_req": 27,
                    "fte_avail": 30,
                    "capacity": 1500,
                    "forecast_change": 0,
                    "fte_req_change": 0,
                    "fte_avail_change": 3,
                    "capacity_change": 100
                },
                "Sep-25": {
                    "forecast": 14000,
                    "fte_req": 28,
                    "fte_avail": 30,
                    "capacity": 1500,
                    "forecast_change": 0,
                    "fte_req_change": 0,
                    "fte_avail_change": 0,
                    "capacity_change": 0
                },
                "Oct-25": {
                    "forecast": 14500,
                    "fte_req": 29,
                    "fte_avail": 32,
                    "capacity": 1600,
                    "forecast_change": 0,
                    "fte_req_change": 0,
                    "fte_avail_change": 2,
                    "capacity_change": 100
                },
                "Nov-25": {
                    "forecast": 15000,
                    "fte_req": 30,
                    "fte_avail": 32,
                    "capacity": 1600,
                    "forecast_change": 0,
                    "fte_req_change": 0,
                    "fte_avail_change": 0,
                    "capacity_change": 0
                }
            }
        }
    ],
    "user_notes": "Allocated excess bench capacity for Q2"
}
```

**Success Response** (200):
```json
{
    "success": true,
    "message": "Bench allocation updated successfully",
    "records_updated": 15,
    "history_log_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Error Response** (400/500):
```json
{
    "success": false,
    "error": "Failed to update allocation: validation error"
}
```

**Response Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Operation success status |
| `message` | string | Success/error message |
| `records_updated` | number | Number of forecast records updated |
| `history_log_id` | string | UUID of created history log entry (for audit trail) |

**Notes**:
- **IMPORTANT**: Send the FULL record structure from the preview response (Section 2)
- Top-level `months` dictionary is **REQUIRED** - must be the same mapping received from preview response. Backend uses this to correctly process month data keys in records. Structure: `{"month1": "Jun-25", "month2": "Jul-25", ...}`
- Each record must have a `months` object containing ALL 6 months (Jun-25 through Nov-25) with complete month data
- All numeric fields are integers (not decimals)
- Month data must include ALL fields: `forecast`, `fte_req`, `fte_avail`, `capacity`, plus corresponding `*_change` fields (`forecast_change`, `fte_req_change`, `fte_avail_change`, `capacity_change`)
- `modified_fields` array is **REQUIRED** - lists which fields changed using DOT notation (e.g., "Jun-25.fte_avail", "target_cph")
- **Option 1 Implementation**: When ANY field changes for a month, ALL 4 fields for that month (forecast, fte_req, fte_avail, capacity) MUST be included in `modified_fields`. This provides a complete snapshot for audit purposes.
- Include `target_cph` in record (typically no change for bench allocation, so `target_cph_change` is 0)
- `*_change` fields show deltas from original values for audit trail and history tracking
- Frontend should send the exact structure received from the preview endpoint - DO NOT manually construct
- Creates corresponding history log entry automatically with full change details
- Should be transactional (all or nothing)
- Validator will reject requests missing `months`, `modified_fields`, or required identifier fields (`main_lob`, `state`, `case_type`, `case_id`)
- In Excel exports, missing field values (when field has no data) are displayed as `0` for clarity

**Field Reference**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `main_lob` | string | Yes | Line of business identifier |
| `state` | string | Yes | State code |
| `case_type` | string | Yes | Case type (e.g., "Claims Processing") |
| `case_id` | string | Yes | Unique case identifier |
| `target_cph` | integer | Yes | Target cases per hour (typically unchanged for bench allocation) |
| `target_cph_change` | integer | Yes | Delta from original CPH (typically 0 for bench allocation) |
| `modified_fields` | array | Yes | DOT notation list of ALL fields for months with changes. With Option 1, includes all 4 fields for each month that has any change (e.g., ["Jun-25.forecast", "Jun-25.fte_req", "Jun-25.fte_avail", "Jun-25.capacity"]) |
| `months` | object | Yes | NESTED object containing month-specific data for all 6 months. Keys are month labels (e.g., "Jun-25"). Each month object contains: forecast, fte_req, fte_avail, capacity, forecast_change, fte_req_change, fte_avail_change, capacity_change (all integers) |

**Top-level Request Fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `months` (top-level) | object | Yes | Month index mapping (month1-month6) to labels. Must match preview response. Required for backend processing. Structure: `{"month1": "Jun-25", "month2": "Jul-25", ...}` |
| `user_notes` | string | No | User-provided notes for the history log (max 500 chars) |
| `{Month}.fte_req_change` | number | Yes | Delta in FTE required (may be 0 if unchanged) |
| `{Month}.fte_avail_change` | number | Yes | Delta in FTE available (may be 0 if unchanged) |
| `{Month}.capacity_change` | number | Yes | Delta in capacity (may be 0 if unchanged) |
| `{Month}.forecast_change` | number | No | Delta in forecast (typically 0 for bench allocation, not included in response but implied 0) |

**Why Full Structure?**
- Validator requires `modified_fields` to identify changes
- Backend needs complete context for audit trail
- History log stores before/after comparison using `*_change` fields
- Ensures data consistency between preview and update operations
- **Option 1**: Provides complete record snapshot for each modified month, even if some fields didn't change
- Excel exports fill missing field values with `0` for clarity in audit reports

---

## 4. Change Types Constants

**IMPORTANT**: These change type values MUST be maintained as constants in the FastAPI backend to ensure consistency across frontend and backend.

**Standard Change Types**:

| Change Type | Description | Usage |
|-------------|-------------|-------|
| `Bench Allocation` | Bench capacity allocation changes | Used when allocating bench FTEs to cases |
| `CPH Update` | Target CPH (Claims Per Hour) updates | Used when modifying target CPH values |
| `Forecast Reallocation` | Manual edits to Target CPH and FTE Available | Used when manually reallocating forecast resources |
| `Manual Update` | Manual adjustments by user | Ad-hoc manual modifications to any field |
| `Forecast Update` | Forecast volume changes after allocation through file uploads | Modifications to forecast values or creation of new data |

**Backend Implementation**:
```python
# FastAPI backend should define these as constants
CHANGE_TYPES = [
    "Bench Allocation",
    "CPH Update",
    "Forecast Reallocation",
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
            "history_log_id": "550e8400-e29b-41d4-a716-446655440000",
            "change_type": "Bench Allocation",
            "month": "April",
            "year": 2025,
            "created_at": "2025-04-15T14:30:00",
            "user": "system",
            "user_notes": "Allocated excess bench capacity for Q2",
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
    "total": 127,
    "page": 1,
    "limit": 25,
    "has_more": true
}
```

**Error Response** (500):
```json
{
    "success": false,
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
- Response uses flat pagination fields (`total`, `page`, `limit`, `has_more`) not nested `pagination` object

**Response Field Reference**:

| Field | Type | Description |
|-------|------|-------------|
| `history_log_id` | string | UUID identifier for the history log entry |
| `change_type` | string | Type of change (see Section 4) |
| `month` | string | Report month name |
| `year` | number | Report year |
| `created_at` | string | ISO timestamp of when the change was recorded |
| `user` | string | User who made the change (default: "system") |
| `user_notes` | string | User-provided notes/description |
| `records_modified` | number | Count of records modified in this change |
| `summary_data` | object | Aggregated before/after totals by month |

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

**Purpose**: Download Excel file for specific history log entry with multi-level headers

**Path Parameters**:
- `history_log_id` (required): UUID of history log entry

**Success Response** (200):
- **Content-Type**: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **Body**: Binary Excel file stream
- **Suggested filename**: `History_Log_{history_log_id}_{timestamp}.xlsx`

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

**Excel File Structure**:

The generated Excel file contains two sheets:

### Changes Sheet
Multi-level headers with merged cells showing hierarchical structure:

```
Row 1: [Main LOB] [State] [Case Type] [Case ID] [Jun-25 ──────────────────] [Jul-25 ──────────────────]
       [merged]   [merged] [merged]    [merged]   [4 columns merged]        [4 columns merged]

Row 2: [merged]   [merged] [merged]    [merged]   [Client] [FTE]  [FTE]      [Capacity]
                                                    [Forecast][Req] [Avail]

Row 3+: Data rows with before/after values...
```

**Header Styling**:
- **Row 1** (Month headers + static columns): Dark blue background (#366092), white bold text, centered
- **Row 2** (Field headers): Light blue background (#5B9BD5), white bold text, centered
- **Data rows**: White background, bordered cells

**Column Structure**:
- **Static columns**: Main LOB, State, Case Type, Case ID, Target CPH (if present)
- **Month columns**: For each month (Jun-25, Jul-25, etc.), 4 sub-columns:
  - Client Forecast
  - FTE Required
  - FTE Available
  - Capacity

**Data Format**:
- Changed values show as: `new_value (old_value)` (e.g., `25 (20)` means changed from 20 to 25)
- Unchanged values show as: `value` (e.g., `1000`)
- Missing fields show as: `0` (when field has no data)

**Example Data Row**:
```
| Amisys Medicaid | TX | Claims | CL-001 | 1000 | 20 | 25 (20) | 1125 (1000) | 2000 | 40 | 40 | 2000 |
```

### Summary Sheet
Contains metadata and aggregated totals:
- History Log ID
- Change Type (e.g., "Bench Allocation", "CPH Update")
- Report Month and Year
- Timestamp
- User
- Description
- Records Modified
- Month-by-month totals (if available):
  - Total FTE Available (Old/New)
  - Total Forecast (Old/New)
  - Total Capacity (Old/New)

**Notes**:
- **Multi-level headers**: Uses merged cells for visual grouping by month
- **Missing field handling**: Fields without data are filled with `0` for clarity
- **Before/after tracking**: Changed values display both new and old values
- **Complete audit trail**: Includes all change details for compliance
- **Option 1 implementation**: Tracks ALL 4 fields (forecast, fte_req, fte_avail, capacity) when ANY field changes in a record

**Known Behavior - Excel for Mac**:

When opening the file in Excel for Mac, you may see this alert:
```
"We found a problem with some content in '[filename].xlsx'.
Do you want us to try to recover as much as we can?"
```

**This is expected behavior and NOT a file corruption issue.** It occurs due to a compatibility difference between openpyxl's merged cell handling and Excel for Mac's strict XML validation. Simply click "Yes" to open the file - all data will be intact and correctly formatted.

- ✓ File is functionally correct
- ✓ All data is preserved
- ✓ All formatting is intact
- ✓ Merged cells work correctly
- Excel for Windows typically opens the file without this dialog

**Field Name Mapping**:

| API Field Name | Excel Display Name |
|----------------|-------------------|
| `forecast` | Client Forecast |
| `fte_req` | FTE Required |
| `fte_avail` | FTE Available |
| `capacity` | Capacity |
| `target_cph` | Target CPH |

**Technical Details**:
- Engine: openpyxl (Python Excel library)
- Format: XLSX (Excel 2007+)
- Encoding: UTF-8
- File size: Varies based on record count (typically 10-50 KB)
- Browser download: Handled via StreamingResponse with proper MIME type

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
    "total": 55
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
    "month": "April",
    "year": 2025,
    "modified_records": [
        {
            "main_lob": "Amisys Medicaid DOMESTIC",
            "state": "MO",
            "case_type": "Claims Processing",
            "case_id": "CASE-123",
            "target_cph": 50.0,
            "target_cph_change": 5.0,
            "modified_fields": ["target_cph", "Jun-25.forecast", "Jun-25.fte_req", "Jun-25.fte_avail", "Jun-25.capacity", "Jul-25.forecast", "Jul-25.fte_req", "Jul-25.fte_avail", "Jul-25.capacity"],
            "months": {
                "Jun-25": {
                    "forecast": 12500,
                    "fte_req": 10,
                    "fte_avail": 8,
                    "capacity": 400,
                    "forecast_change": 0,
                    "fte_req_change": 2,
                    "fte_avail_change": 0,
                    "capacity_change": 100
                },
                "Jul-25": {
                    "forecast": 13000,
                    "fte_req": 11,
                    "fte_avail": 8,
                    "capacity": 440,
                    "forecast_change": 0,
                    "fte_req_change": 3,
                    "fte_avail_change": 0,
                    "capacity_change": 120
                },
                "Aug-25": {
                    "forecast": 13500,
                    "fte_req": 12,
                    "fte_avail": 8,
                    "capacity": 480,
                    "forecast_change": 0,
                    "fte_req_change": 3,
                    "fte_avail_change": 0,
                    "capacity_change": 130
                },
                "Sep-25": {
                    "forecast": 14000,
                    "fte_req": 13,
                    "fte_avail": 8,
                    "capacity": 520,
                    "forecast_change": 0,
                    "fte_req_change": 3,
                    "fte_avail_change": 0,
                    "capacity_change": 140
                },
                "Oct-25": {
                    "forecast": 14500,
                    "fte_req": 14,
                    "fte_avail": 8,
                    "capacity": 560,
                    "forecast_change": 0,
                    "fte_req_change": 4,
                    "fte_avail_change": 0,
                    "capacity_change": 150
                },
                "Nov-25": {
                    "forecast": 15000,
                    "fte_req": 15,
                    "fte_avail": 8,
                    "capacity": 600,
                    "forecast_change": 0,
                    "fte_req_change": 4,
                    "fte_avail_change": 0,
                    "capacity_change": 160
                }
            }
        }
    ],
    "total_modified": 15,
    "summary": {
        "total_fte_change": 45,
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
- **Option 1 Implementation**: When ANY field changes for a month (FTE Required or Capacity due to CPH change), ALL 4 fields for that month are included in `modified_fields`
  - Example: If Jun-25 FTE Required changes, `modified_fields` includes: `["target_cph", "Jun-25.forecast", "Jun-25.fte_req", "Jun-25.fte_avail", "Jun-25.capacity"]`
  - Provides complete snapshot of all modified records for audit trail
- Returns top-level `months` object mapping month indices (month1-month6) to actual month labels
- Returns `month` and `year` in the response for context
- Only returns forecast records affected by CPH changes in `modified_records`
- Each affected forecast record has a `months` object containing month-specific data for ALL 6 months
- Each month object includes both current values AND `*_change` fields showing deltas
- All numeric fields are integers (not decimals) except `target_cph` and `target_cph_change` which are floats
- Change fields: `forecast_change`, `fte_req_change`, `fte_avail_change`, `capacity_change`
- `modified_fields` array uses DOT notation (e.g., "target_cph", "Jun-25.fte_req", "Jul-25.capacity")
- Field names: `forecast`, `fte_req`, `fte_avail`, `capacity` (standardized format)
- **IMPORTANT**: CPH preview includes `target_cph` and `target_cph_change` fields showing the new CPH value and the delta
- `target_cph` in the response shows the NEW (modified) CPH value, NOT the original
- `target_cph_change` shows the delta (modified_target_cph - target_cph)
- Validates that modified_target_cph differs from target_cph (filters unchanged records)
- Cache TTL: 5 minutes (configurable: `TargetCPHConfig.CPH_PREVIEW_TTL`)

**Request Validation**:
- `month` must be full month name (e.g., "April")
- `year` must be integer between 2020-2030
- `modified_records` must be non-empty list
- Each record must have: id, lob, case_type, target_cph, modified_target_cph
- CPH values must be between 0.0 and 200.0 (validated by Pydantic)
- Raises ValidationError if no actual changes (target_cph == modified_target_cph for all records)

**Field Reference for Modified Records in Response**:

| Field | Type | Description |
|-------|------|-------------|
| `main_lob` | string | Line of business identifier |
| `state` | string | State code |
| `case_type` | string | Case type (e.g., "Claims Processing") |
| `case_id` | string | Case identifier (Centene_Capacity_Plan_Call_Type_ID) |
| `target_cph` | float | NEW Target CPH value (after modification) |
| `target_cph_change` | float | Delta in Target CPH (modified - original) |
| `modified_fields` | array | DOT notation list of changed fields (Option 1: includes "target_cph" + all 4 fields for months with changes) |
| `months` | object | NESTED object containing month-specific data for ALL 6 months. Keys are month labels (e.g., "Jun-25"). Each month object contains: forecast (int), fte_req (int), fte_avail (int), capacity (int), forecast_change (int), fte_req_change (int), fte_avail_change (int), capacity_change (int) |

**CPH Preview Specific Notes**:
- For CPH changes, `fte_avail_change` is always 0 (CPH affects FTE Required and Capacity, not FTE Available)
- `fte_req_change` shows the delta in FTE Required due to CPH change
- `capacity_change` shows the delta in Capacity due to CPH change
- Response can be directly submitted to the CPH update endpoint after user approval

---

## 9. Update Target CPH

**Endpoint**: `POST /api/edit-view/target-cph/update/`

**Purpose**: Save CPH changes and create history log entry

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
            "state": "MO",
            "case_type": "Claims Processing",
            "case_id": "CASE-123",
            "target_cph": 50.0,
            "target_cph_change": 5.0,
            "modified_fields": ["target_cph", "Jun-25.forecast", "Jun-25.fte_req", "Jun-25.fte_avail", "Jun-25.capacity", "Jul-25.forecast", "Jul-25.fte_req", "Jul-25.fte_avail", "Jul-25.capacity"],
            "months": {
                "Jun-25": {
                    "forecast": 12500,
                    "fte_req": 10,
                    "fte_avail": 8,
                    "capacity": 400,
                    "forecast_change": 0,
                    "fte_req_change": 2,
                    "fte_avail_change": 0,
                    "capacity_change": 100
                },
                "Jul-25": {
                    "forecast": 13000,
                    "fte_req": 11,
                    "fte_avail": 8,
                    "capacity": 440,
                    "forecast_change": 0,
                    "fte_req_change": 3,
                    "fte_avail_change": 0,
                    "capacity_change": 120
                },
                "Aug-25": {
                    "forecast": 13500,
                    "fte_req": 12,
                    "fte_avail": 8,
                    "capacity": 480,
                    "forecast_change": 0,
                    "fte_req_change": 3,
                    "fte_avail_change": 0,
                    "capacity_change": 130
                },
                "Sep-25": {
                    "forecast": 14000,
                    "fte_req": 13,
                    "fte_avail": 8,
                    "capacity": 520,
                    "forecast_change": 0,
                    "fte_req_change": 3,
                    "fte_avail_change": 0,
                    "capacity_change": 140
                },
                "Oct-25": {
                    "forecast": 14500,
                    "fte_req": 14,
                    "fte_avail": 8,
                    "capacity": 560,
                    "forecast_change": 0,
                    "fte_req_change": 4,
                    "fte_avail_change": 0,
                    "capacity_change": 150
                },
                "Nov-25": {
                    "forecast": 15000,
                    "fte_req": 15,
                    "fte_avail": 8,
                    "capacity": 600,
                    "forecast_change": 0,
                    "fte_req_change": 4,
                    "fte_avail_change": 0,
                    "capacity_change": 160
                }
            }
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
    "cph_changes_applied": 2,
    "forecast_rows_affected": 15,
    "history_log_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Error Response** (400):
```json
{
    "success": false,
    "error": "Validation error: CPH value cannot exceed 200.0"
}
```

**Error Response** (500):
```json
{
    "success": false,
    "error": "Failed to update CPH"
}
```

**Notes**:
- **IMPORTANT**: Send the FULL record structure from the preview response (Section 8)
- Uses the SAME `ModifiedForecastRecord` format as bench allocation update (Section 3)
- Top-level `months` dictionary is **REQUIRED** - must be the same mapping received from preview response
- Frontend should send the exact structure received from the preview endpoint - DO NOT manually construct
- Each record must have a `months` object containing ALL 6 months with complete month data
- All numeric fields are integers except `target_cph` and `target_cph_change` which are floats
- Month data must include ALL fields: `forecast`, `fte_req`, `fte_avail`, `capacity`, plus corresponding `*_change` fields
- `modified_fields` array is **REQUIRED** - lists which fields changed using DOT notation
- **Option 1 Implementation**: When ANY field changes for a month, ALL 4 fields for that month MUST be included in `modified_fields`, plus "target_cph"
- `target_cph` in request shows the NEW (modified) CPH value
- `target_cph_change` shows the delta from original value
- Creates corresponding history log entry automatically with change type "CPH Update"
- Should be transactional (all or nothing)
- Validator will reject requests missing `months`, `modified_fields`, or required identifier fields
- No cache (write operation)

**Top-level Request Fields**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `month` | string | Yes | Month name (e.g., "April") |
| `year` | number | Yes | Year (e.g., 2025) |
| `months` (top-level) | object | Yes | Month index mapping (month1-month6) to labels. Must match preview response. Required for backend processing. Structure: `{"month1": "Jun-25", "month2": "Jul-25", ...}` |
| `modified_records` | array | Yes | Array of modified forecast records (ModifiedForecastRecord format from preview) |
| `user_notes` | string | No | User-provided description (max 1000 chars) |

**Modified Records Structure**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `main_lob` | string | Yes | Line of business identifier |
| `state` | string | Yes | State code (2-letter) or 'N/A' |
| `case_type` | string | Yes | Case type (e.g., "Claims Processing") |
| `case_id` | string | Yes | Unique case identifier |
| `target_cph` | float | Yes | NEW Target CPH value (after modification) |
| `target_cph_change` | float | Yes | Delta from original CPH |
| `modified_fields` | array | Yes | DOT notation list of ALL fields for months with changes. With Option 1, includes "target_cph" + all 4 fields for each month that has any change |
| `months` | object | Yes | NESTED object containing month-specific data for all 6 months. Keys are month labels (e.g., "Jun-25"). Each month object contains: forecast (int), fte_req (int), fte_avail (int), capacity (int), forecast_change (int), fte_req_change (int), fte_avail_change (int), capacity_change (int) |

**Validation Rules**:
- `month`: Must be full month name (January-December)
- `year`: Must be integer between 2020-2050
- `modified_records`: Must be non-empty array
- `months`: Must have exactly 6 entries (month1-month6)
- CPH values: Must be between 0.0 and 200.0 (validated by Pydantic)
- `modified_fields`: Must be non-empty array
- Each record's `months` object must contain all 6 month labels matching the top-level `months` mapping
- `user_notes`: Optional, max 1000 characters

**Response Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Operation success status |
| `message` | string | Success/error message |
| `cph_changes_applied` | number | Number of CPH changes applied |
| `forecast_rows_affected` | number | Number of forecast rows impacted by CPH changes |
| `history_log_id` | string | UUID of created history log entry |

**Why Full Structure?**
- Validator requires `modified_fields` to identify changes
- Backend needs complete context for audit trail
- History log stores before/after comparison using `*_change` fields
- Ensures data consistency between preview and update operations
- **Option 1**: Provides complete record snapshot for each modified month
- Preview is server-generated and trusted, so update accepts it directly

---

## 10. Get Forecast Reallocation Filters

> **DEPRECATED**: This endpoint is no longer used by the frontend UI. Filter options are now extracted client-side from the loaded data (Section 11). The endpoint remains available for backward compatibility but may be removed in a future version.

**Endpoint**: `GET /api/edit-view/forecast-reallocation/filters/`

**Purpose**: Retrieve available filter options (Main LOBs, States, Case Types) for the Forecast Reallocation feature

**Query Parameters**:
- `month` (required): Month name (e.g., "April")
- `year` (required): Year (e.g., 2025)

**Success Response** (200):
```json
{
    "success": true,
    "main_lobs": [
        "Medicaid",
        "Medicare",
        "Commercial",
        "Exchange",
        "Duals"
    ],
    "states": [
        "MO", "TX", "FL", "GA", "IL", "OH", "MI", "NC", "AZ", "NV",
        "WA", "OR", "CA", "NY", "PA"
    ],
    "case_types": [
        "Appeals",
        "Claims",
        "Adjustments",
        "Correspondence",
        "OMNI",
        "FTC",
        "Member Services",
        "Provider Services"
    ]
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
    "error": "Failed to retrieve reallocation filters"
}
```

**Notes**:
- **DEPRECATED**: Frontend now extracts filter options from loaded data (see Section 11)
- Returns distinct filter options available for the selected report month/year
- Previously used to populate multi-select dropdowns before data load

**Field Reference**:

| Field | Type | Description |
|-------|------|-------------|
| `main_lobs` | array | List of available Main LOB values |
| `states` | array | List of available state codes |
| `case_types` | array | List of available case type values |

---

## 11. Get Forecast Reallocation Data

**Endpoint**: `GET /api/edit-view/forecast-reallocation/data/`

**Purpose**: Retrieve editable forecast records for reallocation with 6-month data

**Query Parameters**:
- `month` (required): Month name (e.g., "April")
- `year` (required): Year (e.g., 2025)
- `main_lobs[]` (optional, typically not used): Array of Main LOB values to filter
- `case_types[]` (optional, typically not used): Array of Case Type values to filter
- `states[]` (optional, typically not used): Array of State codes to filter

**Success Response** (200):
```json
{
    "success": true,
    "months": {
        "month1": "Apr-25",
        "month2": "May-25",
        "month3": "Jun-25",
        "month4": "Jul-25",
        "month5": "Aug-25",
        "month6": "Sep-25"
    },
    "data": [
        {
            "case_id": "550e8400-e29b-41d4-a716-446655440000",
            "main_lob": "Medicaid",
            "state": "MO",
            "case_type": "Appeals",
            "target_cph": 100.0,
            "months": {
                "Apr-25": {
                    "forecast": 12500,
                    "fte_req": 125,
                    "fte_avail": 120,
                    "capacity": 12000
                },
                "May-25": {
                    "forecast": 13000,
                    "fte_req": 130,
                    "fte_avail": 125,
                    "capacity": 12500
                },
                "Jun-25": {
                    "forecast": 13500,
                    "fte_req": 135,
                    "fte_avail": 130,
                    "capacity": 13000
                },
                "Jul-25": {
                    "forecast": 14000,
                    "fte_req": 140,
                    "fte_avail": 135,
                    "capacity": 13500
                },
                "Aug-25": {
                    "forecast": 14500,
                    "fte_req": 145,
                    "fte_avail": 140,
                    "capacity": 14000
                },
                "Sep-25": {
                    "forecast": 15000,
                    "fte_req": 150,
                    "fte_avail": 145,
                    "capacity": 14500
                }
            }
        }
    ],
    "total": 150
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
    "error": "Failed to retrieve reallocation data"
}
```

**UI Workflow**:

The Forecast Reallocation tab follows a "load-then-filter" pattern (similar to Target CPH tab):

1. **Initial Selection Card**: User selects only the Report Month and clicks "Load Data"
2. **Data Load**: Frontend calls this endpoint WITHOUT filter parameters to load ALL records
3. **Filter Extraction**: Frontend extracts unique `main_lob`, `state`, and `case_type` values from loaded data
4. **Filter Dropdowns**: Filter dropdowns (inside the data container card) are populated from extracted values
5. **Client-Side Filtering**: User applies filters which filter the already-loaded records client-side
6. **Clear Filters**: A "Clear Filters" button resets all filters and shows all loaded records

```
┌─────────────────────────────────────────────────────────────┐
│ Data Selection Card                                          │
│ [Report Month ▼]                         [Load Data]         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Data Container Card (hidden until data loaded)               │
│                                                              │
│ Filters (populated from loaded data):                        │
│ [Main LOB ▼]    [State ▼]    [Case Type ▼]  [Clear Filters] │
│                                                              │
│ [Month Checkboxes: ☑ Apr-25 ☑ May-25 ...]                   │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Data Table                                               │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**Notes**:
- Returns forecast records with 6-month data starting from the selected report month
- **Initial load fetches ALL records** - no filters applied server-side in typical workflow
- **Filters are applied client-side** after data is loaded (cascading filter behavior)
- Filter query parameters still supported for backward compatibility but typically not used
- User can edit `target_cph` (per record) and `fte_avail` (per month) values in the frontend
- `months` object mapping is required for rendering the table with correct month labels
- All numeric fields in month data are integers except `target_cph` which is a float

**Client-Side Filter Behavior**:
- Filter dropdowns use cascading/dependent behavior (selecting LOB limits available States/Case Types)
- Filters use AND logic between categories, OR logic within same category
- "Clear Filters" button resets all selections and shows all loaded records

**Field Reference for Records**:

| Field | Type | Description |
|-------|------|-------------|
| `case_id` | string | Unique identifier (UUID) for the forecast record |
| `main_lob` | string | Main Line of Business (used for filter extraction) |
| `state` | string | State code (2-letter) (used for filter extraction) |
| `case_type` | string | Case type category (used for filter extraction) |
| `target_cph` | float | Target Cases Per Hour (editable) |
| `months` | object | Nested object with month-specific data |

**Month Data Fields**:

| Field | Type | Editable | Description |
|-------|------|----------|-------------|
| `forecast` | integer | No | Client forecast volume |
| `fte_req` | integer | No | FTE Required (calculated) |
| `fte_avail` | integer | Yes | FTE Available (editable via ± controls) |
| `capacity` | integer | No | Capacity (calculated from FTE Avail × Target CPH) |

**Usage Example**:
```
# Typical usage - load all data without filters
GET /api/edit-view/forecast-reallocation/data/?month=April&year=2025

# Server-side filtering (supported but typically not used in current UI)
GET /api/edit-view/forecast-reallocation/data/?month=April&year=2025&main_lobs[]=Medicaid&main_lobs[]=Medicare
GET /api/edit-view/forecast-reallocation/data/?month=April&year=2025&states[]=MO&states[]=TX&case_types[]=Appeals
```

---

## 12. Get Forecast Reallocation Preview

**Endpoint**: `POST /api/edit-view/forecast-reallocation/preview/`

**Purpose**: Calculate preview with user-edited Target CPH and FTE Available values before committing

**Request Body**:
```json
{
    "month": "April",
    "year": 2025,
    "modified_records": [
        {
            "case_id": "550e8400-e29b-41d4-a716-446655440000",
            "main_lob": "Medicaid",
            "state": "MO",
            "case_type": "Appeals",
            "target_cph": 105.0,
            "target_cph_change": 5.0,
            "modified_fields": ["target_cph", "Apr-25.fte_avail", "Jun-25.fte_avail"],
            "months": {
                "Apr-25": {
                    "forecast": 12500,
                    "fte_req": 125,
                    "fte_avail": 125,
                    "capacity": 12000,
                    "fte_avail_change": 5
                },
                "May-25": {
                    "forecast": 13000,
                    "fte_req": 130,
                    "fte_avail": 125,
                    "capacity": 12500,
                    "fte_avail_change": 0
                },
                "Jun-25": {
                    "forecast": 13500,
                    "fte_req": 135,
                    "fte_avail": 135,
                    "capacity": 13000,
                    "fte_avail_change": 5
                },
                "Jul-25": {
                    "forecast": 14000,
                    "fte_req": 140,
                    "fte_avail": 135,
                    "capacity": 13500,
                    "fte_avail_change": 0
                },
                "Aug-25": {
                    "forecast": 14500,
                    "fte_req": 145,
                    "fte_avail": 140,
                    "capacity": 14000,
                    "fte_avail_change": 0
                },
                "Sep-25": {
                    "forecast": 15000,
                    "fte_req": 150,
                    "fte_avail": 145,
                    "capacity": 14500,
                    "fte_avail_change": 0
                }
            }
        }
    ]
}
```

**Success Response** (200):
```json
{
    "success": true,
    "months": {
        "month1": "Apr-25",
        "month2": "May-25",
        "month3": "Jun-25",
        "month4": "Jul-25",
        "month5": "Aug-25",
        "month6": "Sep-25"
    },
    "month": "April",
    "year": 2025,
    "modified_records": [
        {
            "main_lob": "Medicaid",
            "state": "MO",
            "case_type": "Appeals",
            "case_id": "550e8400-e29b-41d4-a716-446655440000",
            "target_cph": 105.0,
            "target_cph_change": 5.0,
            "modified_fields": ["target_cph", "Apr-25.forecast", "Apr-25.fte_req", "Apr-25.fte_avail", "Apr-25.capacity", "Jun-25.forecast", "Jun-25.fte_req", "Jun-25.fte_avail", "Jun-25.capacity"],
            "months": {
                "Apr-25": {
                    "forecast": 12500,
                    "fte_req": 119,
                    "fte_avail": 125,
                    "capacity": 13125,
                    "forecast_change": 0,
                    "fte_req_change": -6,
                    "fte_avail_change": 5,
                    "capacity_change": 1125
                },
                "May-25": {
                    "forecast": 13000,
                    "fte_req": 124,
                    "fte_avail": 125,
                    "capacity": 13125,
                    "forecast_change": 0,
                    "fte_req_change": -6,
                    "fte_avail_change": 0,
                    "capacity_change": 625
                },
                "Jun-25": {
                    "forecast": 13500,
                    "fte_req": 129,
                    "fte_avail": 135,
                    "capacity": 14175,
                    "forecast_change": 0,
                    "fte_req_change": -6,
                    "fte_avail_change": 5,
                    "capacity_change": 1175
                },
                "Jul-25": {
                    "forecast": 14000,
                    "fte_req": 133,
                    "fte_avail": 135,
                    "capacity": 14175,
                    "forecast_change": 0,
                    "fte_req_change": -7,
                    "fte_avail_change": 0,
                    "capacity_change": 675
                },
                "Aug-25": {
                    "forecast": 14500,
                    "fte_req": 138,
                    "fte_avail": 140,
                    "capacity": 14700,
                    "forecast_change": 0,
                    "fte_req_change": -7,
                    "fte_avail_change": 0,
                    "capacity_change": 700
                },
                "Sep-25": {
                    "forecast": 15000,
                    "fte_req": 143,
                    "fte_avail": 145,
                    "capacity": 15225,
                    "forecast_change": 0,
                    "fte_req_change": -7,
                    "fte_avail_change": 0,
                    "capacity_change": 725
                }
            }
        }
    ],
    "total_modified": 1,
    "summary": {
        "total_fte_change": 10,
        "total_capacity_change": 5025
    }
}
```

**Error Response** (400):
```json
{
    "success": false,
    "error": "No records provided for preview"
}
```

**Error Response** (500):
```json
{
    "success": false,
    "error": "Failed to calculate reallocation preview"
}
```

**Notes**:
- **Calculation Logic**: Backend recalculates based on user edits:
  -  (FTE Required based on new CPH)
  - (Capacity based on new FTE Available and CPH)
- Only records with actual changes should be sent in `modified_records`
- `modified_fields` uses DOT notation to track which fields changed (e.g., "target_cph", "Apr-25.fte_avail")
- `_change` shows delta from original value (0 if value wasn't changed)
- Each month object includes `fte_avail_change`, `fte_req_change`, `capacity_change` showing delta from original value

- Preview response can be directly submitted to update endpoint after user approval

**Request Validation**:
- `month` must be full month name (January-December)
- `year` must be integer between 2020-2050
- `modified_records` must be non-empty array
- Each record must have: case_id, main_lob, state, case_type, target_cph, months
- `target_cph` must be between 0.0 and 200.0 (from ForecastReallocationConfig)
- `fte_avail` must be between 0 and 999 (from ForecastReallocationConfig)

**Field Reference for Preview Response**:

| Field | Type | Description |
|-------|------|-------------|
| `case_id` | string | Unique identifier for the record |
| `main_lob` | string | Main Line of Business |
| `state` | string | State code |
| `case_type` | string | Case type category |
| `target_cph` | float | NEW Target CPH value (after modification) |
| `target_cph_change` | float | Delta from original CPH |
| `modified_fields` | array | DOT notation list of changed fields |
| `months` | object | Month-specific calculated data |

**Month Data in Preview Response**:

| Field | Type | Description |
|-------|------|-------------|
| `forecast` | integer | Client forecast volume |
| `fte_req` | integer | FTE Required (recalculated based on new CPH) |
| `fte_req_change` | integer | Delta in FTE Required from original |
| `fte_avail` | integer | FTE Available (user-modified or original) |
| `fte_avail_change` | integer | Delta in FTE Available from original |
| `capacity` | integer | Capacity (recalculated: FTE Avail × CPH × config) |
| `capacity_change` | integer | Delta in Capacity from original |

---

## 13. Update Forecast Reallocation

**Endpoint**: `POST /api/edit-view/forecast-reallocation/update/`

**Purpose**: Save forecast reallocation changes and create history log entry

**Request Body**:
```json
{
    "month": "April",
    "year": 2025,
    "months": {
        "month1": "Apr-25",
        "month2": "May-25",
        "month3": "Jun-25",
        "month4": "Jul-25",
        "month5": "Aug-25",
        "month6": "Sep-25"
    },
    "modified_records": [
        {
            "main_lob": "Medicaid",
            "state": "MO",
            "case_type": "Appeals",
            "case_id": "550e8400-e29b-41d4-a716-446655440000",
            "target_cph": 105.0,
            "target_cph_change": 5.0,
            "modified_fields": ["target_cph", "Apr-25.forecast", "Apr-25.fte_req", "Apr-25.fte_avail", "Apr-25.capacity", "Jun-25.forecast", "Jun-25.fte_req", "Jun-25.fte_avail", "Jun-25.capacity"],
            "months": {
                "Apr-25": {
                    "forecast": 12500,
                    "fte_req": 119,
                    "fte_avail": 125,
                    "capacity": 13125,
                    "forecast_change": 0,
                    "fte_req_change": -6,
                    "fte_avail_change": 5,
                    "capacity_change": 1125
                },
                "May-25": {
                    "forecast": 13000,
                    "fte_req": 124,
                    "fte_avail": 125,
                    "capacity": 13125,
                    "forecast_change": 0,
                    "fte_req_change": -6,
                    "fte_avail_change": 0,
                    "capacity_change": 625
                },
                "Jun-25": {
                    "forecast": 13500,
                    "fte_req": 129,
                    "fte_avail": 135,
                    "capacity": 14175,
                    "forecast_change": 0,
                    "fte_req_change": -6,
                    "fte_avail_change": 5,
                    "capacity_change": 1175
                },
                "Jul-25": {
                    "forecast": 14000,
                    "fte_req": 133,
                    "fte_avail": 135,
                    "capacity": 14175,
                    "forecast_change": 0,
                    "fte_req_change": -7,
                    "fte_avail_change": 0,
                    "capacity_change": 675
                },
                "Aug-25": {
                    "forecast": 14500,
                    "fte_req": 138,
                    "fte_avail": 140,
                    "capacity": 14700,
                    "forecast_change": 0,
                    "fte_req_change": -7,
                    "fte_avail_change": 0,
                    "capacity_change": 700
                },
                "Sep-25": {
                    "forecast": 15000,
                    "fte_req": 143,
                    "fte_avail": 145,
                    "capacity": 15225,
                    "forecast_change": 0,
                    "fte_req_change": -7,
                    "fte_avail_change": 0,
                    "capacity_change": 725
                }
            }
        }
    ],
    "user_notes": "Adjusted FTE allocation for Q2 capacity optimization"
}
```

**Success Response** (200):
```json
{
    "success": true,
    "message": "Forecast reallocation updated successfully",
    "records_updated": 1,
    "history_log_id": "550e8400-e29b-41d4-a716-446655440001"
}
```

**Error Response** (400):
```json
{
    "success": false,
    "error": "Validation error: target_cph must be between 0.0 and 200.0"
}
```

**Error Response** (500):
```json
{
    "success": false,
    "error": "Failed to update forecast reallocation"
}
```

**Notes**:
- **IMPORTANT**: Send the FULL record structure from the preview response (Section 12)
- Top-level `months` dictionary is **REQUIRED** - must match the mapping received from preview response
- Frontend should send the exact structure received from the preview endpoint - DO NOT manually construct
- Creates history log entry with change type "Forecast Reallocation"
- Should be transactional (all or nothing)
- Validator will reject requests missing `months`, `modified_fields`, or required identifier fields

**Top-level Request Fields**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `month` | string | Yes | Report month name (e.g., "April") |
| `year` | number | Yes | Report year (e.g., 2025) |
| `months` | object | Yes | Month index mapping (month1-month6) to labels. Must match preview response |
| `modified_records` | array | Yes | Array of modified forecast records from preview |
| `user_notes` | string | Yes | User-provided description for audit trail (max 500 chars) |

**Modified Records Structure**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `case_id` | string | Yes | Unique identifier for the record |
| `main_lob` | string | Yes | Main Line of Business |
| `state` | string | Yes | State code |
| `case_type` | string | Yes | Case type category |
| `target_cph` | float | Yes | NEW Target CPH value |
| `target_cph_change` | float | Yes | Delta from original CPH |
| `modified_fields` | array | Yes | DOT notation list of changed fields |
| `months` | object | Yes | Month-specific data with all 6 months |

**Response Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Operation success status |
| `message` | string | Success/error message |
| `records_updated` | number | Number of forecast records updated |
| `history_log_id` | string | UUID of created history log entry (for audit trail) |

**Validation Rules**:
- `month`: Must be full month name (January-December)
- `year`: Must be integer between 2020-2050
- `modified_records`: Must be non-empty array
- `months`: Must have exactly 6 entries (month1-month6)
- `target_cph`: Must be above 0.0
- `fte_avail`: Must be above 0
- `modified_fields`: Must be non-empty array
- `user_notes`: Required, max 500 characters

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
- **Min CPH Value**: 0.0 (exclusive - CPH must be greater than 0)
- **Max CPH Value**: 200.0 (validated by Pydantic models)
- **CPH Decimal Places**: 2
- **Max User Notes Length**: 1000 characters

From `ForecastReallocationConfig` in config.py:
- **Max Months Display**: 6 months
- **Records Per Page**: 25 records
- **Min Target CPH**: 0.0
- **Max Target CPH**: 200.0
- **Min FTE Available**: 0
- **Max FTE Available**: 999
- **CPH Increment Unit**: 1.0 (for ± buttons)
- **FTE Increment Unit**: 1 (for ± buttons)
- **Data Cache TTL**: 900 seconds (15 minutes)
- **Filter Cache TTL**: 300 seconds (5 minutes)

---

## History Log Data Structure

The update endpoints (Sections 3, 9, 13) all use a **standardized data structure** that provides sufficient information for creating per-record history log entries.

### Required Fields for History Logging

Each `modified_records` entry contains:

| Field | Purpose in History Log |
|-------|----------------------|
| `main_lob` | Record identifier |
| `state` | Record identifier |
| `case_type` | Record identifier |
| `case_id` | Unique record identifier |
| `target_cph` | NEW value (after modification) |
| `target_cph_change` | Delta from original (for before/after tracking) |
| `modified_fields` | Array listing which fields changed (DOT notation) |
| `months` | Contains ALL 6 months with current values and `*_change` deltas |

### Month Data for History Logging

Each month object in `months` provides:

```json
{
    "Apr-25": {
        "forecast": 12500,       // Current value
        "fte_req": 119,          // Current value
        "fte_avail": 125,        // Current value
        "capacity": 13125,       // Current value
        "forecast_change": 0,    // Delta from original
        "fte_req_change": -6,    // Delta from original
        "fte_avail_change": 5,   // Delta from original
        "capacity_change": 1125  // Delta from original
    }
}
```

### Calculating Before Values

The history log can calculate "before" values using:
```
before_value = current_value - change_value
```

Example:
- `fte_avail` (current) = 125
- `fte_avail_change` = 5
- `fte_avail` (before) = 125 - 5 = 120

### History Log Entry Creation

When an update is processed, the backend:

1. Creates a `HistoryLogModel` entry with:
   - `history_log_id` (UUID)
   - `change_type` (e.g., "Bench Allocation", "CPH Update", "Forecast Reallocation")
   - `month`, `year` (report period)
   - `user`, `user_notes`
   - `records_modified` (count)
   - `summary_data` (aggregated totals)

2. Creates `HistoryLogChangesModel` entries for each modified record:
   - Links to `history_log_id`
   - Stores record identifiers (`main_lob`, `state`, `case_type`, `case_id`)
   - Stores `modified_fields` array
   - Stores full `months` data (for Excel export reconstruction)

### Data Sufficiency Verification

The update data structure is **sufficient** for:
- ✅ Per-record change tracking (via `modified_fields` and `*_change` fields)
- ✅ Before/after value calculation (current value - change = before value)
- ✅ Field-level audit trail (via DOT notation in `modified_fields`)
- ✅ Excel export generation (full month data preserved)
- ✅ Summary aggregation (sum of individual changes)

---

## Error Handling

All endpoints should:
1. Return proper HTTP status codes (200, 400, 404, 500)
2. Include `success` boolean in JSON responses
3. Provide descriptive error messages in `error` or `message` fields
4. Log errors server-side for debugging
