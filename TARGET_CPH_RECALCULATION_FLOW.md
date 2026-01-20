# Target CPH Change - FTE Required & Capacity Recalculation Flow

## Overview

When Target CPH changes, both **FTE Required** and **Capacity** MUST be recalculated for all affected forecast rows. This document verifies that all CPH update operations correctly use centralized utility functions to ensure consistency.

---

## ✅ Complete Flow Verification

### 1. CPH Update Preview Operation

**File:** `code/logics/cph_update_transformer.py`

**Function:** `calculate_cph_preview()` (Lines 183-377)

#### Step-by-Step Flow:

1. **Receives CPH change request** (Lines 223-233)
   ```python
   actual_changes = [
       r for r in modified_cph_records
       if r['target_cph'] != r['modified_target_cph']
   ]
   ```

2. **Gets affected forecast records** (Lines 253-259)
   ```python
   forecast_records = session.query(ForecastModel).filter(
       ForecastModel.Centene_Capacity_Plan_Main_LOB == cph_record['lob'],
       ForecastModel.Centene_Capacity_Plan_Case_Type == cph_record['case_type']
   ).all()
   ```

3. **For EACH affected forecast row:**

   a. **Initializes tracking** (Line 263)
      ```python
      modified_fields = ["target_cph"]
      month_data = {}
      ```

   b. **For EACH of the 6 months:**

      i. **Gets current values** (Lines 271-290)
         - forecast (current month forecast)
         - old_fte_req (current FTE Required)
         - fte_avail (current FTE Available)
         - old_capacity (current Capacity)

      ii. **✅ RECALCULATES FTE Required using utility** (Line 297)
          ```python
          new_fte_req = calculate_fte_required(forecast, config, new_cph)
          ```
          - Uses centralized `calculate_fte_required()` function
          - Formula: `ceil(forecast / (working_days * work_hours * (1-shrinkage) * target_cph))`
          - Returns integer (ceiling applied)
          - Does NOT use occupancy

      iii. **✅ RECALCULATES Capacity using utility** (Line 300)
           ```python
           new_capacity = calculate_capacity(fte_avail, config, new_cph)
           ```
           - Uses centralized `calculate_capacity()` function
           - Formula: `fte_avail * working_days * work_hours * (1-shrinkage) * target_cph`
           - Returns float (rounded to 2 decimals)
           - Does NOT use occupancy

      iv. **Calculates changes** (Lines 303-304)
          ```python
          fte_req_change = new_fte_req - old_fte_req
          capacity_change = new_capacity - old_capacity
          ```

      v. **Creates month data response** (Lines 307-315)
         ```python
         month_data[month_label] = MonthDataResponse(
             forecast=int(forecast),
             fte_req=int(new_fte_req),        # NEW calculated value
             fte_req_change=int(fte_req_change),
             fte_avail=int(fte_avail),        # Unchanged
             fte_avail_change=0,
             capacity=int(new_capacity),      # NEW calculated value
             capacity_change=int(capacity_change)
         )
         ```

      vi. **Tracks modified fields** (Lines 318-333)
          ```python
          has_changes = (fte_req_change != 0 or capacity_change != 0)

          if has_changes:
              fields_to_add = [
                  f"{month_label}.forecast",
                  f"{month_label}.fte_req",      # ✅ Included
                  f"{month_label}.fte_avail",
                  f"{month_label}.capacity"      # ✅ Included
              ]
              for field in fields_to_add:
                  if field not in modified_fields:
                      modified_fields.append(field)
          ```

4. **Returns PreviewResponse** (Lines 367-376)
   - Includes all modified forecast records
   - Each record has recalculated FTE Required and Capacity for all 6 months
   - modified_fields lists: "target_cph", "Month.fte_req", "Month.capacity", etc.

---

### 2. CPH Update Database Operation

**File:** `code/logics/cph_update_transformer.py`

**Function:** `update_forecast_from_cph_changes()` (Lines 379-492)

#### Step-by-Step Flow:

1. **Receives CPH change request** (Lines 401-408)

2. **Gets affected forecast records** (Lines 425-438)

