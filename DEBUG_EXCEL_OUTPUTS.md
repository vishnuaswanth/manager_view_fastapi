# Debug Excel Outputs - Quick Reference

## 📊 What Excel Files Are Generated?

When you run the allocation, **4 Excel files** are automatically created in `/code/logics/`:

| File | When | Purpose | Key Info |
|------|------|---------|----------|
| **buckets_debug.xlsx** | BEFORE allocation | Shows initial bucket structure | 2 sheets: Summary + Details |
| **buckets_after_allocation.xlsx** | AFTER allocation | Shows allocation results | Allocated vs Unallocated |
| **unmet_demand_report.xlsx** | AFTER allocation | Shows shortages | Platform/State/Month/Worktype |
| **unutilized_resources_report.xlsx** | AFTER allocation | Shows unused vendors | By Skills/States |

---

## 1️⃣ buckets_debug.xlsx (Initial State)

### **Sheet 1: Bucket_Summary**
Quick overview of all buckets.

```
Platform | Month | Skills              | Skill_Count | Vendor_Count | States_Available
---------|-------|---------------------|-------------|--------------|------------------
AMISYS   | March | ftc-basic/non mmp   | 1           | 5            | FL, GA, MI, N/A
AMISYS   | March | adj-basic/non mmp   | 1           | 3            | MI, N/A
FACETS   | April | ftc mcare           | 1           | 2            | N/A, TX
```

**Use this to:**
- ✅ Check total vendors per bucket
- ✅ Verify state mapping (N/A always present)
- ✅ Identify single-skill vs multi-skill

---

### **Sheet 2: Vendor_Details**
Every vendor, every bucket.

```
Platform | Month | Skills              | Vendor_ID | Vendor_States | Allocated
---------|-------|---------------------|-----------|---------------|----------
AMISYS   | March | ftc-basic/non mmp   | 0         | FL, GA, N/A   | False
AMISYS   | March | ftc-basic/non mmp   | 1         | MI, N/A       | False
AMISYS   | April | ftc-basic/non mmp   | 0         | FL, GA, N/A   | False
```

**Use this to:**
- ✅ Verify each vendor's StateList
- ✅ Check no duplicate vendor_id in same month-bucket
- ✅ Confirm N/A is always present

---

## 2️⃣ buckets_after_allocation.xlsx (Post-Allocation)

Shows what happened during allocation.

```
Platform | Month | Skills              | Total | Allocated | Unallocated | Rate | Allocated_States | Unallocated_States
---------|-------|---------------------|-------|-----------|-------------|------|------------------|-------------------
AMISYS   | March | ftc-basic/non mmp   | 5     | 3         | 2           | 3/5  | FL, GA           | MI, N/A
AMISYS   | March | adj-basic/non mmp   | 3     | 1         | 2           | 1/3  | MI               | N/A
FACETS   | April | ftc mcare           | 2     | 0         | 2           | 0/2  | -                | N/A, TX
```

**Use this to:**
- ✅ See utilization rate per bucket
- ✅ Find fully allocated buckets (Unallocated=0)
- ✅ Identify unutilized resources (Allocated=0)

---

## 3️⃣ unmet_demand_report.xlsx

Shows all allocation shortages.

```
Platform | State | Month | Worktype              | Requested | Allocated | Shortage
---------|-------|-------|-----------------------|-----------|-----------|----------
Amisys   | FL    | March | FTC-Basic/Non MMP     | 10        | 5         | 5
Facets   | TX    | April | FTC MCARE             | 3         | 0         | 3
```

**Use this to:**
- ✅ Identify where demand exceeds supply
- ✅ Know which skills need more vendors

---

## 4️⃣ unutilized_resources_report.xlsx

Shows unused vendor resources.

```
Platform | Month | Skills              | States       | Count
---------|-------|---------------------|--------------|-------
AMISYS   | March | adj-basic/non mmp   | MI, N/A      | 2
FACETS   | April | ftc mcare           | N/A, TX      | 2
```

