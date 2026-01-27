# Forecast Data Cleaning Fix - allocation.py

## Issue

In the `process_files()` function, forecast data loaded from Excel files could contain NaN values. These NaN values were not cleaned until AFTER being used in Target CPH and FTE Required calculations, causing potential calculation errors.

## Date
2026-01-20

---

## Problem Description

### Before Fix:

The data flow was:
1. **Line 1742-1748**: Load Client Forecast data via `get_value()` (may contain NaN)
2. **Line 1750**: Calculate Target CPH (uses potentially NaN forecast data in matching)
3. **Line 1752**: Calculate FTE Required (uses NaN forecast values)
4. **Line 1754**: Clean all NaN values with `fillna(0)` ← **TOO LATE!**

### Issues Caused:

1. **NaN in FTE Required calculations**
   ```python
   # If forecast = NaN
   fte_required = calculate_fte_required(NaN, config, target_cph)
   # Result: Could produce NaN or unexpected values
   ```

2. **NaN propagation**
   - NaN forecast values propagate through calculations
   - Results in invalid FTE Required values
   - Causes allocation failures

3. **Data integrity**
   - Final output_df has clean data (due to line 1754)
   - But intermediate calculations used dirty data
   - Inconsistent calculation results

---

## Solution

### Added Immediate Data Cleaning

**File**: `code/logics/allocation.py`

**Location**: Lines 1749-1755 (after forecast loading, before calculations)

```python
for month in month_headers:
    if file_type == 'medicare_medicaid_mmp':
        output_df[('Client Forecast', month)] = output_df.apply(...)
    elif file_type == 'medicare_medicaid_nonmmp':
        output_df[('Client Forecast', month)] = output_df.apply(...)
    elif file_type == 'medicare_medicaid_summary':
        output_df[('Client Forecast', month)] = output_df.apply(...)

# ✅ NEW: Clean forecast data IMMEDIATELY after loading
# This ensures FTE Required and Capacity calculations work correctly
for month in month_headers:
    output_df[('Client Forecast', month)] = output_df[('Client Forecast', month)].fillna(0)

# ✅ NEW: Clean Target CPH after retrieval
output_df[('Centene Capacity plan', 'Target CPH')] = output_df.apply(calculations.get_target_cph, axis=1)
output_df[('Centene Capacity plan', 'Target CPH')] = output_df[('Centene Capacity plan', 'Target CPH')].fillna(0)

# Now calculations use clean data
for month in month_headers:
    output_df[('FTE Required', month)] = output_df.apply(lambda row: get_fte_required(row, month, calculations), axis=1)
```

---

## Changes Made

### 1. Clean Client Forecast Columns (Lines ~1749-1751)

**Before:**
```python
for month in month_headers:
    output_df[('Client Forecast', month)] = output_df.apply(...)
# No cleaning here!

output_df[('Centene Capacity plan', 'Target CPH')] = ...
```

**After:**
```python
for month in month_headers:
    output_df[('Client Forecast', month)] = output_df.apply(...)

# Clean forecast data: Replace NaN with 0 BEFORE calculations
for month in month_headers:
    output_df[('Client Forecast', month)] = output_df[('Client Forecast', month)].fillna(0)

output_df[('Centene Capacity plan', 'Target CPH')] = ...
```

### 2. Clean Target CPH Column (Line ~1753)

**Before:**
```python
output_df[('Centene Capacity plan', 'Target CPH')] = output_df.apply(calculations.get_target_cph, axis=1)
# No cleaning here!

for month in month_headers:
    output_df[('FTE Required', month)] = ...
```

**After:**
```python
output_df[('Centene Capacity plan', 'Target CPH')] = output_df.apply(calculations.get_target_cph, axis=1)
output_df[('Centene Capacity plan', 'Target CPH')] = output_df[('Centene Capacity plan', 'Target CPH')].fillna(0)

for month in month_headers:
    output_df[('FTE Required', month)] = ...
```

---

## Impact

### Before Fix:

| Scenario | Result |
|----------|--------|
| Excel cell empty | `get_value()` returns 0 ✓ |
| Excel cell = `#N/A` | Pandas reads as NaN → used in calculations ❌ |
| Excel cell = blank string | May be NaN → used in calculations ❌ |
| Target CPH not found | Returns 0 ✓ |
| Target CPH = NaN in source | Used as NaN in calculations ❌ |

### After Fix:

| Scenario | Result |
|----------|--------|
| Excel cell empty | `get_value()` returns 0 ✓ |
| Excel cell = `#N/A` | Pandas reads as NaN → **cleaned to 0** ✓ |
| Excel cell = blank string | May be NaN → **cleaned to 0** ✓ |
| Target CPH not found | Returns 0 ✓ |
| Target CPH = NaN in source | **Cleaned to 0** ✓ |

---

## Example Scenarios

### Scenario 1: Empty Forecast Cell

**Input Excel:**
```
Month1 Forecast: [empty cell]
```

**Before Fix:**
```python
forecast = NaN  # From Excel
fte_required = calculate_fte_required(NaN, config, 50.0)
# Result: NaN or error
```

