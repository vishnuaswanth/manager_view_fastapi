# Allocation Debug Guide

## How to Run the Debug Test

```bash
cd /Users/aswanthvishnu/Projects/manager_view_fastapi
python test_allocation_debug.py
```

Or run directly:
```bash
python code/logics/allocation.py
```

## State Mapping Logic (IMPORTANT!)

The allocator now uses **smart state mapping** to handle unmatched vendor states:

### **Example:**
- **Demand states:** [FL, GA, MI, N/A]
- **Vendor state:** "FL GA AR"

### **What happens:**
1. Split into individual states: FL, GA, AR
2. Map each state:
   - **FL** → matches demand → create **FL bucket**
   - **GA** → matches demand → create **GA bucket**
   - **AR** → doesn't match demand → create **N/A bucket**

### **Result:**
- Specific state demands (FL, GA, MI) → can access their specific buckets
- N/A state demands → can access **all N/A buckets** (includes unmapped states like AR, AZ, invalid codes like "facets")

---

## What to Look For in the Logs

### 1. **Initialization Phase**
```
Valid states from demand: ['FL', 'GA', 'MI', 'N/A']
Built vocabulary with 3 unique worktypes
Sample worktypes: ['ftc-basic/non mmp', 'adj-basic/non mmp', 'ftc mcare']
State expansion: 4 → 6 records
  - 3 states matched demand (specific states)
  - 2 valid codes unmapped → N/A
  - 1 invalid codes → N/A
Unique states in vendor data: ['FL', 'GA', 'MI', 'N/A']
Sample vendor PrimaryPlatform: ['Amisys CROP', 'amisys', 'Facets', 'Amisys']
Sample vendor PlatformNormalized: ['AMISYS', 'AMISYS', 'FACETS', 'AMISYS']
Sample vendor NewWorkType: ['FTC-Basic/Non MMP', 'ADJ-Basic/NON MMP', 'FTC MCARE', 'FTC-Basic/Non MMP']
Sample ParsedSkills: [frozenset({'ftc-basic/non mmp'}), frozenset({'adj-basic/non mmp'}), frozenset({'ftc mcare'}), frozenset({'ftc-basic/non mmp'})]
Filtered vendors: 6 → 6 (removed 0 with no recognized skills)
```

**What this verifies:**
✅ State expansion working ("FL GA AR" → FL, GA, N/A records)
✅ Matched states go to specific buckets (FL, GA, MI)
✅ Unmatched valid codes → N/A bucket (AR, AZ)
✅ Invalid states → N/A bucket (facets)
✅ Platform normalization (both "Amisys CROP" and "amisys" → "AMISYS")
✅ Vocabulary built from demand
✅ Vendor skills parsed correctly

---

### 2. **Allocation Requests (First 5 shown in detail)**
```
ALLOCATE REQUEST: platform='Amisys CROP' (normalized: 'AMISYS'),
                  state='MI' (normalized: 'MI'),
                  month='March' (normalized: 'March'),
                  worktype='FTC-Basic/Non MMP' (normalized: 'ftc-basic/non mmp'),
                  fte_required=5
  Exact state match: [('AMISYS', 'MI', 'March')]
  Priority 1: Looking for single-skill match frozenset({'ftc-basic/non mmp'})
    ✓ Allocated 1 from single-skill match at ('AMISYS', 'MI', 'March')
  RESULT: Allocated 1/5, Shortage: 4
```

**What this verifies:**
✅ Case-insensitive platform matching ("Amisys CROP" → "AMISYS")
✅ Case-insensitive state matching ("MI" → "MI", "mi" → "MI")
✅ Case-insensitive month matching ("March" → "March", "march" → "March")
✅ Case-insensitive worktype matching (all lowercase)
✅ Bucket lookup working
✅ Allocation priority (single-skill first)

---

### 3. **N/A State Allocation**
```
ALLOCATE REQUEST: platform='Facets Global' (normalized: 'FACETS'),
                  state='N/A' (normalized: 'N/A'),
                  month='April' (normalized: 'April'),
                  worktype='FTC MCARE' (normalized: 'ftc mcare'),
                  fte_required=2
  N/A state: searching 1 state buckets
  Priority 1: Looking for single-skill match frozenset({'ftc mcare'})
    ✓ Allocated 1 from single-skill match at ('FACETS', 'TX', 'April')
  RESULT: Allocated 1/2, Shortage: 1
```

**What this verifies:**
✅ N/A state searches across ALL states
✅ Found resources in TX state even though demand was "N/A"

---

### 4. **No Matching Buckets (if applicable)**
```
  No matching buckets found! Available bucket keys (first 5): [('AMISYS', 'MI', 'March'), ...]
```

**What this indicates:**
❌ Platform/state/month combination not found in vendor data
→ Check if platform names match between demand and vendor
→ Check if states are valid 2-letter codes
→ Check if month names match

---

## Common Issues & Solutions

### Issue: "Filtered vendors: X → 0 (removed X with no recognized skills)"
**Problem:** No vendor NewWorkType values matched the vocabulary
**Solution:**
- Check if vendor NewWorkType values contain the exact worktypes from demand
- Check if worktypes are lowercase matched correctly
- Verify vocabulary is built from demand data

---

### Issue: "No matching buckets found!"
**Problem:** Platform/state/month combination doesn't exist in buckets
**Solution:**
- Check platform normalization (first word only, uppercase)
- Check state is valid 2-letter code
- Check month is title case ("March" not "march" or "MARCH")
- Look at "Available bucket keys" to see what exists

---

### Issue: "Allocated 0/X, Shortage: X"
**Problem:** Resources exist but skills don't match
**Solution:**
- Check worktype parsing (see "Sample ParsedSkills")
- Verify demand worktype exists in vendor NewWorkType
- Check for typos or extra spaces in worktypes

---

## Running Full Allocation

Once debug test passes, update `allocation.py` line 1349:

```python
if __name__ == "__main__":
    # Run full processing
    process_files('March', 2025, 'Makzoom Shah', 'NTT Forecast - v4_Capacity and HC_March_2025.xlsx')
```

This will show the same debug logs for real data.