3. **For EACH CPH change:**

   a. **Updates Target_CPH** (Line 444)
      ```python
      forecast_row.Centene_Capacity_Plan_Target_CPH = new_cph
      ```

   b. **For ALL 6 months:**

      i. **Gets current values** (Lines 449-458)

      ii. **✅ RECALCULATES FTE Required using utility** (Line 463)
          ```python
          new_fte_req = calculate_fte_required(forecast, config, new_cph)
          ```

      iii. **✅ RECALCULATES Capacity using utility** (Line 466)
           ```python
           new_capacity = calculate_capacity(fte_avail, config, new_cph)
           ```

      iv. **✅ UPDATES database columns** (Lines 469-478)
          ```python
          setattr(
              forecast_row,
              get_forecast_column_name('fte_req', suffix),
              new_fte_req
          )
          setattr(
              forecast_row,
              get_forecast_column_name('capacity', suffix),
              new_capacity
          )
          ```

4. **Commits all updates** (Line 485)
   ```python
   session.commit()
   ```

---

### 3. Generic Forecast Updater

**File:** `code/logics/forecast_updater.py`

**Function:** `update_forecast_from_modified_records()` (Lines 21-175)

**Purpose:** Generic updater that applies pre-calculated changes from preview

#### Flow:

1. **Receives modified_records** from preview (already calculated)

2. **For each modified record:**

   a. **Finds forecast record in database** (Lines 94-112)

   b. **Applies changes from modified_fields** (Lines 120-165)
      - For month-specific fields (e.g., "Jun-25.fte_req"):
        - Extracts new value from month_data
        - Updates database column
      - For target_cph field:
        - Updates Centene_Capacity_Plan_Target_CPH

3. **Commits all updates** (Line 168)

**Important Note:**
- This updater applies values that were **already calculated** in the preview
- The preview used centralized utilities to calculate FTE Required and Capacity
- So the database receives correctly calculated values from the preview

---

## Complete Target CPH Change Flow

```
User changes Target CPH (45.0 → 50.0)
         ↓
┌─────────────────────────────────────────────────┐
│ 1. PREVIEW PHASE                                │
│    File: cph_update_transformer.py              │
└─────────────────────────────────────────────────┘
         ↓
    Get affected forecast records
         ↓
    For each forecast row:
      For each of 6 months:
         ↓
    ✅ calculate_fte_required(forecast, config, 50.0)
         ↓
    ✅ calculate_capacity(fte_avail, config, 50.0)
         ↓
    Build modified_fields list:
      - "target_cph"
      - "Jun-25.fte_req"
      - "Jun-25.capacity"
      - "Jul-25.fte_req"
      - "Jul-25.capacity"
      - ... (all 6 months)
         ↓
    Return PreviewResponse with:
      - New Target CPH: 50.0
      - New FTE Required for all months (calculated)
      - New Capacity for all months (calculated)
         ↓
┌─────────────────────────────────────────────────┐
│ 2. USER APPROVAL                                │
│    User reviews preview and approves            │
└─────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────┐
│ 3. UPDATE PHASE (Option A - Direct Update)     │
│    File: cph_update_transformer.py              │
└─────────────────────────────────────────────────┘
         ↓
    For each CPH change:
      Update Target_CPH = 50.0
         ↓
      For each of 6 months:
         ↓
    ✅ calculate_fte_required(forecast, config, 50.0)
         ↓
    ✅ calculate_capacity(fte_avail, config, 50.0)
         ↓
    Update database:
      - Centene_Capacity_Plan_Target_CPH = 50.0
      - FTE_Required_Month1 = new_fte_req
      - Capacity_Month1 = new_capacity
      - ... (all 6 months)
         ↓
    Commit to database
         ↓
┌─────────────────────────────────────────────────┐
│ 3. UPDATE PHASE (Option B - Generic Updater)   │
│    File: forecast_updater.py                    │
└─────────────────────────────────────────────────┘
         ↓
    Receives pre-calculated values from preview
         ↓
    For each modified_field:
      - "target_cph" → Update Target_CPH
      - "Jun-25.fte_req" → Update FTE_Required_Month1
      - "Jun-25.capacity" → Update Capacity_Month1
      - ... (all fields in modified_fields)
         ↓
    Commit to database
         ↓
┌─────────────────────────────────────────────────┐
│ 4. HISTORY LOG                                  │
│    Tracks all changes with before/after values  │
└─────────────────────────────────────────────────┘
```

---

## Verification Summary

### ✅ All Target CPH changes trigger recalculations