**Use this to:**
- ✅ Find underutilized skills
- ✅ Identify vendors available for reallocation

---

## 🎯 Quick Debug Checklist

### **Step 1: Check Initial Buckets**
Open `buckets_debug.xlsx` → Bucket_Summary:

- [ ] Total Vendor_Count makes sense?
- [ ] All platforms normalized (UPPERCASE)?
- [ ] States_Available includes 'N/A'?

### **Step 2: Verify State Mapping**
Open `buckets_debug.xlsx` → Vendor_Details:

- [ ] Every row has 'N/A' in Vendor_States?
- [ ] Vendor "FL GA AR" shows ['FL', 'GA', 'N/A']?
- [ ] No duplicate Vendor_ID in same month-bucket?

### **Step 3: Check No Double-Counting**
Still in Vendor_Details:

- [ ] Filter by Month = "March"
- [ ] Count unique Vendor_ID values
- [ ] Does it match expected vendor count? (Not 3x inflated?)

### **Step 4: Verify Allocation**
Open `buckets_after_allocation.xlsx`:

- [ ] Allocated > 0 for high-demand skills?
- [ ] Sum of Allocated = total FTEs allocated?
- [ ] Unallocated resources identified?

### **Step 5: Cross-Check Reports**
Compare files:

- [ ] `unmet_demand_report.xlsx` shortages match low Unallocated in buckets?
- [ ] `unutilized_resources_report.xlsx` matches high Unallocated in buckets?

---

## 🔍 Common Issues to Look For

| Issue | Where to Check | What to Look For |
|-------|----------------|------------------|
| **Double-counting** | buckets_debug.xlsx → Vendor_Details | Same Vendor_ID appears 3x in same month-bucket |
| **Missing N/A** | buckets_debug.xlsx → Vendor_Details | Vendor_States doesn't include 'N/A' |
| **No allocation** | buckets_after_allocation.xlsx | All Allocated = 0 |
| **Wrong states** | buckets_debug.xlsx → Bucket_Summary | States_Available doesn't match vendor data |

---

## 📁 Where Are Files Saved?

```
/Users/aswanthvishnu/Projects/manager_view_fastapi/code/logics/

├── buckets_debug.xlsx                    ← Generated on initialization
├── buckets_after_allocation.xlsx         ← Generated after allocation
├── unmet_demand_report.xlsx              ← Generated after allocation
├── unutilized_resources_report.xlsx      ← Generated after allocation
└── result.xlsx                           ← Final consolidated output
```

---

## 💡 Pro Tips

1. **Pivot Tables**: Create pivot tables in buckets_debug.xlsx to summarize by Platform/Month
2. **Filters**: Use Excel filters on Vendor_ID to track individual vendors
3. **Compare**: Open both bucket files side-by-side to see before/after
4. **Formulas**: In buckets_after_allocation.xlsx, verify: `Total = Allocated + Unallocated`
5. **Search**: Use Ctrl+F to find specific platforms/skills/states

---

## 🚀 Example Usage

**Scenario:** "Why is FL state showing shortage but we have vendors?"

1. Open `unmet_demand_report.xlsx` → Note: FL / FTC-Basic/Non MMP has shortage
2. Open `buckets_after_allocation.xlsx` → Find: AMISYS / March / ftc-basic/non mmp
3. Check: Allocated=5, Unallocated=0 (fully utilized!)
4. Open `buckets_debug.xlsx` → Vendor_Details → Filter: Platform=AMISYS, Month=March, Skills=ftc-basic/non mmp
5. See: 5 vendors total, all had Vendor_States including 'FL'
6. **Conclusion:** All FL vendors were allocated, demand exceeded supply

---

## 📖 Full Documentation

See `BUCKET_DEBUG_EXPORTS.md` for complete details on:
- Column descriptions
- Use cases
- Troubleshooting
- Debug workflows
