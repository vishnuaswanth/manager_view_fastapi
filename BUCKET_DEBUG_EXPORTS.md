# Bucket Debug Excel Exports

## Overview

Two Excel files are automatically generated for debugging bucket structure:

1. **`buckets_debug.xlsx`** - Generated BEFORE allocation (shows initial state)
2. **`buckets_after_allocation.xlsx`** - Generated AFTER allocation (shows what was allocated)

Both files are saved to: `/code/logics/`

---

## 1. buckets_debug.xlsx

**When:** Generated immediately after bucket initialization, before any allocation.

**Purpose:** Shows the initial structure of all buckets with vendor details.

### **Sheet 1: Bucket_Summary**

Overview of all buckets with counts.

| Column | Description | Example |
|--------|-------------|---------|
| Platform | Normalized platform name | AMISYS |
| Month | Month name | March |
| Skills | Skillset (+ separated for multi-skill) | ftc-basic/non mmp |
| Skill_Count | Number of skills (1=single, 2+=multi) | 1 |
| Vendor_Count | Total vendors in this bucket | 5 |
| States_Available | All unique states from vendors | FL, GA, MI, N/A |

**Example Rows:**
```
Platform  Month  Skills                 Skill_Count  Vendor_Count  States_Available
AMISYS    March  ftc-basic/non mmp      1            5             FL, GA, MI, N/A
AMISYS    March  adj-basic/non mmp      1            3             MI, N/A
FACETS    April  ftc mcare              1            2             N/A, TX
AMISYS    March  adj + ftc-basic        2            1             FL, GA, N/A
```

**Insights:**
- ✅ See total vendors available per skill/platform/month
- ✅ Identify single-skill vs multi-skill buckets
- ✅ Check which states are available for each bucket

---

### **Sheet 2: Vendor_Details**

Full details for every vendor in every bucket.

| Column | Description | Example |
|--------|-------------|---------|
| Platform | Normalized platform name | AMISYS |
| Month | Month name | March |
| Skills | Skillset | ftc-basic/non mmp |
| Vendor_ID | Unique vendor identifier | 0 |
| Vendor_States | States vendor can work in | FL, GA, N/A |
| Allocated | Whether vendor is allocated | False |

**Example Rows:**
```
Platform  Month  Skills                 Vendor_ID  Vendor_States  Allocated
AMISYS    March  ftc-basic/non mmp      0          FL, GA, N/A    False
AMISYS    March  ftc-basic/non mmp      1          MI, N/A        False
AMISYS    March  ftc-basic/non mmp      2          FL, GA, N/A    False
AMISYS    April  ftc-basic/non mmp      0          FL, GA, N/A    False
AMISYS    April  ftc-basic/non mmp      1          MI, N/A        False
```

**Insights:**
- ✅ See each vendor's state list
- ✅ Verify no duplicate vendor_ids within same month
- ✅ Check N/A is always present in Vendor_States
- ✅ Initial Allocated = False for all vendors

---

## 2. buckets_after_allocation.xlsx

**When:** Generated after all allocation is complete.

**Purpose:** Shows which vendors were allocated and which remain available.

### **Single Sheet: Allocation Summary**

| Column | Description | Example |
|--------|-------------|---------|
| Platform | Normalized platform name | AMISYS |
| Month | Month name | March |
| Skills | Skillset | ftc-basic/non mmp |
| Skill_Count | Number of skills | 1 |
| Total_Vendors | Total vendors in bucket | 5 |
| Allocated | Number allocated | 3 |
| Unallocated | Number still available | 2 |
| Allocation_Rate | Allocated/Total | 3/5 |
| Allocated_States | States from allocated vendors | FL, GA |
| Unallocated_States | States from unallocated vendors | MI, N/A |

**Example Rows:**
```
Platform  Month  Skills                 Total  Allocated  Unallocated  Rate  Allocated_States  Unallocated_States
AMISYS    March  ftc-basic/non mmp      5      3          2            3/5   FL, GA            MI, N/A
AMISYS    March  adj-basic/non mmp      3      1          2            1/3   MI                N/A
FACETS    April  ftc mcare              2      0          2            0/2   -                 N/A, TX
AMISYS    March  adj + ftc-basic        1      1          0            1/1   FL, GA, N/A       -
```

**Insights:**
- ✅ See utilization rate per bucket
- ✅ Identify fully allocated buckets (Unallocated=0)
- ✅ Find unutilized resources (Allocated=0)
- ✅ Check which states were allocated vs still available

---

## How to Use These Files

### **1. Verify Initial Bucket Structure**

Open `buckets_debug.xlsx` → Bucket_Summary sheet:

**Check:**
- ✅ Total vendor count matches expected number
- ✅ All platforms are normalized (uppercase)
- ✅ Skills are parsed correctly (no raw vendor data)
- ✅ Multi-skill vendors have Skill_Count > 1

