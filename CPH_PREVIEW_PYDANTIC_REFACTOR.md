# CPH Preview Pydantic Response Type Refactor

## Summary

Refactored `calculate_cph_preview()` function in `code/logics/cph_update_transformer.py` to return a validated Pydantic `PreviewResponse` model instead of a plain dictionary.

## Changes Made

### 1. Updated Imports (`cph_update_transformer.py`)

**Added:**
```python
from code.logics.bench_allocation_transformer import (
    PreviewResponse,
    ModifiedRecordResponse,
    MonthDataResponse,
    SummaryResponse
)
```

### 2. Updated Function Signature

**Before:**
```python
def calculate_cph_preview(
    month: str,
    year: int,
    modified_cph_records: List[Dict],
    core_utils: CoreUtils
) -> Dict:
```

**After:**
```python
def calculate_cph_preview(
    month: str,
    year: int,
    modified_cph_records: List[Dict],
    core_utils: CoreUtils
) -> PreviewResponse:
```

### 3. Restructured Modified Records

**Before (Dict structure with dynamic keys):**
```python
record = {
    "id": str(uuid.uuid4()),
    "main_lob": forecast_row.Main_LOB,
    "state": forecast_row.State,
    "case_type": forecast_row.Case_Type,
    "case_id": forecast_row.Case_ID,
    "target_cph": cph_record['target_cph'],
    "target_cph_change": ...,
    "modified_fields": ["target_cph"],
    "Jun-25": {  # Dynamic month keys at root level
        "forecast": ...,
        "fte_req": ...,
        ...
    },
    "Jul-25": {...}
}
```

**After (Pydantic models with nested months):**
```python
# Create month data using MonthDataResponse
month_data[month_label] = MonthDataResponse(
    forecast=int(forecast),
    fte_req=int(new_fte_req),
    fte_req_change=int(fte_req_change),
    fte_avail=int(fte_avail),
    fte_avail_change=0,
    capacity=int(new_capacity),
    capacity_change=int(capacity_change)
)

# Create record using ModifiedRecordResponse
record = ModifiedRecordResponse(
    main_lob=forecast_row.Main_LOB,
    state=forecast_row.State,
    case_type=forecast_row.Case_Type,
    case_id=forecast_row.Case_ID,
    target_cph=int(cph_record['target_cph']),
    target_cph_change=int(cph_record['modified_target_cph'] - cph_record['target_cph']),
    modified_fields=modified_fields,
    months=month_data  # Months nested under "months" key
)
```

### 4. Updated Return Statement

**Before (Dict):**
```python
return {
    "success": True,
    "months": months_dict,
    "month": month,
    "year": year,
    "modified_records": modified_records,
    "total_modified": len(modified_records),
    "summary": {
        "total_fte_change": ...,
        "total_capacity_change": ...
    },
    "message": f"Preview shows forecast impact of {len(actual_changes)} CPH changes"
}
```

**After (Pydantic PreviewResponse):**
```python
summary = SummaryResponse(
    total_fte_change=int(total_fte_change),
    total_capacity_change=int(total_capacity_change)
)

return PreviewResponse(
    success=True,
    months=months_dict,
    month=month,
    year=year,
    modified_records=modified_records,
    total_modified=len(modified_records),
    summary=summary,
    message=f"Preview shows forecast impact of {len(actual_changes)} CPH changes"
)
```

### 5. Updated Router Type Annotation (`edit_view_router.py`)

**Added import:**
```python
from code.logics.bench_allocation_transformer import (
    transform_allocation_result_to_preview,
    calculate_summary_data,
    PreviewResponse  # Added
)
```

**Updated endpoint:**
```python
@router.post("/api/edit-view/target-cph/preview/", response_model=PreviewResponse)
async def preview_target_cph_changes(request: CPHPreviewRequest) -> PreviewResponse:
    """
    Preview forecast impact of CPH changes.

    Args:
        request: CPH preview request with modified records

    Returns:
        PreviewResponse: Validated Pydantic model with affected forecast records
    """
    # ... implementation ...
    return preview_response
```

## Benefits

### 1. **Type Safety**
- Static type checking with mypy/pyright
- IDE autocomplete and type hints
- Catches type errors at development time

### 2. **Validation**
- Automatic validation of all fields
- Ensures data integrity (e.g., integers are actually integers)
- Prevents invalid data from being returned

