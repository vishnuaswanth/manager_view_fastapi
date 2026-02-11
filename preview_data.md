# Preview Response Standardization

**Created:** December 31, 2024
**Status:** Required for FastAPI Backend Implementation

## Problem Statement

Currently, the Bench Allocation and Target CPH preview endpoints return different data structures, causing unnecessary code duplication in the frontend. The only functional differences are:
- Bench allocation includes `target_cph` and `target_cph_change` fields
- CPH preview includes `case_id` field
- Both display the same month-wise forecast data with change tracking

## Standardized Response Format

Both `/api/bench-allocation/preview` and `/api/target-cph/preview` MUST return this structure:

```json
{
  "success": true,
  "total_modified": 150,
  "modified_records": [
    {
      "id": "unique_record_id",
      "main_lob": "Medicaid",
      "state": "MO",
      "case_type": "Appeals",
      "case_id": "CASE-123",                    // Optional - present in CPH preview
      "target_cph": 100.0,                      // Optional - present in bench allocation
      "target_cph_change": 5.0,                 // Optional - present in bench allocation
      "modified_fields": [
        "target_cph",                           // If target_cph was modified
        "Jun-25.fte_req",                      // If June FTE Req was modified
        "Jun-25.capacity",                     // If June Capacity was modified
        "Jul-25.fte_avail"                     // etc.
      ],
      "Jun-25": {
        "forecast": 12500,                     // Client forecast (never modified)
        "fte_req": 10.5,                       // FTE Required (new value)
        "fte_req_change": 2.3,                 // Change amount (can be negative)
        "fte_avail": 8.2,                      // FTE Available (new value)
        "fte_avail_change": 1.5,               // Change amount
        "capacity": 0.78,                      // Capacity % (new value)
        "capacity_change": 0.05                // Change amount
      },
      "Jul-25": { /* same structure */ },
      "Aug-25": { /* same structure */ }
    }
  ],
  "summary": {
    "total_fte_change": 45.5,
    "total_capacity_change": 2250
  },
  "message": null  // or error message if success=false
}
```

## Field Standards

### Fixed Columns
- `id`: Unique identifier (string/UUID)
- `main_lob`: Main line of business (string)
- `state`: State code (string, e.g., "MO", "LA")
- `case_type`: Type of case (string)
- `case_id`: **(Optional)** Case identifier - present in CPH preview
- `target_cph`: **(Optional)** Target CPH value - present in bench allocation
- `target_cph_change`: **(Optional)** Change in target CPH - present in bench allocation

### Modified Fields Array
Format: `"{month_code}.{field_name}"` OR `"target_cph"`

Examples:
- `"target_cph"` - target CPH was modified
- `"Jun-25.fte_req"` - June FTE Required was modified
- `"Jun-25.fte_avail"` - June FTE Available was modified
- `"Jun-25.capacity"` - June Capacity was modified

**DO NOT USE:**
- ❌ Underscore: `"Jun-25_fte_req"` (WRONG)
- ❌ Different names: `"Jun-25.fte_required"` (WRONG - should be `fte_req`)

### Month Data Structure
Each month key (e.g., `"Jun-25"`, `"Jul-25"`) contains:

```javascript
{
  "forecast": 12500,         // Client forecast (number, never modified)
  "fte_req": 10.5,          // FTE Required (number, new value)
  "fte_req_change": 2.3,    // Change in FTE Required (can be negative)
  "fte_avail": 8.2,         // FTE Available (number, new value)
  "fte_avail_change": 1.5,  // Change in FTE Available
  "capacity": 0.78,         // Capacity percentage (number, new value)
  "capacity_change": 0.05   // Change in capacity
}
```

**Field Name Standards:**
- ✅ `fte_req` (correct)
- ✅ `fte_avail` (correct)
- ✅ `forecast` (correct)
- ✅ `capacity` (correct)
- ❌ `fte_required` (WRONG)
- ❌ `fte_available` (WRONG)
- ❌ `cf` (WRONG - use `forecast`)

**DO NOT** nest month data under a `data` property:
- ✅ `record["Jun-25"]` (correct)
- ❌ `record.data["Jun-25"]` (WRONG)

## Backend Implementation Requirements

### Bench Allocation Preview Endpoint
**URL:** `POST /api/bench-allocation/preview`

**Request:**
```json
{
  "month": "April",
  "year": 2025
}
```

**Response:** Follow standard format above with:
- Include `target_cph` and `target_cph_change` if modified
- Do NOT include `case_id`
- Month data directly on record (not nested under `data`)

### Target CPH Preview Endpoint
**URL:** `POST /api/target-cph/preview`

**Request:**
```json
{
  "month": "April",
  "year": 2025,
  "modified_records": [
    {
      "id": "cph_1",
      "lob": "Medicaid",
      "case_type": "Appeals",
      "target_cph": 100.0,
      "modified_target_cph": 105.0
    }
  ]
}
```

**Response:** Follow standard format above with:
- Include `case_id` field
- Do NOT include `target_cph` or `target_cph_change`
- Month data directly on record (not nested under `data`)

## Frontend Benefits

With this standardization, the frontend can:

1. **Eliminate ~300 lines of duplicate code**
2. **Use shared rendering functions:**
   - `renderPreviewTable(data, config)`
   - `renderPreviewHeaders(months)`
   - `renderPreviewRows(records, months)`
   - `renderPreviewTotals(records, months)`
   - `applyPreviewFilters()`

3. **Configuration-driven rendering:**
```javascript
const BENCH_CONFIG = {
  showTargetCph: true,
  showCaseId: false,
  container: DOM.previewContainer,
  tableHead: DOM.previewTableHead,
  // ... other bench-specific DOM elements
};

const CPH_CONFIG = {
  showTargetCph: false,
  showCaseId: true,
  container: DOM.cphPreviewContainer,
  tableHead: DOM.cphPreviewTableHead,
  // ... other CPH-specific DOM elements
};

// Use same function for both
renderPreviewTable(data, BENCH_CONFIG);
renderPreviewTable(data, CPH_CONFIG);
```

## Validation Checklist

Before merging backend changes, verify:

- [ ] No nested `data` object - months are directly on record
- [ ] Field names use underscore: `fte_req`, `fte_avail`, `forecast`, `capacity`
- [ ] `modified_fields` use dot notation: `"Jun-25.fte_req"`
- [ ] Month codes match frontend regex: `/^[A-Z][a-z]{2}-\d{2}$/` (e.g., "Jun-25")
- [ ] Optional fields handled correctly (`target_cph`, `case_id`)
- [ ] All change fields can be negative numbers
- [ ] `forecast` field is never modified (no `forecast_change`)

## Migration Steps

1. **Update FastAPI Backend:**
   - Modify bench allocation preview serializer
   - Modify CPH preview serializer
   - Use shared base serializer
   - Test both endpoints return same structure

2. **Update Django Frontend:**
   - Consolidate preview rendering functions
   - Add configuration objects for each preview type
   - Remove duplicate code from `edit_view.js` lines 2322-2620
   - Update tests

3. **Verify:**
   - Both previews render correctly
   - Filters work on both
   - Pagination works on both
   - Month-wise summary displays correctly

## Contact

For questions about this specification:
- Django repo: centene_forecast_app
- Reference file: `static/centene_forecast_app/js/edit_view.js`
- Related: `edit_serializers.py`, `edit_service.py`
