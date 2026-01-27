# Target CPH = 0 Handling - Implementation Summary

## Overview

Updated FTE Required and Capacity calculation functions to allow `target_cph = 0` and handle it appropriately by returning 0 values.

## Date
2026-01-20

---

## Business Requirement

When `target_cph = 0` (no target set), the system should:
- Return **FTE Required = 0** (no staff needed if no target)
- Return **Capacity = 0.0** (no capacity if no target)

This allows for scenarios where Target CPH has not yet been configured or is temporarily disabled.

---

## Changes Made

### File Modified: `code/logics/capacity_calculations.py`

#### 1. **Updated `calculate_fte_required()` Function**

**Previous Validation:**
```python
if target_cph <= 0:
    raise ValueError(f"target_cph must be positive: {target_cph}")
```

**New Validation:**
```python
if target_cph < 0:
    raise ValueError(f"target_cph cannot be negative: {target_cph}")

# Special case: zero target_cph (no target set, FTE required is 0)
if target_cph == 0:
    return 0
```

**Changes:**
- ✅ Now allows `target_cph = 0` (previously rejected)
- ✅ Returns `0` when `target_cph = 0` (avoids division by zero)
- ✅ Still rejects negative values (`target_cph < 0`)

---

#### 2. **Updated `calculate_capacity()` Function**

**Previous Validation:**
```python
if target_cph <= 0:
    raise ValueError(f"target_cph must be positive: {target_cph}")
```

**New Validation:**
```python
if target_cph < 0:
    raise ValueError(f"target_cph cannot be negative: {target_cph}")

# Special case: zero target_cph (no target set, capacity is 0)
if target_cph == 0:
    return 0.0
```

**Changes:**
- ✅ Now allows `target_cph = 0` (previously rejected)
- ✅ Returns `0.0` when `target_cph = 0` (no capacity without target)
- ✅ Still rejects negative values (`target_cph < 0`)

---

#### 3. **Updated Docstrings**

Both functions now document the new behavior:

**FTE Required:**
```python
"""
Args:
    target_cph: Target Cases Per Hour (>= 0, if 0 returns 0)

Returns:
    FTE Required (integer, always ceiling)
    Returns 0 if forecast is 0 or target_cph is 0

Examples:
    >>> calculate_fte_required(1000, config, 50.0)
    2
    >>> calculate_fte_required(1000, config, 0)
    0
"""
```

**Capacity:**
```python
"""
Args:
    target_cph: Target Cases Per Hour (>= 0, if 0 returns 0.0)

Returns:
    Capacity (float, rounded to 2 decimal places)
    Returns 0.0 if fte_avail is 0 or target_cph is 0

Examples:
    >>> calculate_capacity(10, config, 50.0)
    85050.0
    >>> calculate_capacity(10, config, 0)
    0.0
"""
```

---

## Behavior Summary

### Before Changes:

| Input | Previous Behavior |
|-------|------------------|
| `target_cph = 0` | ❌ ValueError: "target_cph must be positive: 0" |
| `target_cph = -10` | ❌ ValueError: "target_cph must be positive: -10" |
| `target_cph = 50` | ✅ Normal calculation |

### After Changes:

| Input | New Behavior |
|-------|--------------|
| `target_cph = 0` | ✅ Returns 0 (FTE) or 0.0 (Capacity) |
| `target_cph = -10` | ❌ ValueError: "target_cph cannot be negative: -10" |
| `target_cph = 50` | ✅ Normal calculation (unchanged) |

---

## Test Results

### Verification Script: `verify_target_cph_zero.py`

```
======================================================================
SUMMARY
======================================================================
  Tests passed: 4
  Tests failed: 0
======================================================================

✓ ALL TESTS PASSED

Conclusion:
  - target_cph = 0 is now allowed
  - FTE Required returns 0 when target_cph = 0
  - Capacity returns 0.0 when target_cph = 0
  - Normal calculations (target_cph > 0) still work
  - Negative target_cph is correctly rejected
```

### Test Cases Covered:

1. **✅ FTE Required with target_cph = 0**
   - Test 1: Normal forecast (10,000) → Returns 0
   - Test 2: Zero forecast → Returns 0
   - Test 3: Large forecast (100,000) → Returns 0

2. **✅ Capacity with target_cph = 0**
   - Test 1: Normal FTE (10) → Returns 0.0
   - Test 2: Zero FTE → Returns 0.0
   - Test 3: Large FTE (100) → Returns 0.0

3. **✅ Normal Calculations Still Work**
   - FTE Required with target_cph = 50 → Correct result
   - Capacity with target_cph = 50 → Correct result

4. **✅ Negative target_cph Rejected**
   - Both functions correctly reject negative values

---

## Example Scenarios

### Scenario 1: New Forecast Without Target CPH Set

**Input:**
```python
forecast = 10000
target_cph = 0  # Not configured yet
config = {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10}
```

**Result:**
```python
fte_required = calculate_fte_required(10000, config, 0)
# Returns: 0 (no staff needed without target)
```

---

### Scenario 2: Existing Allocation With Zero CPH

