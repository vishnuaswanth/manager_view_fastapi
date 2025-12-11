# State Mapping Logic - Visual Guide

## 📋 The Problem

Vendor data has multi-state strings and invalid codes that need intelligent mapping to buckets.

---

## ✅ The Solution: Smart State Mapping

### **Rule 1: Matched States → Specific Buckets**
States in vendor that match demand states go to specific buckets.

### **Rule 2: Unmatched States → N/A Bucket**
States in vendor that DON'T match demand get mapped to N/A bucket.

---

## 🎯 Example Walkthrough

### **Input:**

**Demand States:**
```
[FL, GA, MI, N/A]
```

**Vendor Data:**
| Vendor | Platform | State      | NewWorkType         |
|--------|----------|------------|---------------------|
| V1     | Amisys   | FL GA AR   | FTC-Basic/Non MMP   |
| V2     | Amisys   | MI         | ADJ-Basic/NON MMP   |
| V3     | Facets   | facets     | FTC MCARE           |
| V4     | Amisys   | AZ         | FTC-Basic/Non MMP   |

---

### **Processing:**

#### **Vendor V1: "FL GA AR"**
```
Split: [FL, GA, AR]

FL: ✅ Matches demand → Create bucket (AMISYS, FL, March)
GA: ✅ Matches demand → Create bucket (AMISYS, GA, March)
AR: ❌ Not in demand → Create bucket (AMISYS, N/A, March)
```

#### **Vendor V2: "MI"**
```
Split: [MI]

MI: ✅ Matches demand → Create bucket (AMISYS, MI, March)
```

#### **Vendor V3: "facets"**
```
Split: [facets]

facets: ❌ Invalid (not 2-letter) → Create bucket (FACETS, N/A, April)
```

#### **Vendor V4: "AZ"**
```
Split: [AZ]

AZ: ❌ Not in demand → Create bucket (AMISYS, N/A, March)
```

---

### **Result: Bucket Structure**

```python
buckets = {
    # Matched states - specific buckets
    ('AMISYS', 'FL', 'March'): {
        frozenset({'ftc-basic/non mmp'}): 1
    },
    ('AMISYS', 'GA', 'March'): {
        frozenset({'ftc-basic/non mmp'}): 1
    },
    ('AMISYS', 'MI', 'March'): {
        frozenset({'adj-basic/non mmp'}): 1
    },

    # Unmatched states - N/A bucket (consolidated)
    ('AMISYS', 'N/A', 'March'): {
        frozenset({'ftc-basic/non mmp'}): 2  # AR + AZ combined
    },
    ('FACETS', 'N/A', 'April'): {
        frozenset({'ftc mcare'}): 1  # facets
    }
}
```

---

## 🔍 Allocation Behavior

### **Scenario 1: Specific State Demand**
```python
# Demand: FL state
allocate('Amisys', 'FL', 'March', 'FTC-Basic/Non MMP', 5)

# Searches: ('AMISYS', 'FL', 'March') bucket only
# Finds: 1 FTE available
# Result: Allocated=1, Shortage=4
```

### **Scenario 2: N/A State Demand**
```python
# Demand: N/A state (any state acceptable)
allocate('Amisys', 'N/A', 'March', 'FTC-Basic/Non MMP', 5)

# Searches: ALL ('AMISYS', *, 'March') where * = any state
# Finds buckets:
#   - ('AMISYS', 'FL', 'March'): 1 FTE
#   - ('AMISYS', 'GA', 'March'): 1 FTE
#   - ('AMISYS', 'N/A', 'March'): 2 FTE (AR + AZ)
# Result: Allocated=4, Shortage=1
```

### **Scenario 3: Unmatched Vendor States Still Useful**
```python
# Vendor in AZ state doesn't match any specific demand
# But it's available in N/A bucket
# So demand with state=N/A can still access it!
```

---

## 📊 Summary Table

| Vendor State | Demand Has State? | Result Bucket State |
|--------------|-------------------|---------------------|
| FL           | ✅ Yes (FL)       | FL                  |
| GA           | ✅ Yes (GA)       | GA                  |
| MI           | ✅ Yes (MI)       | MI                  |
| AR           | ❌ No             | N/A                 |
| AZ           | ❌ No             | N/A                 |
| facets       | ❌ Invalid        | N/A                 |
| TX           | ❌ No             | N/A                 |

---

## 🎯 Benefits

1. **No Resources Lost**: Unmatched vendor states go to N/A bucket instead of being discarded
2. **Flexible Allocation**: N/A demands can access unmatched states
3. **Clean Separation**: Specific state demands only get their exact matches
4. **Invalid State Handling**: "facets", "Amisys", etc. treated as N/A

---

## 🧪 Test Output You Should See

```
State expansion: 4 → 6 records
  - 3 states matched demand (specific states)    ← FL, GA, MI
  - 2 valid codes unmapped → N/A                 ← AR, AZ
  - 1 invalid codes → N/A                        ← facets
Unique states in vendor data: ['FL', 'GA', 'MI', 'N/A']
```

This confirms:
- ✅ Matched states preserved
- ✅ Unmatched states mapped to N/A
- ✅ Invalid states handled gracefully