| Operation | Location | Uses Utilities | Recalculates FTE | Recalculates Capacity |
|-----------|----------|----------------|------------------|---------------------|
| **CPH Preview** | cph_update_transformer.py:297 | ✅ Yes | ✅ Yes | ✅ Yes |
| **CPH Update (Direct)** | cph_update_transformer.py:463 | ✅ Yes | ✅ Yes | ✅ Yes |
| **CPH Update (Generic)** | forecast_updater.py:161 | ✅ Yes* | ✅ Yes* | ✅ Yes* |

*Generic updater applies pre-calculated values from preview, which used utilities

---

## Formula Consistency

**When Target CPH changes from 45.0 to 50.0:**

### FTE Required Recalculation:
```python
# OLD CPH (45.0)
old_fte_req = ceil(forecast / (working_days * work_hours * (1-shrinkage) * 45.0))

# NEW CPH (50.0)
new_fte_req = ceil(forecast / (working_days * work_hours * (1-shrinkage) * 50.0))

# Result: new_fte_req will be LOWER (higher CPH = fewer FTE needed)
```

### Capacity Recalculation:
```python
# OLD CPH (45.0)
old_capacity = fte_avail * working_days * work_hours * (1-shrinkage) * 45.0

# NEW CPH (50.0)
new_capacity = fte_avail * working_days * work_hours * (1-shrinkage) * 50.0

# Result: new_capacity will be HIGHER (higher CPH = more cases processed)
```

---

## Example Calculation

**Scenario:** Target CPH changes from 45.0 to 50.0

**Given:**
- Forecast: 10,000 cases
- FTE Available: 10
- Working Days: 21
- Work Hours: 9
- Shrinkage: 0.10

**FTE Required:**
```
Old: ceil(10000 / (21 * 9 * 0.90 * 45)) = ceil(1.31) = 2 FTE
New: ceil(10000 / (21 * 9 * 0.90 * 50)) = ceil(1.18) = 2 FTE
Change: 0 FTE (both round to 2 in this case)
```

**Capacity:**
```
Old: 10 * 21 * 9 * 0.90 * 45 = 76,545
New: 10 * 21 * 9 * 0.90 * 50 = 85,050
Change: +8,505 (11% increase)
```

---

## Key Verification Points

### ✅ Centralized Utilities Used

**Both functions are imported and used:**
```python
from code.logics.capacity_calculations import calculate_fte_required, calculate_capacity
```

**Locations:**
1. ✅ `cph_update_transformer.py` Line 18 (import)
2. ✅ `cph_update_transformer.py` Line 297 (preview - FTE)
3. ✅ `cph_update_transformer.py` Line 300 (preview - Capacity)
4. ✅ `cph_update_transformer.py` Line 463 (update - FTE)
5. ✅ `cph_update_transformer.py` Line 466 (update - Capacity)

### ✅ No Inline Calculations

**Verified no inline formulas in CPH update code:**
- ✅ No manual division for FTE Required
- ✅ No manual multiplication for Capacity
- ✅ All calculations use centralized utilities

### ✅ Formula Consistency

**Both operations use identical formulas:**
- ✅ Preview and Update use same utilities
- ✅ FTE Required: Always ceiling function
- ✅ Capacity: Always rounded to 2 decimals
- ✅ Neither uses occupancy

### ✅ All 6 Months Updated

**When Target CPH changes:**
- ✅ FTE Required recalculated for Month1 through Month6
- ✅ Capacity recalculated for Month1 through Month6
- ✅ modified_fields includes all affected months
- ✅ Database updated for all 6 months

---

## Test Verification

**Run test to verify CPH changes:**
```bash
python3 verify_all_calculations.py
```

**Expected results:**
- ✅ FTE Required calculation: PASS
- ✅ Capacity calculation: PASS
- ✅ Formula consistency: PASS
- ✅ Occupancy exclusion: PASS

---

## Conclusion

✅ **VERIFIED: All Target CPH changes correctly trigger FTE Required and Capacity recalculations**

**Key Findings:**
1. ✅ All CPH update operations use centralized utility functions
2. ✅ Both preview and actual update recalculate FTE Required and Capacity
3. ✅ All 6 months are updated when Target CPH changes
4. ✅ No inline calculations found - all use utilities
5. ✅ Formula consistency maintained across all operations
6. ✅ Occupancy correctly excluded from all calculations

**Summary:**
- When Target CPH changes, the system **automatically recalculates** both FTE Required and Capacity for all affected forecast rows
- All recalculations use the **centralized utility functions**
- The flow ensures **consistency** between preview and actual database updates
- **No manual calculations** exist - all use standardized formulas

The system is working correctly! 🎉
