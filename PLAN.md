# Fix Bench Allocation Month Mapping Bug + Add Type Safety

## Issues Identified

### Issue 1: Month Mapping Bug (CRITICAL)
**Location**: `bench_allocation.py:265` in `get_year_for_month()`

**Problem**:
```python
target_month_num = start_month_num + (month_index - 1)
```

This assumes **Month1 = report month**, but user confirmed:
> "Usually when March month report data is fetched it has data starting from April to September"

So the actual mapping is:
- **ForecastModel.Month = "March"** (report month)
- **Month1 = April** (not March!)
- **Month2 = May**
- Month3 = June
- Month4 = July
- Month5 = August
- Month6 = September

**Current (WRONG) behavior**:
```
allocate_bench_for_month("March", 2025)
  → Month1 maps to March (WRONG! Should be April)
  → Month2 maps to April (WRONG! Should be May)
```

**Expected behavior**:
```
allocate_bench_for_month("March", 2025)
  → Month1 should map to April
  → Month2 should map to May
  → etc.
```

**Root cause**: The formula assumes Month1 starts at `start_month`, but it actually starts at `start_month + 1`.

**Fix**:
```python
# OLD (line 265):
target_month_num = start_month_num + (month_index - 1)

# NEW:
target_month_num = start_month_num + month_index
```

**Example**:
- data_month = "March" → start_month_num = 3
- month_index = 1 (Month1):
  - OLD: 3 + (1-1) = 3 → March ❌
  - NEW: 3 + 1 = 4 → April ✅
- month_index = 2 (Month2):
  - OLD: 3 + (2-1) = 4 → April ❌
  - NEW: 3 + 2 = 5 → May ✅

### Issue 2: Type Safety (HIGH PRIORITY)
**Location**: `bench_allocation.py:724-732` - Return dict

**Problem**: Function returns a complex nested dict structure, making it hard to:
- Understand what fields are available
- Do type checking/assertions
- Catch typos (e.g., `result['alocation']` would fail at runtime)

**Solution**: Use Python dataclasses for type-safe return structures

## Implementation Plan

### Step 1: Replace Month Generation Logic with ForecastMonthsModel

**CRITICAL CHANGE**: Don't generate month names using date math. Fetch from ForecastMonthsModel instead.

**File**: `code/logics/bench_allocation.py`

**Problem**: Current `get_year_for_month()` uses hardcoded logic that can break if business rules change.

**Solution**: Query ForecastMonthsModel to get actual month mappings.

**New function** (replace get_year_for_month):
```python
def get_month_mappings_from_db(core_utils: CoreUtils, uploaded_file: str) -> Dict[int, Dict[str, any]]:
    """
    Get month mappings from ForecastMonthsModel for a given uploaded file.

    Returns:
        Dict mapping month_index (1-6) to {'month': name, 'year': year}
    """
    from code.logics.db import ForecastMonthsModel

    db_manager = core_utils.get_db_manager(ForecastMonthsModel, limit=1, skip=0)

    with db_manager.SessionLocal() as session:
        months_record = session.query(ForecastMonthsModel).filter(
            ForecastMonthsModel.UploadedFile == uploaded_file
        ).first()

        if not months_record:
            raise ValueError(f"No month mappings found for file: {uploaded_file}")

    # Parse month names to get years (handle year wrapping)
    # This is still safer than generating - uses actual data from DB
    mappings = {}
    for i in range(1, 7):
        month_name = getattr(months_record, f'Month{i}')
        # Extract year from month name or calculate based on sequence
        # Implementation depends on how years are stored
        mappings[i] = {'month': month_name, 'year': calculate_year(month_name, ...)}

    return mappings
```

**Update unnormalize_forecast_data**:
```python
def unnormalize_forecast_data(month, year, core_utils):
    # ... fetch forecast_records ...

    # NEW: Get month mappings from first record
    if forecast_records:
        uploaded_file = forecast_records[0].UploadedFile
        month_mappings = get_month_mappings_from_db(core_utils, uploaded_file)

    rows = []
    for record in forecast_records:
        for month_idx in range(1, 7):
            # NEW: Use DB mappings instead of calculating
            month_data = month_mappings[month_idx]
            actual_month_name = month_data['month']
            actual_year = month_data['year']

            # ... rest of row creation ...
```

### Step 2: Add Type-Safe Return Structure

**File**: `code/logics/bench_allocation.py` (top of file, after imports)

**Add dataclasses**:
```python
from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class VendorAllocation:
    """Single vendor allocation details"""
    first_name: str
    last_name: str
    cn: str
    skills: str
    state_list: List[str]
    # Add any other vendor fields

@dataclass
class ForecastRowData:
    """Forecast row data with allocation updates"""
    forecast_id: int
    main_lob: str
    state: str
    case_type: str
    target_cph: float
    month_name: str
    month_year: int
    month_index: int
    forecast: float
    fte_required: float
    fte_avail: float
    fte_avail_original: float
    capacity: int
    capacity_original: int

@dataclass
class AllocationRecord:
    """Single allocation record with forecast and vendor details"""
    forecast_row: ForecastRowData
    vendors: List[VendorAllocation]
    gap_fill_count: int
    excess_distribution_count: int
    fte_change: int
    capacity_change: int

@dataclass
class AllocationResult:
    """Complete allocation result"""
    success: bool
    month: str
    year: int
    total_bench_allocated: int
    gaps_filled: int
    excess_distributed: int
    rows_modified: int
    allocations: List[AllocationRecord]
    error: str = ""  # Only populated if success=False
```