**Input:**
```python
fte_avail = 10
target_cph = 0  # Target disabled temporarily
config = {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10}
```

**Result:**
```python
capacity = calculate_capacity(10, config, 0)
# Returns: 0.0 (no capacity without target)
```

---

### Scenario 3: Normal Operation (Unchanged)

**Input:**
```python
forecast = 10000
fte_avail = 10
target_cph = 50.0
config = {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10}
```

**Result:**
```python
fte_required = calculate_fte_required(10000, config, 50.0)
# Returns: 2 (ceiling of 1.176)

capacity = calculate_capacity(10, config, 50.0)
# Returns: 85050.0 (10 * 21 * 9 * 0.90 * 50)
```

---

## Impact on Other Modules

All modules that use these functions will automatically benefit from the new behavior:

1. **✅ Primary Allocation** (`code/logics/allocation.py`)
   - Uses `calculate_fte_required()` and `calculate_capacity()`
   - Now handles target_cph = 0

2. **✅ Bench Allocation** (`code/logics/bench_allocation.py`)
   - Uses both calculation functions
   - Now handles target_cph = 0

3. **✅ CPH Updates** (`code/logics/cph_update_transformer.py`)
   - Uses both calculation functions
   - Now allows updating target_cph to 0

4. **✅ Edit View Operations** (`code/api/routers/edit_view_router.py`)
   - All preview/update operations
   - Now support target_cph = 0

---

## Database Implications

### ForecastModel Records

When `Centene_Capacity_Plan_Target_CPH = 0`:

**Before:**
- ❌ Calculations would fail with ValueError
- ❌ Allocation operations would crash

**After:**
- ✅ FTE Required automatically calculated as 0
- ✅ Capacity automatically calculated as 0.0
- ✅ Allocation operations complete successfully

---

## Backward Compatibility

### ✅ Fully Backward Compatible

- All existing calculations with `target_cph > 0` work exactly the same
- No changes to function signatures
- No changes to return types
- Existing database records unaffected

### Migration Notes

- No data migration needed
- Existing records with `target_cph > 0` continue to work
- Records can now have `target_cph = 0` without errors
- Simply restart server to pick up changes

---

## Edge Cases Handled

| Case | Behavior |
|------|----------|
| `forecast = 0, target_cph = 0` | ✅ Returns 0 |
| `forecast = 10000, target_cph = 0` | ✅ Returns 0 |
| `fte_avail = 0, target_cph = 0` | ✅ Returns 0.0 |
| `fte_avail = 10, target_cph = 0` | ✅ Returns 0.0 |
| `target_cph = -5` | ❌ ValueError (negative not allowed) |
| `target_cph = 0.001` | ✅ Normal calculation |

---

## Validation Rules

### FTE Required:
- ✅ `target_cph >= 0` (0 or positive)
- ❌ `target_cph < 0` (negative rejected)
- ✅ Returns 0 when `target_cph = 0`
- ✅ Returns 0 when `forecast = 0`

### Capacity:
- ✅ `target_cph >= 0` (0 or positive)
- ❌ `target_cph < 0` (negative rejected)
- ✅ Returns 0.0 when `target_cph = 0`
- ✅ Returns 0.0 when `fte_avail = 0`

---

## Testing Commands

### Run Verification Tests:
```bash
python3 verify_target_cph_zero.py
```

### Expected Output:
```
✓ ALL TESTS PASSED

Conclusion:
  - target_cph = 0 is now allowed
  - FTE Required returns 0 when target_cph = 0
  - Capacity returns 0.0 when target_cph = 0
  - Normal calculations (target_cph > 0) still work
  - Negative target_cph is correctly rejected
```

---

## Key Benefits

1. **✅ Flexibility**
   - Forecasts can exist without target CPH configured
   - Temporary disabling of targets supported

2. **✅ Stability**
   - No more ValueError crashes for zero CPH
   - Graceful handling of edge cases

3. **✅ Logical Consistency**
   - Zero target → Zero FTE needed
   - Zero target → Zero capacity
   - Makes business sense

4. **✅ Backward Compatible**
   - All existing functionality preserved
   - No breaking changes
   - Safe to deploy

---

## Deployment Steps

1. **Clear Python cache** (optional but recommended):
   ```bash
   find code -type d -name "__pycache__" -exec rm -rf {} +
   find code -name "*.pyc" -delete
   ```

2. **Restart server**:
   ```bash
   # Development
   python3 -m uvicorn code.main:app --reload

   # Production
   python3 -m uvicorn code.main:app --host 0.0.0.0 --port 8000
   ```

3. **Verify changes**:
   ```bash
   python3 verify_target_cph_zero.py
   ```

---

## Conclusion

Successfully updated capacity calculation functions to allow `target_cph = 0` with proper handling:

- ✅ **Validation updated** to accept 0 or positive values
- ✅ **Special case handling** returns 0 for zero CPH
- ✅ **Comprehensive tests** verify all scenarios
- ✅ **Backward compatible** with existing functionality
- ✅ **Documentation updated** with examples

The system now gracefully handles scenarios where Target CPH is not yet configured or is temporarily set to zero, returning appropriate zero values for FTE Required and Capacity.