---

### **2. Verify State Mapping**

Open `buckets_debug.xlsx` → Vendor_Details sheet:

**Check:**
- ✅ Every vendor has 'N/A' in Vendor_States
- ✅ Vendors with "FL GA AR" show: ['FL', 'GA', 'N/A'] (AR ignored if not in demand)
- ✅ Invalid states like "facets" show only: ['N/A']
- ✅ No duplicate vendor_id within same month-bucket

**Filter by Vendor_ID:**
```
Vendor_ID = 0
Shows all months where this vendor appears
```

---

### **3. Verify No Double-Counting**

Open `buckets_debug.xlsx` → Vendor_Details sheet:

**Count unique Vendor_IDs per month:**
```
Filter: Month = "March"
Count unique Vendor_ID values

This should equal total unique vendors (not 3x if vendor has 3 states!)
```

**Check:**
- ✅ Vendor_ID=0 appears in multiple buckets (different skills/months) ← OK
- ✅ Vendor_ID=0 does NOT appear 3 times in SAME month/skill bucket ← Would be bug!

---

### **4. Verify Allocation Results**

Open `buckets_after_allocation.xlsx`:

**Check:**
- ✅ High-demand skills show high Allocation_Rate
- ✅ Allocated > 0 for buckets that match demand
- ✅ Unallocated > 0 for skills not fully utilized
- ✅ Sum of Allocated across all rows = total allocated FTEs

**Compare with Unmet Demand Report:**
```
If "FL / FTC-Basic/Non MMP" has shortage in unmet_demand_report.xlsx
→ buckets_after_allocation.xlsx should show Unallocated=0 for that bucket
```

---

### **5. Find Unutilized Resources**

Open `buckets_after_allocation.xlsx`:

**Filter:**
- Unallocated > 0
- Sort by: Unallocated (descending)

**Result:** Shows which skills/platforms/months have unused vendors

---

## Common Issues to Look For

### ❌ **Issue 1: Vendor Appears 3 Times in Same Bucket**

**Symptom:**
```
Bucket_Details shows:
Platform  Month  Skills            Vendor_ID  States
AMISYS    March  ftc-basic/non mmp 0          FL, GA, N/A
AMISYS    March  ftc-basic/non mmp 0          FL, GA, N/A  ← Duplicate!
AMISYS    March  ftc-basic/non mmp 0          FL, GA, N/A  ← Duplicate!
```

**Problem:** Double-counting bug - vendor counted 3 times!

**Fix:** Check state expansion logic in `_clean_and_expand_vendor_states()`

---

### ❌ **Issue 2: Vendor Missing 'N/A' in StateList**

**Symptom:**
```
Vendor_States: "FL, GA"  ← Missing N/A!
```

**Problem:** Vendor won't be available for N/A demands

**Fix:** Check that N/A is always added in `parse_states()`

---

### ❌ **Issue 3: Total_Vendors Doesn't Match**

**Symptom:**
```
buckets_debug.xlsx → Summary: Total across all buckets = 500
Vendor data: Only 100 unique vendors

Expected: 100 vendors × 2 months = 200 (not 500!)
```

**Problem:** Vendors being triple-counted due to state expansion

**Fix:** Use vendor lists, not state-expanded records

---

### ❌ **Issue 4: All Allocated=False After Allocation**

**Symptom:**
```
buckets_after_allocation.xlsx shows:
Allocated = 0 for all rows
```

**Problem:** Allocation logic not marking vendors as allocated

**Fix:** Check `vendor['allocated'] = True` is being set in `_allocate_from_vendor_list()`

---

## Quick Debug Workflow

1. **Run allocation** → generates both Excel files
2. **Open `buckets_debug.xlsx`** → Check Bucket_Summary
   - ✅ Vendor counts look reasonable?
   - ✅ States_Available includes N/A?
3. **Open Vendor_Details sheet** → Pick a Vendor_ID
   - ✅ Appears once per month-skillset combination?
   - ✅ Has N/A in Vendor_States?
4. **Open `buckets_after_allocation.xlsx`**
   - ✅ Allocated > 0 for demanded skills?
   - ✅ Unallocated shows remaining resources?
5. **Compare with reports:**
   - `unmet_demand_report.xlsx` ← Shortages
   - `unutilized_resources_report.xlsx` ← Unused vendors

---

## Files Location

```
/Users/aswanthvishnu/Projects/manager_view_fastapi/
└── code/
    └── logics/
        ├── buckets_debug.xlsx              ← Initial buckets
        ├── buckets_after_allocation.xlsx   ← Post-allocation
        ├── unmet_demand_report.xlsx        ← Shortages
        └── unutilized_resources_report.xlsx ← Unused resources
```

All files regenerated on each run!