**Update return statements** (lines 724-732):
```python
# Replace dict return with dataclass
return AllocationResult(
    success=True,
    month=month,
    year=year,
    total_bench_allocated=len(all_allocations),
    gaps_filled=gaps_filled,
    excess_distributed=excess_distributed,
    rows_modified=len(consolidated_allocations),
    allocations=[
        AllocationRecord(
            forecast_row=ForecastRowData(**data['forecast_row']),
            vendors=[VendorAllocation(**v) for v in data['vendors']],
            gap_fill_count=data['gap_fill_count'],
            excess_distribution_count=data['excess_distribution_count'],
            fte_change=data['fte_change'],
            capacity_change=data['capacity_change']
        )
        for data in final_allocations_list
    ]
)
```

### Step 3: Update Test File to Use Dataclasses

**File**: `code/logics/test_bench_allocation_comprehensive.py`

**Update to access dataclass fields**:
```python
# OLD (dict access):
result['success']
result['allocations']
alloc['forecast_row']

# NEW (dataclass attribute access):
result.success
result.allocations
alloc.forecast_row
```

### Step 4: Add Debug Logging (Development Only)

**File**: `code/logics/bench_allocation.py`

**Use logger.debug()** for development logs (won't appear in production):
```python
# After getting month mappings:
month_data = month_mappings[month_idx]
actual_month_name = month_data['month']
actual_year = month_data['year']

# ADD DEBUG LOG (development only):
if month_idx == 1:  # Log first month for each record
    logger.debug(f"Report Month: {month} {year} | Month{month_idx} maps to: {actual_month_name} {actual_year}")
```

**Note**: Use `logger.debug()` instead of `logger.info()` so logs don't clutter production.

## Testing Plan

### Test Case 1: Verify Month Mapping
**Input**: `allocate_bench_for_month("March", 2025)`

**Expected Output** (in Excel Allocations tab):
- Month1 data should show **April 2025**
- Month2 data should show **May 2025**
- Month3 data should show **June 2025**
- Month4 data should show **July 2025**
- Month5 data should show **August 2025**
- Month6 data should show **September 2025**

**NOT March!** March is the report month, not the data month.

### Test Case 2: Type Safety
```python
result = allocate_bench_for_month("March", 2025)

# Should have IDE autocomplete:
result.success  # ✅ Type-safe
result.allocations  # ✅ Type-safe
result.allocations[0].forecast_row.main_lob  # ✅ Type-safe

# Typos caught at dev time:
result.sucesss  # ❌ IDE error
result.alocation  # ❌ IDE error
```

### Step 5: Fix get_unallocated_vendors_with_states

**File**: `code/logics/bench_allocation.py`

**Problem**: Function should use allocation_id to retrieve report data.

**Update function signature and logic**:
```python
def get_unallocated_vendors_with_states(allocation_id: str, core_utils: CoreUtils) -> pd.DataFrame:
    """
    Get unallocated vendors from AllocationReportsModel using allocation_id.

    Args:
        allocation_id: The execution ID from AllocationExecutionModel
        core_utils: CoreUtils instance for DB access

    Returns:
        DataFrame of unallocated vendors with their state lists
    """
    from code.logics.db import AllocationReportsModel

    db_manager = core_utils.get_db_manager(AllocationReportsModel, limit=None, skip=0)

    with db_manager.SessionLocal() as session:
        # Query report data using allocation_id
        report = session.query(AllocationReportsModel).filter(
            AllocationReportsModel.execution_id == allocation_id,
            AllocationReportsModel.ReportType == 'roster_allotment'  # Or appropriate type
        ).first()

        if not report:
            raise ValueError(f"No report found for allocation_id: {allocation_id}")

        # Parse JSON report data
        import json
        report_data = json.loads(report.ReportData)

        # Extract unallocated vendors
        # ... implementation depends on report structure ...
```

## Files to Modify

1. **`code/logics/bench_allocation.py`**:
   - Replace `get_year_for_month()` with `get_month_mappings_from_db()`
   - Update `unnormalize_forecast_data()` to use ForecastMonthsModel
   - Top of file: Add dataclass definitions
   - Line 724-732: Update return to use dataclass
   - Update `get_unallocated_vendors_with_states()` to use allocation_id
   - Add debug logging (use logger.debug(), not logger.info())

2. **`code/logics/test_bench_allocation_comprehensive.py`**:
   - Update all dict access to dataclass attribute access
   - Update typing hints if present

## Summary of Changes

**Critical Fix**:
- ✅ Replace hardcoded month generation with ForecastMonthsModel query (future-proof!)
- ✅ Fix month mapping to use actual DB data instead of date math

**Type Safety**:
- ✅ Add dataclasses for AllocationResult, AllocationRecord, ForecastRowData, VendorAllocation
- ✅ Update return statement to use dataclasses
- ✅ Update test file to use dataclass attributes

**Additional Fixes**:
- ✅ Update `get_unallocated_vendors_with_states()` to use allocation_id parameter
- ✅ Use `logger.debug()` for development logs (not logger.info())

**Why These Changes Are Better**:
1. **ForecastMonthsModel**: No hardcoded logic = no future breakage when business rules change
2. **Dataclasses**: Type safety catches errors at dev time, not runtime
3. **execution_id**: Proper parameter passing for report retrieval
4. **logger.debug()**: Clean production logs without dev noise

This will fix the bug where wrong months were being updated AND make the code more maintainable.