**After Fix:**
```python
forecast = NaN  # From Excel
forecast = fillna(0)  # Cleaned immediately
# forecast = 0
fte_required = calculate_fte_required(0, config, 50.0)
# Result: 0 (correct!)
```

---

### Scenario 2: #N/A Error in Excel

**Input Excel:**
```
Month1 Forecast: #N/A (formula error)
```

**Before Fix:**
```python
forecast = NaN  # Pandas reads #N/A as NaN
fte_required = calculate_fte_required(NaN, config, 50.0)
# Result: NaN propagates through calculation
```

**After Fix:**
```python
forecast = NaN  # Pandas reads #N/A as NaN
forecast = fillna(0)  # Cleaned immediately
# forecast = 0
fte_required = calculate_fte_required(0, config, 50.0)
# Result: 0 (correct!)
```

---

### Scenario 3: Valid Forecast Data

**Input Excel:**
```
Month1 Forecast: 10000
```

**Before & After (No Change):**
```python
forecast = 10000
fte_required = calculate_fte_required(10000, config, 50.0)
# Result: 2 (correct!)
```

---

## Data Flow Comparison

### Before Fix:

```
Excel File
    ↓
get_value() → May contain NaN
    ↓
[NaN values present]
    ↓
get_target_cph() ← Uses NaN data
    ↓
get_fte_required() ← Uses NaN forecast
    ↓
[Calculations may produce NaN]
    ↓
fillna(0) ← Cleans NaN AFTER calculations
    ↓
Output (clean but calculations were wrong)
```

### After Fix:

```
Excel File
    ↓
get_value() → May contain NaN
    ↓
fillna(0) ✓ Clean immediately
    ↓
[All forecast data is now 0 or valid number]
    ↓
get_target_cph() ← Uses clean data
fillna(0) ✓ Clean Target CPH
    ↓
get_fte_required() ← Uses clean forecast and CPH
    ↓
[Calculations produce correct values]
    ↓
Output (clean and calculations are correct)
```

---

## Testing Recommendations

### 1. Test with Empty Cells

Create test Excel file with:
- Empty forecast cells
- #N/A errors
- Blank strings
- Mix of valid and invalid data

**Expected Result:**
- All empty/NaN cells treated as 0
- FTE Required calculations complete successfully
- No NaN values in output

### 2. Test with Valid Data

Create test Excel file with:
- All valid forecast numbers
- Valid Target CPH

**Expected Result:**
- Calculations unchanged
- Results match previous behavior
- No regression

### 3. Test Edge Cases

- All forecasts = 0
- All forecasts = NaN (entire column empty)
- Mix of 0 and NaN
- Very large numbers

---

## Benefits

### 1. ✅ Data Integrity

- All calculations use clean data
- No NaN propagation
- Consistent results

### 2. ✅ Calculation Accuracy

- FTE Required calculations always work
- Capacity calculations always work
- No unexpected NaN results

### 3. ✅ Error Prevention

- Prevents NaN-related calculation failures
- Prevents allocation errors
- Prevents invalid database records

### 4. ✅ Business Logic Correctness

- Empty forecast = 0 is correct business logic
- Missing Target CPH = 0 is safe default
- Calculations proceed normally

---

## Backward Compatibility

### ✅ Fully Backward Compatible

- Existing clean data behaves the same
- Only affects data with NaN values
- No changes to calculation formulas
- No changes to output format

### Migration Notes

- No data migration needed
- No database changes required
- Simply restart server to apply fix
- Existing forecasts unaffected

---

## Related Code

### Functions That Benefit:

1. **`get_fte_required()`** (Line 257)
   - Now always receives clean forecast data
   - No more NaN input

2. **`get_capacity()`** (Line 1289)
   - Uses FTE Available (populated after allocation)
   - Benefits indirectly from clean calculations

3. **`calculate_fte_required()`** (capacity_calculations.py)
   - Now handles target_cph = 0 (from earlier fix)
   - Receives clean forecast data

4. **`calculate_capacity()`** (capacity_calculations.py)
   - Now handles target_cph = 0 (from earlier fix)
   - Receives clean FTE data

---

## Code Location

**File:** `code/logics/allocation.py`

**Function:** `process_files()` (Line 1576)

**Modified Section:** Lines 1749-1757 (approximately)

---

## Verification Steps

1. **Check data cleaning occurs**:
   ```python
   # After loading forecast data
   for month in month_headers:
       output_df[('Client Forecast', month)].isna().sum()
   # Should be 0
   ```

2. **Verify calculations work**:
   ```python
   # FTE Required should never be NaN
   for month in month_headers:
       output_df[('FTE Required', month)].isna().sum()
   # Should be 0
   ```

3. **Check final output**:
   ```python
   # Final DataFrame should have no NaN
   output_df.isna().sum().sum()
   # Should be 0
   ```

---

## Conclusion

Successfully added immediate data cleaning for forecast data and Target CPH values in the allocation process. This ensures:

- ✅ **All NaN values converted to 0** before calculations
- ✅ **FTE Required calculations** always work correctly
- ✅ **No NaN propagation** through the system
- ✅ **Data integrity** maintained throughout process
- ✅ **Backward compatible** with existing data

The fix is simple, safe, and prevents potential calculation errors from NaN values in source Excel files.