### 3. **API Documentation**
- FastAPI automatically generates accurate OpenAPI/Swagger docs
- `response_model` parameter enables response schema in API docs
- Better developer experience for API consumers

### 4. **Consistency**
- Matches bench allocation preview pattern
- Reuses existing Pydantic models
- Unified response structure across all preview endpoints

### 5. **Maintainability**
- Centralized response structure definition
- Single source of truth for response schema
- Easier to modify response structure in future

## Data Structure Differences

### Preview Response (Pydantic - Used in Preview Endpoint)

**Structure:**
```json
{
  "success": true,
  "months": {"month1": "Jun-25", ...},
  "modified_records": [
    {
      "main_lob": "...",
      "state": "CA",
      "case_type": "...",
      "case_id": "...",
      "target_cph": 45,
      "target_cph_change": 5,
      "modified_fields": ["target_cph", "Jun-25.fte_req"],
      "months": {  // <-- Months nested under "months" key
        "Jun-25": {
          "forecast": 1000,
          "fte_req": 10,
          "fte_req_change": 2,
          "fte_avail": 15,
          "fte_avail_change": 0,
          "capacity": 1500,
          "capacity_change": 100
        }
      }
    }
  ]
}
```

### Update Request (ModifiedForecastRecord - Used in Update Endpoint)

**Structure:**
```json
{
  "month": "April",
  "year": 2025,
  "months": {"month1": "Jun-25", ...},
  "modified_records": [
    {
      "main_lob": "...",
      "state": "CA",
      "case_type": "...",
      "case_id": "...",
      "target_cph": 45,
      "target_cph_change": 5,
      "modified_fields": ["target_cph", "Jun-25.fte_req"],
      "Jun-25": {  // <-- Dynamic month keys at root level
        "forecast": 1000,
        "fte_req": 10,
        "fte_req_change": 2,
        ...
      },
      "Jul-25": {...}
    }
  ]
}
```

**Note:** The frontend is responsible for flattening the nested structure when converting preview data to update request format.

## Testing

### Compilation Tests
- ✅ `code/logics/cph_update_transformer.py` compiles without errors
- ✅ `code/api/routers/edit_view_router.py` compiles without errors

### Type Checking
Run mypy to verify type annotations:
```bash
mypy code/logics/cph_update_transformer.py
mypy code/api/routers/edit_view_router.py
```

### Integration Testing
Test the preview endpoint:
```bash
# Start the server
python3 -m uvicorn code.main:app --reload

# Test the endpoint (use actual data from your database)
curl -X POST "http://localhost:8000/api/edit-view/target-cph/preview/" \
  -H "Content-Type: application/json" \
  -d '{
    "month": "April",
    "year": 2025,
    "modified_records": [
      {
        "id": "cph_1",
        "lob": "Amisys Medicaid DOMESTIC",
        "case_type": "Claims Processing",
        "target_cph": 45.0,
        "modified_target_cph": 50.0
      }
    ]
  }'
```

## Files Modified

1. `/code/logics/cph_update_transformer.py`
   - Added Pydantic model imports
   - Updated function signature
   - Restructured data to use Pydantic models
   - Updated return statement

2. `/code/api/routers/edit_view_router.py`
   - Added PreviewResponse import
   - Added response_model parameter to endpoint
   - Added return type annotation

## Migration Notes

### No Breaking Changes for API Consumers

The JSON structure returned by the API has changed:
- **Before:** Dynamic month keys at root level of each record
- **After:** Months nested under "months" key

**Frontend teams must update their code to handle the new structure.**

### Backward Compatibility

If backward compatibility is required, create a compatibility layer:

```python
def flatten_preview_response(preview: PreviewResponse) -> Dict:
    """Convert PreviewResponse to legacy dict format."""
    response_dict = preview.dict()

    # Flatten months for each record
    for record in response_dict['modified_records']:
        months = record.pop('months', {})
        for month_label, month_data in months.items():
            record[month_label] = month_data

    return response_dict
```

## Future Improvements

1. **Update the update endpoint** to accept nested month structure
2. **Eliminate dual structures** by standardizing on Pydantic models throughout
3. **Add response validation tests** using pytest and Pydantic
4. **Generate TypeScript types** from Pydantic models for frontend
