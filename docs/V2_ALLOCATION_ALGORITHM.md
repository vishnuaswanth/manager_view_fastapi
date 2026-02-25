# V2 Fair Allocation Algorithm - Detailed Design

## Executive Summary

This document describes a **fair, optimized allocation algorithm** for V2 that:
- Distributes resources proportionally across all LOBs and case types
- Handles multi-skilled, multi-state resources without over-allocation
- Uses O(n log n) time complexity with O(n) space
- Processes weekly allocations in milliseconds

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Algorithm Overview](#2-algorithm-overview)
3. [Data Structures](#3-data-structures)
4. [Eligibility Gate (Misfit Prevention)](#4-eligibility-gate-misfit-prevention)
5. [Ideal FTE Calculation](#5-ideal-fte-calculation)
6. [Allocation Phases](#6-allocation-phases)
7. [Detailed Flowcharts](#7-detailed-flowcharts)
8. [Complexity Analysis](#8-complexity-analysis)
9. [Memory Optimization](#9-memory-optimization)
10. [Implementation Plan](#10-implementation-plan)

---

## 1. Problem Statement

### Current Issues (V1)
```
Problem: Greedy Sequential Allocation

Demands processed in order:
  D1: FL FTC (Forecast: 1000) → Gets 10 resources ✓
  D2: GA FTC (Forecast: 800)  → Gets 5 resources (shortage!)
  D3: FL ADJ (Forecast: 600)  → Gets 2 resources (critical shortage!)

Result: First demands over-allocated, later demands starved
```

### V2 Goal
```
Fair Proportional Allocation

Total Resources: 17
Total Forecast: 2400

Fair Distribution:
  D1: FL FTC → 1000/2400 × 17 = 7.08 → 7 resources
  D2: GA FTC → 800/2400 × 17 = 5.67  → 6 resources
  D3: FL ADJ → 600/2400 × 17 = 4.25  → 4 resources

Result: Each demand gets proportional share
```

---

## 2. Algorithm Overview

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    V2 WEEKLY ALLOCATION                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PHASE 0: INITIALIZATION (O(n))                                │
│  ├── Load resources into indexed structures                     │
│  ├── Load demands with forecast data                           │
│  └── Build skill vocabulary and state mappings                 │
│                                                                 │
│  PHASE 1: CALCULATE IDEAL FTE (O(d))                           │
│  ├── Sum total forecast across all demands                     │
│  ├── Calculate proportional target for each demand             │
│  └── Track current allocation vs ideal                         │
│                                                                 │
│  PHASE 2: EXCLUSIVE ALLOCATION (O(r × d))                      │
│  ├── Identify single-option resources                          │
│  ├── Allocate to their only matching demand                    │
│  └── Update demand gaps                                        │
│                                                                 │
│  PHASE 3: SCORED ALLOCATION (O(r × d × log d))                 │
│  ├── Score each resource-demand pair                           │
│  ├── Use priority queue for best matches                       │
│  └── Allocate highest-scoring pairs first                      │
│                                                                 │
│  PHASE 4: REMAINDER DISTRIBUTION (O(d log d))                  │
│  ├── Apply Largest Remainder Method                            │
│  └── Distribute any remaining resources fairly                 │
│                                                                 │
│  PHASE 5: VALIDATION & PERSIST (O(n))                          │
│  ├── Validate no over-allocation                               │
│  └── Persist assignments to database                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Structures

### 3.1 Resource Index (Hash-based O(1) lookup)

```python
@dataclass
class ResourceIndex:
    """Pre-computed indices for O(1) resource lookup"""

    # Primary index: CN → Resource
    by_cn: Dict[str, Resource]

    # Skill index: skill → Set[CN]
    by_skill: Dict[str, Set[str]]

    # State index: state → Set[CN]
    by_state: Dict[str, Set[str]]

    # Platform index: platform → Set[CN]
    by_platform: Dict[str, Set[str]]

    # Combined index: (platform, skill) → Set[CN]
    by_platform_skill: Dict[Tuple[str, str], Set[str]]

    # Availability index: week_number → Set[CN]
    by_week_available: Dict[int, Set[str]]
```

**Memory:** O(r × s) where r = resources, s = avg skills per resource

### 3.2 Demand Structure

```python
@dataclass
class DemandTarget:
    """Demand with allocation tracking"""

    demand_id: int
    platform: str
    state: str
    case_type: str  # skill required

    # V2: Locality - derived from main_lob using dynamic policy
    locality: str  # "Domestic" or "Global"
    main_lob: str  # Original main_lob for reference

    # Forecast data
    forecast: int

    # Allocation tracking
    ideal_fte: float        # Calculated proportional target
    current_fte: int        # Currently allocated
    gap: float              # ideal_fte - current_fte

    # For scoring
    exclusive_resources: int  # Resources that can ONLY serve this demand
    total_eligible: int       # All resources that CAN serve this demand
```

### 3.3 Allocation Score Entry (Priority Queue)

```python
@dataclass(order=True)
class AllocationScore:
    """Sortable score for priority queue"""

    score: float  # Primary sort key (higher = better)
    resource_cn: str = field(compare=False)
    demand_id: int = field(compare=False)

    # Score components (for debugging)
    urgency_score: float = field(compare=False)
    exclusivity_score: float = field(compare=False)
    state_score: float = field(compare=False)
```

### 3.4 Allocation State (Week-level tracking)

```python
@dataclass
class WeekAllocationState:
    """Tracks allocation state for a single week"""

    year: int
    week_number: int

    # Allocated tracking
    allocated_resources: Set[str]  # Set of CNs allocated this week

    # Demand state
    demands: Dict[int, DemandTarget]

    # Statistics
    total_allocated: int
    total_available: int
```

### 3.5 Locality Policy System (Dynamic Configuration)

**V2 introduces dynamic locality determination** via configurable policy rules stored in the database.

#### Purpose

Locality (Domestic/Global) determines:
- Which working days calendar to use (Domestic vs Global holidays)
- Month configuration parameters (shrinkage, occupancy rates differ by location)
- Resource eligibility (some resources work only Domestic or Global)

#### Database Model: `LocalityParsingPolicyModel`

```python
class LocalityParsingPolicyModel(SQLModel, table=True):
    """
    Dynamic policy rules for determining Locality from Main_LOB.

    Rules evaluated in priority order (lowest number = highest priority).
    """
    __tablename__ = "locality_parsing_policy"

    id: int
    rule_name: str          # Unique identifier (e.g., 'domestic_keyword')
    pattern: str            # Pattern to match (e.g., 'domestic')
    match_type: str         # 'contains', 'exact', 'regex', 'startswith', 'endswith'
    result_locality: str    # 'Domestic', 'Global', or NULL (use fallback)
    fallback_field: str     # Field to check if result_locality is NULL (e.g., 'worktype')
    fallback_pattern: str   # Pattern in fallback field for Domestic (else Global)
    priority: int           # Lower = higher priority (default: 100)
    is_active: bool         # Toggle rule on/off
```

#### Default Rules (Seeded at Startup)

| Priority | Rule Name | Pattern | Match Type | Result |
|----------|-----------|---------|------------|--------|
| 5 | `oic_volumes_special` | "OIC Volumes" | contains | NULL (fallback to worktype) |
| 10 | `domestic_keyword` | "domestic" | contains | Domestic |
| 10 | `global_keyword` | "global" | contains | Global |
| 15 | `domestic_parens` | "(domestic)" | contains | Domestic |
| 15 | `global_parens` | "(global)" | contains | Global |
| 20 | `onshore_keyword` | "onshore" | contains | Domestic |
| 20 | `offshore_keyword` | "offshore" | contains | Global |

#### Usage Example

```python
from code.logics.locality_policy_utils import get_locality_from_main_lob

# Standard case: keyword in main_lob
locality = get_locality_from_main_lob("Amisys Medicaid Domestic")
# Returns: "Domestic"

# Special case: OIC Volumes - check worktype field
locality = get_locality_from_main_lob(
    main_lob="OIC Volumes",
    worktype="COB Domestic"
)
# Returns: "Domestic" (found 'domestic' in worktype)

# Unknown LOB - returns default
locality = get_locality_from_main_lob("Unknown LOB")
# Returns: "Global" (default)
```

#### Extending Rules

To add new locality patterns, insert into `locality_parsing_policy` table:

```sql
INSERT INTO locality_parsing_policy
    (rule_name, pattern, match_type, result_locality, priority, is_active, CreatedBy, UpdatedBy)
VALUES
    ('nearshore_keyword', 'nearshore', 'contains', 'Global', 25, true, 'admin', 'admin');
```

Rules are cached in memory and automatically reloaded when modified via API.

---

## 4. Eligibility Gate (Misfit Prevention)

### 4.1 Purpose

The **Eligibility Gate** is a critical pre-scoring filter that guarantees only valid resource-demand pairs are ever considered for allocation. This prevents misfit allocations such as:

- A Facets resource being allocated to an Amisys demand
- A resource without FTC-Basic skill being allocated to an FTC-Basic demand
- A resource who only works in FL being allocated to a TX demand

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        ELIGIBILITY GATE                                  │
│                                                                          │
│  Purpose: ONLY allow valid (resource, demand) pairs to be scored        │
│                                                                          │
│  Guarantees:                                                             │
│  ✓ Platform match (Amisys resource → Amisys demand)                     │
│  ✓ Skill match (resource has required case_type)                        │
│  ✓ State compatibility (resource can work in demand's state)            │
│                                                                          │
│  Result: Zero misfit allocations possible                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Eligibility Checks

The gate performs **three mandatory checks** for each (resource, demand) pair:

| Check | Rule | Example Pass | Example Fail |
|-------|------|--------------|--------------|
| **Platform** | `resource.platform == demand.platform` | Amisys → Amisys ✓ | Amisys → Facets ✗ |
| **Skill** | `demand.case_type in resource.skills` | {FTC,ADJ} has FTC ✓ | {ADJ} has FTC ✗ |
| **State** | `demand.state in resource.state_list OR 'N/A' in resource.state_list` | FL in {FL,GA} ✓ | TX in {FL,GA} ✗ |

### 4.3 Implementation

```python
def compute_eligibility_matrix(resources: List[Resource],
                                demands: List[DemandTarget],
                                resource_index: ResourceIndex) -> SparseEligibility:
    """
    Build sparse eligibility matrix - ONLY valid pairs stored.

    This is the FIRST step before any scoring happens.
    Invalid pairs are NEVER added to the matrix.

    Time: O(r × d) where r=resources, d=demands
    Space: O(eligible_pairs) - much less than r×d for sparse matches
    """

    eligibility = SparseEligibility()

    for demand in demands:
        for resource in resources:

            # ══════════════════════════════════════════════════════════
            # CHECK 1: PLATFORM MUST MATCH
            # ══════════════════════════════════════════════════════════
            if resource.platform != demand.platform:
                continue  # REJECT - platform mismatch

            # ══════════════════════════════════════════════════════════
            # CHECK 2: SKILL MUST MATCH
            # ══════════════════════════════════════════════════════════
            if demand.case_type not in resource.skills:
                continue  # REJECT - missing required skill

            # ══════════════════════════════════════════════════════════
            # CHECK 3: STATE MUST BE COMPATIBLE
            # ══════════════════════════════════════════════════════════
            if not is_state_compatible(demand.state, resource.state_list):
                continue  # REJECT - state incompatible

            # ══════════════════════════════════════════════════════════
            # ALL THREE CHECKS PASSED - Add to eligibility matrix
            # ══════════════════════════════════════════════════════════
            eligibility.add(resource.cn, demand.demand_id)

    return eligibility


def is_state_compatible(demand_state: str, resource_states: Set[str]) -> bool:
    """
    Check if resource can work in demand's state.

    Rules:
    1. Exact match: demand_state in resource_states
    2. N/A fallback: 'N/A' in resource_states (can work anywhere)
    3. Otherwise: incompatible

    Examples:
      is_state_compatible('FL', {'FL', 'GA'}) → True (exact match)
      is_state_compatible('TX', {'FL', 'GA'}) → False (no match)
      is_state_compatible('TX', {'N/A'}) → True (N/A works anywhere)
      is_state_compatible('FL', {'N/A', 'FL'}) → True (exact match)
    """

    # Check 1: Exact state match
    if demand_state in resource_states:
        return True

    # Check 2: N/A fallback (resource can work in any state)
    if 'N/A' in resource_states:
        return True

    # No match
    return False
```

### 4.4 Eligibility Gate Flowchart

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    ELIGIBILITY GATE FLOW                                 │
└─────────────────────────────────────────────────────────────────────────┘

For each (Resource R, Demand D) pair:

                    ┌───────────────────────────────┐
                    │  START: Check Eligibility     │
                    │  Resource R, Demand D         │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  CHECK 1: Platform Match?     │
                    │  R.platform == D.platform     │
                    └───────────────────────────────┘
                                    │
                         ┌──────────┴──────────┐
                         │                     │
                        YES                    NO
                         │                     │
                         ▼                     ▼
        ┌───────────────────────────┐   ┌─────────────────┐
        │  CHECK 2: Skill Match?    │   │  REJECT         │
        │  D.case_type in R.skills  │   │  Platform Error │
        └───────────────────────────┘   └─────────────────┘
                         │
              ┌──────────┴──────────┐
              │                     │
             YES                    NO
              │                     │
              ▼                     ▼
┌───────────────────────────┐   ┌─────────────────┐
│  CHECK 3: State Match?    │   │  REJECT         │
│  D.state in R.state_list  │   │  Skill Error    │
│  OR 'N/A' in R.state_list │   └─────────────────┘
└───────────────────────────┘
              │
   ┌──────────┴──────────┐
   │                     │
  YES                    NO
   │                     │
   ▼                     ▼
┌─────────────────┐   ┌─────────────────┐
│  ✓ ELIGIBLE     │   │  REJECT         │
│  Add to Matrix  │   │  State Error    │
└─────────────────┘   └─────────────────┘
```

### 4.5 Example: Misfit Prevention in Action

```
Scenario: Allocating Week 15

Resources:
┌──────┬──────────┬─────────────────┬───────────────┐
│ CN   │ Platform │ Skills          │ States        │
├──────┼──────────┼─────────────────┼───────────────┤
│ R001 │ Amisys   │ {FTC-Basic}     │ {FL, GA}      │
│ R002 │ Amisys   │ {FTC-Basic,ADJ} │ {FL}          │
│ R003 │ Facets   │ {Claims}        │ {TX, CA}      │
│ R004 │ Amisys   │ {ADJ-COB}       │ {N/A}         │
└──────┴──────────┴─────────────────┴───────────────┘

Demands:
┌──────┬──────────┬───────────┬───────┐
│ ID   │ Platform │ Case Type │ State │
├──────┼──────────┼───────────┼───────┤
│ D1   │ Amisys   │ FTC-Basic │ FL    │
│ D2   │ Amisys   │ FTC-Basic │ TX    │
│ D3   │ Facets   │ Claims    │ TX    │
│ D4   │ Amisys   │ ADJ-COB   │ GA    │
└──────┴──────────┴───────────┴───────┘

Eligibility Matrix (after gate):

                D1        D2        D3        D4
              (FL FTC)  (TX FTC)  (TX Clm)  (GA ADJ)
         ┌─────────────────────────────────────────┐
R001     │    ✓          ✗          ✗          ✗   │
(FL,GA)  │  (FL match)  (no TX)   (wrong     (no ADJ
         │                        platform)   skill)
         ├─────────────────────────────────────────┤
R002     │    ✓          ✗          ✗          ✗   │
(FL)     │  (FL match)  (no TX)   (wrong     (no ADJ
         │                        platform)   skill)
         ├─────────────────────────────────────────┤
R003     │    ✗          ✗          ✓          ✗   │
(TX,CA)  │  (wrong     (wrong    (TX match)  (wrong
         │  platform)  platform)             platform)
         ├─────────────────────────────────────────┤
R004     │    ✗          ✗          ✗          ✓   │
(N/A)    │  (no FTC)   (no FTC)  (wrong     (N/A works
         │                       platform)   anywhere)
         └─────────────────────────────────────────┘

Result:
- D1 (FL FTC): Eligible resources = {R001, R002}
- D2 (TX FTC): Eligible resources = {} ← NO ELIGIBLE RESOURCES
- D3 (TX Claims): Eligible resources = {R003}
- D4 (GA ADJ): Eligible resources = {R004}

Key Insight: D2 has ZERO eligible resources because no Amisys FTC
resource works in TX. The system will report a gap for D2, not
allocate an ineligible resource.
```

### 4.6 Sparse Eligibility Matrix

```python
class SparseEligibility:
    """
    Memory-efficient eligibility storage.
    Only stores VALID pairs, not a full r×d matrix.

    For 500 resources × 100 demands:
    - Dense matrix: 50,000 entries × 1 byte = 50 KB
    - Sparse (20% eligible): 10,000 entries × 16 bytes = 160 KB

    But sparse is faster to iterate (skip invalid pairs).
    """

    def __init__(self):
        # Bidirectional index for O(1) lookups
        self.resource_to_demands: Dict[str, Set[int]] = {}
        self.demand_to_resources: Dict[int, Set[str]] = {}

    def add(self, resource_cn: str, demand_id: int):
        """Add an eligible pair."""
        self.resource_to_demands.setdefault(resource_cn, set()).add(demand_id)
        self.demand_to_resources.setdefault(demand_id, set()).add(resource_cn)

    def get_demands_for_resource(self, cn: str) -> Set[int]:
        """Get all demands a resource can serve."""
        return self.resource_to_demands.get(cn, set())

    def get_resources_for_demand(self, demand_id: int) -> Set[str]:
        """Get all resources that can serve a demand."""
        return self.demand_to_resources.get(demand_id, set())

    def can_serve(self, cn: str, demand_id: int) -> bool:
        """Check if resource can serve demand. O(1)."""
        return demand_id in self.resource_to_demands.get(cn, set())

    def count_eligible_pairs(self) -> int:
        """Total number of eligible pairs."""
        return sum(len(demands) for demands in self.resource_to_demands.values())
```

### 4.7 Integration with Scoring

The Eligibility Gate runs **BEFORE** any scoring happens:

```python
def initialize_allocation(year: int, week: int, db: Session) -> AllocationContext:
    """
    Phase 0: Initialize allocation context.

    CRITICAL: Eligibility matrix is built FIRST.
    Scoring only considers pairs IN the eligibility matrix.
    """

    # 1. Load resources
    resources = load_available_resources(year, week, db)

    # 2. Build indices
    resource_index = build_resource_index(resources)

    # 3. Load demands
    demands = load_demands(year, week, db)

    # ═══════════════════════════════════════════════════════════════
    # 4. BUILD ELIGIBILITY MATRIX - THE GATE
    #    After this point, ONLY eligible pairs exist in the system
    # ═══════════════════════════════════════════════════════════════
    eligibility = compute_eligibility_matrix(resources, demands, resource_index)

    return AllocationContext(
        resources=resources,
        resource_index=resource_index,
        demands=demands,
        eligibility=eligibility,  # <-- Scoring uses this
        allocated=set()
    )


def allocate_by_score(ctx: AllocationContext) -> List[Assignment]:
    """
    Phase 3: Scored allocation.

    GUARANTEE: Only pairs in eligibility matrix are scored.
    Misfit allocations are IMPOSSIBLE.
    """

    for resource in ctx.resources:
        if resource.cn in ctx.allocated:
            continue

        # ═══════════════════════════════════════════════════════════════
        # ONLY iterate over ELIGIBLE demands for this resource
        # This is where the gate prevents misfits
        # ═══════════════════════════════════════════════════════════════
        eligible_demands = ctx.eligibility.get_demands_for_resource(resource.cn)

        for demand_id in eligible_demands:  # <-- Already filtered by gate
            demand = ctx.demands[demand_id]
            score = calculate_allocation_score(resource, demand, ctx)
            heapq.heappush(score_heap, (-score.score, score))

    # ... rest of allocation logic
```

### 4.8 Guarantees

| Guarantee | Implementation |
|-----------|----------------|
| **No platform misfits** | Gate rejects `R.platform != D.platform` |
| **No skill misfits** | Gate rejects `D.case_type not in R.skills` |
| **No state misfits** | Gate rejects incompatible states |
| **Audit trail** | Eligibility matrix can be exported for debugging |
| **Performance** | O(r × d) one-time cost, then O(eligible) per iteration |

---

## 5. Ideal FTE Calculation

### 5.1 Key Concept: Weekly Granularity

**Critical Understanding:** Allocation runs **week by week**, not across all 6 months at once.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    WEEKLY ALLOCATION LOOP                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Input: Report Month = June 2025, Forecast Months = Jul-Dec 2025        │
│                                                                          │
│  For EACH forecast month (e.g., July 2025):                             │
│    For EACH week in that month:                                          │
│      1. Filter resources available THIS week                             │
│      2. Get weekly forecast (monthly ÷ weeks)                           │
│      3. Calculate ideal FTE for THIS week                                │
│      4. Run allocation for THIS week                                     │
│      5. Persist WeeklyResourceAssignment records                        │
│                                                                          │
│  Result: Each week allocated independently with fresh resource count    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Monthly Forecast to Weekly Forecast (Working Days Weighted)

Forecasts are stored monthly (Month1-Month6), but allocation is weekly. Distribution must be **weighted by working days**, not equally divided.

**Why Working Days Matter:**
- Weekends (Sat/Sun) are not working days
- Holidays vary by location (Domestic vs Global)
- Partial weeks (month starts Friday = 1 working day)
- Future: Regional holidays per group

### 5.2.0 Location-Aware Distribution Flow

**Critical:** Forecast distribution happens **per demand's location**, not globally.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                LOCATION-AWARE FORECAST DISTRIBUTION FLOW                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  INPUT: Monthly forecasts per (Platform, LOB, CaseType, State, Location)│
│                                                                          │
│  STEP 1: For each demand D:                                             │
│          └── Get D.locality (Domestic or Global)                        │
│                                                                          │
│  STEP 2: Get location-specific working days:                            │
│          └── Domestic demand → Use Domestic calendar (US holidays)      │
│          └── Global demand → Use Global calendar (India holidays)       │
│                                                                          │
│  STEP 3: Distribute D's monthly forecast using D's location calendar:   │
│          └── weekly_forecast[D] = monthly[D] × (days[D.loc] / total)    │
│                                                                          │
│  STEP 4: Filter resources for D:                                        │
│          └── Match platform, skill, state, AND location                 │
│                                                                          │
│  STEP 5: Calculate ideal FTE for D using filtered resources count       │
│                                                                          │
│  RESULT: Each demand uses its own location's working days calendar      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Example: Same Month, Same Forecast, Different Distribution**

```
July 2025 - Week 27 has Jul 4 (US Holiday, not India Holiday)

┌────────────────────────────────────────────────────────────────────────┐
│ Demand D1: Amisys FL FTC-Basic (DOMESTIC)                              │
├────────────────────────────────────────────────────────────────────────┤
│ Monthly Forecast: 8000 cases                                           │
│ Working Days: Week 27=3, Week 28=5, Week 29=5, Week 30=4 → Total=17   │
│                                                                        │
│ Weekly Distribution:                                                   │
│   Week 27: 8000 × (3/17) = 1412 cases                                 │
│   Week 28: 8000 × (5/17) = 2353 cases                                 │
│   Week 29: 8000 × (5/17) = 2353 cases                                 │
│   Week 30: 8000 × (4/17) = 1882 cases                                 │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│ Demand D2: Amisys India FTC-Basic (GLOBAL)                             │
├────────────────────────────────────────────────────────────────────────┤
│ Monthly Forecast: 8000 cases                                           │
│ Working Days: Week 27=4, Week 28=5, Week 29=5, Week 30=5 → Total=19   │
│ (No Jul 4 holiday in India)                                            │
│                                                                        │
│ Weekly Distribution:                                                   │
│   Week 27: 8000 × (4/19) = 1684 cases  ← MORE than Domestic           │
│   Week 28: 8000 × (5/19) = 2105 cases                                 │
│   Week 29: 8000 × (5/19) = 2105 cases                                 │
│   Week 30: 8000 × (5/19) = 2106 cases                                 │
└────────────────────────────────────────────────────────────────────────┘

KEY: D1 and D2 have same monthly forecast (8000) but different weekly
     distribution because they use different location calendars.
```

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    WORKING DAYS WEIGHTED DISTRIBUTION                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Formula (per demand D):                                                │
│                                                                          │
│                                 working_days(week, D.locality)           │
│  weekly_forecast(D) = monthly × ───────────────────────────────────────│
│                                 Σ working_days(all weeks, D.locality)    │
│                                                                          │
│  Where:                                                                  │
│  - D.locality = demand's location (Domestic or Global)                  │
│  - working_days uses D's location-specific calendar                     │
│  - Each demand is distributed independently using its own calendar      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

```python
def distribute_forecasts_to_weeks(demands: List[DemandTarget],
                                   month: int,
                                   year: int,
                                   db: Session) -> Dict[int, Dict[int, int]]:
    """
    Distribute monthly forecasts to weekly for ALL demands.

    Each demand uses its OWN location's working days calendar.

    Args:
        demands: List of demands with monthly_forecast and locality
        month: Month number (1-12)
        year: Year
        db: Database session

    Returns:
        Dict mapping demand_id → {week_number → weekly_forecast}
    """

    # Pre-load working days calendars for both locations
    domestic_weeks = get_week_configs_for_month(month, year, 'Domestic', db)
    global_weeks = get_week_configs_for_month(month, year, 'Global', db)

    domestic_total = sum(w.working_days for w in domestic_weeks)
    global_total = sum(w.working_days for w in global_weeks)

    result = {}

    for demand in demands:
        # SELECT CALENDAR BASED ON DEMAND'S LOCATION
        if demand.locality.upper() in ('DOMESTIC', 'ONSHORE'):
            weeks = domestic_weeks
            total_days = domestic_total
        else:  # GLOBAL, OFFSHORE
            weeks = global_weeks
            total_days = global_total

        # Distribute this demand's forecast using its location's calendar
        weekly = {}
        allocated = 0

        for week in weeks:
            proportion = week.working_days / total_days
            week_forecast = int(demand.monthly_forecast * proportion)
            weekly[week.week_number] = week_forecast
            allocated += week_forecast

        # Distribute remainder
        remainder = demand.monthly_forecast - allocated
        if remainder > 0:
            fractions = [
                (w.week_number, (demand.monthly_forecast * w.working_days / total_days) % 1)
                for w in weeks
            ]
            fractions.sort(key=lambda x: x[1], reverse=True)
            for i in range(remainder):
                weekly[fractions[i % len(fractions)][0]] += 1

        result[demand.demand_id] = weekly

    return result


# Example usage:
#
# demands = [
#     DemandTarget(id=1, platform='Amisys', case_type='FTC', state='FL',
#                  locality='Domestic', monthly_forecast=8000),
#     DemandTarget(id=2, platform='Amisys', case_type='FTC', state='India',
#                  locality='Global', monthly_forecast=8000),
# ]
#
# weekly_forecasts = distribute_forecasts_to_weeks(demands, 7, 2025, db)
#
# Result:
# {
#     1: {27: 1412, 28: 2353, 29: 2353, 30: 1882},  # Domestic calendar
#     2: {27: 1684, 28: 2105, 29: 2105, 30: 2106},  # Global calendar
# }
```

**Example: July 2025 with Holidays**

```
July 2025 Monthly Forecast: 16000 cases

┌─────────────────────────────────────────────────────────────────────────┐
│ DOMESTIC Location (US Holidays)                                         │
├──────────┬────────────────────┬──────────────┬───────────┬─────────────┤
│ Week     │ Dates              │ Working Days │ Proportion│ Forecast    │
├──────────┼────────────────────┼──────────────┼───────────┼─────────────┤
│ Week 27  │ Jun 30 - Jul 6     │ 3 days       │ 3/17=17.6%│ 2,824       │
│          │ (Jul 4 = Holiday)  │ (Mon-Wed)    │           │             │
├──────────┼────────────────────┼──────────────┼───────────┼─────────────┤
│ Week 28  │ Jul 7 - Jul 13     │ 5 days       │ 5/17=29.4%│ 4,706       │
│          │ (Full week)        │              │           │             │
├──────────┼────────────────────┼──────────────┼───────────┼─────────────┤
│ Week 29  │ Jul 14 - Jul 20    │ 5 days       │ 5/17=29.4%│ 4,706       │
│          │ (Full week)        │              │           │             │
├──────────┼────────────────────┼──────────────┼───────────┼─────────────┤
│ Week 30  │ Jul 21 - Jul 27    │ 4 days       │ 4/17=23.5%│ 3,764       │
│          │ (Month ends Thu)   │              │           │             │
├──────────┴────────────────────┼──────────────┼───────────┼─────────────┤
│ TOTAL                         │ 17 days      │ 100%      │ 16,000 ✓    │
└───────────────────────────────┴──────────────┴───────────┴─────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ GLOBAL Location (India Holidays - Different Calendar)                   │
├──────────┬────────────────────┬──────────────┬───────────┬─────────────┤
│ Week     │ Dates              │ Working Days │ Proportion│ Forecast    │
├──────────┼────────────────────┼──────────────┼───────────┼─────────────┤
│ Week 27  │ Jun 30 - Jul 6     │ 4 days       │ 4/19=21.1%│ 3,368       │
│          │ (No Jul 4 holiday) │              │           │             │
├──────────┼────────────────────┼──────────────┼───────────┼─────────────┤
│ Week 28  │ Jul 7 - Jul 13     │ 5 days       │ 5/19=26.3%│ 4,211       │
│          │ (Full week)        │              │           │             │
├──────────┼────────────────────┼──────────────┼───────────┼─────────────┤
│ Week 29  │ Jul 14 - Jul 20    │ 5 days       │ 5/19=26.3%│ 4,211       │
│          │ (Full week)        │              │           │             │
├──────────┼────────────────────┼──────────────┼───────────┼─────────────┤
│ Week 30  │ Jul 21 - Jul 27    │ 5 days       │ 5/19=26.3%│ 4,210       │
│          │ (Full week)        │              │           │             │
├──────────┴────────────────────┼──────────────┼───────────┼─────────────┤
│ TOTAL                         │ 19 days      │ 100%      │ 16,000 ✓    │
└───────────────────────────────┴──────────────┴───────────┴─────────────┘

KEY INSIGHT: Same month, same forecast, but different weekly distribution
             based on location-specific working days.
```

### 5.2.1 WeekConfiguration Model

Working days are stored per week, per location:

```python
@dataclass
class WeekConfiguration:
    """Week configuration with working days per location"""

    id: int
    year: int
    week_number: int
    week_start_date: date
    week_end_date: date

    # Working days by location
    working_days_domestic: int  # Excludes US holidays
    working_days_global: int    # Excludes India/Global holidays

    # Future: Regional working days
    # working_days_region_a: int
    # working_days_region_b: int

    # Other config
    work_hours: float           # Default 9.0
    shrinkage: float            # Default 0.10


def get_working_days(week_config: WeekConfiguration,
                     location: str) -> int:
    """Get working days for a location."""
    if location.upper() in ('DOMESTIC', 'ONSHORE'):
        return week_config.working_days_domestic
    elif location.upper() in ('GLOBAL', 'OFFSHORE'):
        return week_config.working_days_global
    else:
        # Default to domestic
        return week_config.working_days_domestic
```

### 5.2.2 Edge Cases

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    EDGE CASES FOR WORKING DAYS                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. MONTH STARTS ON FRIDAY                                              │
│     Week 1 of month = 1 working day (Friday only)                       │
│     Forecast weight: 1/22 ≈ 4.5% of monthly                             │
│                                                                          │
│  2. MONTH ENDS ON MONDAY                                                │
│     Last week = 1 working day (Monday only)                             │
│     Forecast weight: 1/22 ≈ 4.5% of monthly                             │
│                                                                          │
│  3. HOLIDAY WEEK (e.g., Christmas)                                      │
│     Week may have only 2-3 working days                                 │
│     Forecast weight proportionally reduced                              │
│                                                                          │
│  4. DIFFERENT HOLIDAYS BY LOCATION                                      │
│     Domestic: Jul 4, Thanksgiving, etc.                                 │
│     Global: Diwali, Holi, regional holidays                             │
│     Same week can have different working days per location              │
│                                                                          │
│  5. FUTURE: REGIONAL HOLIDAYS                                           │
│     Within Domestic, different states may have different holidays       │
│     TX holiday vs CA holiday                                            │
│     Model can be extended with working_days_per_region                  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Resource Availability Per Week

Resources are filtered **fresh each week** based on their availability window:

```python
def get_available_resources_for_week(year: int,
                                      week_number: int,
                                      db: Session) -> List[Resource]:
    """
    Get resources available for a specific week.

    A resource is available if:
    - is_active = True
    - available_from <= week_start_date
    - available_until >= week_end_date (or is NULL)
    """

    week_start, week_end = get_week_dates(year, week_number)

    return db.query(ResourceModel).filter(
        ResourceModel.is_active == True,
        ResourceModel.available_from <= week_start,
        or_(
            ResourceModel.available_until.is_(None),
            ResourceModel.available_until >= week_end
        )
    ).all()
```

**Example: Resource Availability Changes Week to Week**

```
Resource R001: available_from = Apr 1, available_until = Apr 20
Resource R002: available_from = Apr 1, available_until = NULL (ongoing)
Resource R003: available_from = Apr 15, available_until = NULL (new hire)

Week 15 (Apr 7-13):
├── R001: ✓ Available (Apr 1-20 covers this week)
├── R002: ✓ Available (ongoing)
└── R003: ✗ NOT available (starts Apr 15)
└── Total: 2 resources

Week 16 (Apr 14-20):
├── R001: ✓ Available (Apr 1-20 covers this week)
├── R002: ✓ Available (ongoing)
└── R003: ✓ Available (started Apr 15)
└── Total: 3 resources

Week 17 (Apr 21-27):
├── R001: ✗ NOT available (ended Apr 20)
├── R002: ✓ Available (ongoing)
└── R003: ✓ Available (ongoing)
└── Total: 2 resources
```

### 5.4 Ideal FTE Formula (Per Week)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    IDEAL FTE FORMULA                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  For each demand d in week w:                                           │
│                                                                          │
│                                         weekly_forecast(d, w)            │
│  ideal_fte(d, w) = available_resources(w) × ─────────────────────────   │
│                                          Σ weekly_forecast(all, w)       │
│                                                                          │
│  Where:                                                                  │
│  - available_resources(w) = count of resources available in week w      │
│  - weekly_forecast(d, w) = demand d's forecast for week w               │
│  - Σ weekly_forecast(all, w) = sum of all demand forecasts for week w   │
│                                                                          │
│  KEY: Each variable is specific to week w, not the entire month/year    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.5 Complete Weekly Calculation Example (Working Days Weighted)

```
═══════════════════════════════════════════════════════════════════════════
MONTH: July 2025 (Weeks 27, 28, 29, 30) - DOMESTIC Location
═══════════════════════════════════════════════════════════════════════════

Monthly Forecasts (from ForecastModel):
  D1: Amisys FL FTC-Basic    = 8000 cases/month
  D2: Amisys GA FTC-Basic    = 6000 cases/month
  D3: Facets TX Claims       = 2000 cases/month
  ─────────────────────────────────────────────
  Total Monthly:               16000 cases

Working Days by Week (Domestic):
  Week 27: 3 days (Jul 4 holiday)
  Week 28: 5 days (full week)
  Week 29: 5 days (full week)
  Week 30: 4 days (month ends Thu)
  ─────────────────────────────────
  Total: 17 working days

Weekly Forecast (weighted by working days):
  Week 27: 16000 × (3/17) = 2824 cases
  Week 28: 16000 × (5/17) = 4706 cases
  Week 29: 16000 × (5/17) = 4706 cases
  Week 30: 16000 × (4/17) = 3764 cases
  ─────────────────────────────────────
  Total: 16000 cases ✓

Per-Demand Weekly Forecast (same 50%/37.5%/12.5% split):
  Week 27: D1=1412, D2=1059, D3=353
  Week 28: D1=2353, D2=1765, D3=588
  Week 29: D1=2353, D2=1765, D3=588
  Week 30: D1=1882, D2=1412, D3=470

───────────────────────────────────────────────────────────────────────────
WEEK 27 (Jul 1-6): 50 resources available, 3 working days
───────────────────────────────────────────────────────────────────────────
  Weekly Forecast: 2824 total (D1=1412, D2=1059, D3=353)

  D1: 50 × (1412/2824) = 50 × 0.50 = 25.0 ideal FTE
  D2: 50 × (1059/2824) = 50 × 0.375 = 18.75 ideal FTE
  D3: 50 × (353/2824)  = 50 × 0.125 = 6.25 ideal FTE
  ─────────────────────────────────────────────────────
  Total: 50.0 FTE ✓

  Capacity per resource: 3 days × 9 hrs × 0.90 = 24.3 hrs
  (Lower capacity due to fewer working days)

───────────────────────────────────────────────────────────────────────────
WEEK 28 (Jul 7-13): 48 resources available, 5 working days
───────────────────────────────────────────────────────────────────────────
  Weekly Forecast: 4706 total (D1=2353, D2=1765, D3=588)

  D1: 48 × (2353/4706) = 48 × 0.50 = 24.0 ideal FTE
  D2: 48 × (1765/4706) = 48 × 0.375 = 18.0 ideal FTE
  D3: 48 × (588/4706)  = 48 × 0.125 = 6.0 ideal FTE
  ─────────────────────────────────────────────────────
  Total: 48.0 FTE ✓

  Capacity per resource: 5 days × 9 hrs × 0.90 = 40.5 hrs
  (Full week = higher capacity)

───────────────────────────────────────────────────────────────────────────
WEEK 29 (Jul 14-20): 52 resources available, 5 working days
───────────────────────────────────────────────────────────────────────────
  Weekly Forecast: 4706 total (D1=2353, D2=1765, D3=588)

  D1: 52 × (2353/4706) = 52 × 0.50 = 26.0 ideal FTE
  D2: 52 × (1765/4706) = 52 × 0.375 = 19.5 ideal FTE
  D3: 52 × (588/4706)  = 52 × 0.125 = 6.5 ideal FTE
  ─────────────────────────────────────────────────────
  Total: 52.0 FTE ✓

───────────────────────────────────────────────────────────────────────────
WEEK 30 (Jul 21-27): 52 resources available, 4 working days
───────────────────────────────────────────────────────────────────────────
  Weekly Forecast: 3764 total (D1=1882, D2=1412, D3=470)

  D1: 52 × (1882/3764) = 52 × 0.50 = 26.0 ideal FTE
  D2: 52 × (1412/3764) = 52 × 0.375 = 19.5 ideal FTE
  D3: 52 × (470/3764)  = 52 × 0.125 = 6.5 ideal FTE
  ─────────────────────────────────────────────────────
  Total: 52.0 FTE ✓

  Capacity per resource: 4 days × 9 hrs × 0.90 = 32.4 hrs

═══════════════════════════════════════════════════════════════════════════
MONTHLY SUMMARY (Sum of weekly allocations):
═══════════════════════════════════════════════════════════════════════════
  D1: 25 + 24 + 26 + 26 = 101 resource-weeks
  D2: 19 + 18 + 20 + 20 = 77 resource-weeks (rounded)
  D3: 6 + 6 + 6 + 6 = 24 resource-weeks
  ─────────────────────────────────────────────
  Total: 202 resource-weeks across July

KEY INSIGHT: Forecast was NOT evenly distributed (4000/week).
             Week 27 had lower forecast (2824) due to fewer working days.
             Week 28/29 had higher forecast (4706) due to full weeks.
```

### 5.6 Resource-Week Concept

A **resource-week** is the unit of allocation:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    RESOURCE-WEEK CONCEPT                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Definition: 1 resource-week = 1 resource working for 1 week            │
│                                                                          │
│  Example: Resource R001 available for 3 weeks in July                   │
│                                                                          │
│  Week 27: R001 allocated to D1 → 1 resource-week for D1                 │
│  Week 28: R001 allocated to D2 → 1 resource-week for D2                 │
│  Week 29: R001 allocated to D1 → 1 resource-week for D1                 │
│  Week 30: R001 ended availability                                       │
│                                                                          │
│  Total contribution: 3 resource-weeks (2 to D1, 1 to D2)                │
│                                                                          │
│  This is NOT the same as "3 FTEs" - it's one person for 3 weeks         │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.7 Same Resource, Multiple Weeks, Different Demands

A resource can be allocated to **different demands** in different weeks:

```python
# Example: Multi-skilled resource allocation across weeks

Resource R001:
  skills = {FTC-Basic, ADJ-COB}
  states = {FL, GA}
  available_from = Jul 1
  available_until = Jul 31

Week 27:
  D1 (FL FTC) has highest urgency → R001 → D1
  Assignment: WeeklyResourceAssignment(cn=R001, week=27, demand=D1)

Week 28:
  D1 filled, D3 (FL ADJ) now has highest urgency → R001 → D3
  Assignment: WeeklyResourceAssignment(cn=R001, week=28, demand=D3)

Week 29:
  D1 has gap again → R001 → D1
  Assignment: WeeklyResourceAssignment(cn=R001, week=29, demand=D1)

Result: R001 contributed to BOTH D1 and D3 across the month
        This is VALID and EXPECTED for multi-skilled resources
```

### 5.8 Implementation

```python
def run_monthly_allocation(report_month: str,
                            report_year: int,
                            forecast_month: str,
                            db: Session) -> MonthlyAllocationResult:
    """
    Run allocation for all weeks in a forecast month.

    Args:
        report_month: The report month (e.g., "June")
        report_year: The report year (e.g., 2025)
        forecast_month: The forecast month to allocate (e.g., "July")
    """

    # Get week numbers for the forecast month
    weeks = get_weeks_in_month(forecast_month, report_year)

    # Load all demands with their monthly forecasts
    monthly_demands = load_demands_for_month(forecast_month, report_year, db)

    # ═══════════════════════════════════════════════════════════════
    # STEP 1: DISTRIBUTE FORECASTS USING LOCATION-SPECIFIC CALENDARS
    # Each demand uses its own locality's working days
    # ═══════════════════════════════════════════════════════════════
    weekly_forecasts_by_demand = distribute_forecasts_to_weeks(
        demands=monthly_demands,
        month=get_month_number(forecast_month),
        year=report_year,
        db=db
    )
    # Result: {demand_id: {week_num: forecast, ...}, ...}

    all_assignments = []

    # ═══════════════════════════════════════════════════════════════
    # STEP 2: PROCESS EACH WEEK INDEPENDENTLY
    # ═══════════════════════════════════════════════════════════════
    for week_number in weeks:

        # 2a. Get resources available THIS week
        available_resources = get_available_resources_for_week(
            report_year, week_number, db
        )

        # 2b. Build demands for THIS week with weekly forecasts
        week_demands = []
        for demand in monthly_demands:
            week_forecast = weekly_forecasts_by_demand[demand.demand_id][week_number]
            week_demands.append(DemandTarget(
                demand_id=demand.demand_id,
                platform=demand.platform,
                state=demand.state,
                case_type=demand.case_type,
                locality=demand.locality,
                weekly_forecast=week_forecast,  # Location-specific!
                ideal_fte=0.0,
                current_fte=0,
                gap=0.0
            ))

        # 2c. Calculate ideal FTE for THIS week
        #     Uses total weekly forecast (already location-adjusted)
        ideal_fte = calculate_ideal_fte_for_week(
            demands=week_demands,
            available_resources=available_resources
        )

        # 2d. Build eligibility matrix
        eligibility = compute_eligibility_matrix(
            available_resources, week_demands
        )

        # 2e. Run allocation for THIS week
        week_assignments = allocate_week(
            year=report_year,
            week=week_number,
            resources=available_resources,
            demands=week_demands,
            ideal_fte=ideal_fte,
            eligibility=eligibility
        )

        all_assignments.extend(week_assignments)

    return MonthlyAllocationResult(
        month=forecast_month,
        year=report_year,
        total_weeks=len(weeks),
        assignments=all_assignments
    )


def calculate_ideal_fte_for_week(demands: List[DemandTarget],
                                  available_resources: List[Resource]) -> Dict[int, float]:
    """
    Calculate ideal FTE for a single week.

    Note: Each demand already has its weekly_forecast calculated using
    its location-specific working days calendar.

    Args:
        demands: List of demands with weekly_forecast values
        available_resources: Resources available THIS week

    Returns:
        Dict mapping demand_id → ideal_fte for this week
    """

    total_forecast = sum(d.weekly_forecast for d in demands)

    if total_forecast == 0:
        return {d.demand_id: 0.0 for d in demands}

    # Group resources by location for accurate counting
    domestic_resources = [r for r in available_resources
                          if r.location.upper() in ('DOMESTIC', 'ONSHORE')]
    global_resources = [r for r in available_resources
                        if r.location.upper() in ('GLOBAL', 'OFFSHORE')]

    ideal_fte = {}

    for demand in demands:
        # Get resources that match this demand's location
        if demand.locality.upper() in ('DOMESTIC', 'ONSHORE'):
            matching_resources = len(domestic_resources)
        else:
            matching_resources = len(global_resources)

        # Calculate ideal based on this demand's forecast proportion
        # among demands of the SAME location
        same_location_demands = [d for d in demands
                                  if d.locality.upper() == demand.locality.upper()]
        same_location_forecast = sum(d.weekly_forecast for d in same_location_demands)

        if same_location_forecast > 0:
            proportion = demand.weekly_forecast / same_location_forecast
            ideal_fte[demand.demand_id] = matching_resources * proportion
        else:
            ideal_fte[demand.demand_id] = 0.0

    return ideal_fte
```

### 5.9 Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                 COMPLETE LOCATION-AWARE ALLOCATION FLOW                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  INPUT: July 2025 forecasts                                             │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ STEP 1: Load demands with monthly forecasts                     │   │
│  │                                                                  │   │
│  │  D1: Amisys FL FTC    | Domestic | 8000/month                   │   │
│  │  D2: Amisys GA FTC    | Domestic | 6000/month                   │   │
│  │  D3: Amisys India FTC | Global   | 4000/month                   │   │
│  │  D4: Facets TX Claims | Domestic | 2000/month                   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              ↓                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ STEP 2: Distribute to weeks using LOCATION calendars            │   │
│  │                                                                  │   │
│  │  Domestic Calendar: Week 27=3d, 28=5d, 29=5d, 30=4d (17 total)  │   │
│  │  Global Calendar:   Week 27=4d, 28=5d, 29=5d, 30=5d (19 total)  │   │
│  │                                                                  │   │
│  │  D1 (Domestic): W27=1412, W28=2353, W29=2353, W30=1882         │   │
│  │  D2 (Domestic): W27=1059, W28=1765, W29=1765, W30=1411         │   │
│  │  D3 (Global):   W27=842,  W28=1053, W29=1053, W30=1052         │   │
│  │  D4 (Domestic): W27=353,  W28=588,  W29=588,  W30=471          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              ↓                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ STEP 3: For each WEEK, allocate independently                   │   │
│  │                                                                  │   │
│  │  Week 27:                                                       │   │
│  │    Domestic resources: 40 available                             │   │
│  │    Global resources:   15 available                             │   │
│  │                                                                  │   │
│  │    Domestic demands (D1+D2+D4): 2824 total weekly forecast      │   │
│  │    → D1 ideal: 40 × (1412/2824) = 20.0 FTE                      │   │
│  │    → D2 ideal: 40 × (1059/2824) = 15.0 FTE                      │   │
│  │    → D4 ideal: 40 × (353/2824)  = 5.0 FTE                       │   │
│  │                                                                  │   │
│  │    Global demands (D3): 842 weekly forecast                     │   │
│  │    → D3 ideal: 15 × (842/842) = 15.0 FTE (all global resources) │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  RESULT: Each location's resources serve that location's demands        │
│          using that location's working days calendar                    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Allocation Phases

### Phase 1: Initialization

```python
def initialize_allocation(year: int, week: int, db: Session) -> AllocationContext:
    """
    Load and index all data for fast allocation.

    Time: O(r + d) where r=resources, d=demands
    Space: O(r × s) where s=avg skills per resource
    """

    # 1. Load resources available this week
    resources = load_available_resources(year, week, db)

    # 2. Build indices
    resource_index = build_resource_index(resources)

    # 3. Load demands
    demands = load_demands(year, week, db)

    # 4. Pre-compute eligibility matrix (sparse)
    eligibility = compute_eligibility_matrix(resources, demands, resource_index)

    return AllocationContext(
        resources=resources,
        resource_index=resource_index,
        demands=demands,
        eligibility=eligibility,
        allocated=set()
    )
```

### Phase 2: Exclusive Resource Allocation

```python
def allocate_exclusive_resources(ctx: AllocationContext) -> List[Assignment]:
    """
    Allocate resources that can only serve ONE demand.
    These MUST go to their only matching demand.

    Time: O(r) single pass through resources
    """

    assignments = []

    for resource in ctx.resources:
        if resource.cn in ctx.allocated:
            continue

        # Find all demands this resource can serve
        eligible_demands = ctx.eligibility.get_demands_for_resource(resource.cn)

        if len(eligible_demands) == 1:
            # Exclusive resource - only one option
            demand_id = eligible_demands[0]
            demand = ctx.demands[demand_id]

            # Allocate
            assignment = create_assignment(resource, demand, ctx)
            assignments.append(assignment)

            # Update state
            ctx.allocated.add(resource.cn)
            demand.current_fte += 1
            demand.gap = demand.ideal_fte - demand.current_fte

    return assignments
```

### Phase 3: Scored Allocation (Main Algorithm)

```python
def allocate_by_score(ctx: AllocationContext) -> List[Assignment]:
    """
    Score-based allocation using priority queue.

    Time: O(r × d × log(r × d)) for heap operations
    Space: O(r × d) for score entries
    """

    assignments = []

    # Build priority queue with all valid pairs
    score_heap = []  # Max heap (negate scores for min heap)

    for resource in ctx.resources:
        if resource.cn in ctx.allocated:
            continue

        eligible_demands = ctx.eligibility.get_demands_for_resource(resource.cn)

        for demand_id in eligible_demands:
            demand = ctx.demands[demand_id]
            score = calculate_allocation_score(resource, demand, ctx)

            # Push to heap (negate for max-heap behavior)
            heapq.heappush(score_heap, (-score.score, score))

    # Process heap until empty or all resources allocated
    while score_heap and len(ctx.allocated) < len(ctx.resources):
        neg_score, score_entry = heapq.heappop(score_heap)

        resource_cn = score_entry.resource_cn
        demand_id = score_entry.demand_id

        # Skip if resource already allocated
        if resource_cn in ctx.allocated:
            continue

        # Skip if demand already at or above ideal
        demand = ctx.demands[demand_id]
        if demand.current_fte >= demand.ideal_fte:
            continue

        # Allocate
        resource = ctx.resource_index.by_cn[resource_cn]
        assignment = create_assignment(resource, demand, ctx)
        assignments.append(assignment)

        # Update state
        ctx.allocated.add(resource_cn)
        demand.current_fte += 1
        demand.gap = demand.ideal_fte - demand.current_fte

    return assignments
```

### Phase 4: Scoring Function

```python
def calculate_allocation_score(resource: Resource,
                                demand: DemandTarget,
                                ctx: AllocationContext) -> AllocationScore:
    """
    Calculate allocation priority score.
    Higher score = higher priority for allocation.

    Time: O(1) using pre-computed values
    """

    # Component 1: Demand Urgency (40% weight)
    # How much does this demand need resources relative to ideal?
    if demand.ideal_fte > 0:
        urgency = (demand.ideal_fte - demand.current_fte) / demand.ideal_fte
    else:
        urgency = 0
    urgency_score = max(0, min(1, urgency)) * 0.40

    # Component 2: Resource Exclusivity (35% weight)
    # Prefer resources with fewer options (they MUST go somewhere specific)
    eligible_demand_count = len(ctx.eligibility.get_demands_for_resource(resource.cn))
    exclusivity = 1.0 / eligible_demand_count
    exclusivity_score = exclusivity * 0.35

    # Component 3: State Match Quality (15% weight)
    # Exact state match preferred over N/A fallback
    if demand.state in resource.state_list and demand.state != 'N/A':
        state_score = 1.0 * 0.15
    elif 'N/A' in resource.state_list:
        state_score = 0.5 * 0.15
    else:
        state_score = 0

    # Component 4: Skill Match Quality (10% weight)
    # Single-skill resources preferred for their skill
    if len(resource.skills) == 1:
        skill_score = 1.0 * 0.10
    else:
        skill_score = 0.5 * 0.10

    total_score = urgency_score + exclusivity_score + state_score + skill_score

    return AllocationScore(
        score=total_score,
        resource_cn=resource.cn,
        demand_id=demand.demand_id,
        urgency_score=urgency_score,
        exclusivity_score=exclusivity_score,
        state_score=state_score
    )
```

### Phase 5: Remainder Distribution

```python
def distribute_remainder(ctx: AllocationContext) -> List[Assignment]:
    """
    Use Largest Remainder Method for any unallocated resources.

    Time: O(d log d) for sorting
    """

    unallocated = [r for r in ctx.resources if r.cn not in ctx.allocated]
    if not unallocated:
        return []

    assignments = []

    # Calculate remainders
    remainders = []
    for demand in ctx.demands.values():
        fractional = demand.ideal_fte - int(demand.ideal_fte)
        current_gap = demand.ideal_fte - demand.current_fte
        remainders.append((demand.demand_id, fractional, current_gap))

    # Sort by remainder (descending), then by gap (descending)
    remainders.sort(key=lambda x: (x[1], x[2]), reverse=True)

    # Allocate remaining resources to demands with largest remainders
    for resource in unallocated:
        for demand_id, _, _ in remainders:
            demand = ctx.demands[demand_id]

            # Check if resource can serve this demand
            if ctx.eligibility.can_serve(resource.cn, demand_id):
                assignment = create_assignment(resource, demand, ctx)
                assignments.append(assignment)
                ctx.allocated.add(resource.cn)
                demand.current_fte += 1
                break

    return assignments
```

---

## 7. Detailed Flowcharts

### 6.1 Main Allocation Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     WEEKLY ALLOCATION MAIN FLOW                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  START: Input Week & Year     │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Load Week Configuration      │
                    │  (working_days, shrinkage)    │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Load Available Resources     │
                    │  WHERE available_from <= week │
                    │  AND available_until >= week  │
                    │  AND is_active = true         │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Build Resource Indices       │
                    │  - by_skill: O(r×s)          │
                    │  - by_state: O(r×t)          │
                    │  - by_platform: O(r)         │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Load Demands for Week        │
                    │  (platform, state, case_type, │
                    │   forecast)                   │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Calculate Ideal FTE          │
                    │  ideal = total × (forecast /  │
                    │          sum_forecasts)       │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  PHASE 2: Exclusive Allocation│
                    │  Resources with 1 option only │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  PHASE 3: Scored Allocation   │
                    │  Priority queue by score      │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  PHASE 4: Remainder Distribution│
                    │  Largest Remainder Method     │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Calculate Weekly Capacity    │
                    │  per assignment               │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Persist to Database          │
                    │  WeeklyResourceAssignment     │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Return AllocationResult      │
                    └───────────────────────────────┘
```

### 6.2 Scoring Decision Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     ALLOCATION SCORING FLOW                             │
└─────────────────────────────────────────────────────────────────────────┘

For each (Resource R, Demand D) pair:

                    ┌───────────────────────────────┐
                    │  Can R serve D?               │
                    │  - Skill match?               │
                    │  - State compatible?          │
                    │  - Platform match?            │
                    └───────────────────────────────┘
                                    │
                         ┌──────────┴──────────┐
                         │                     │
                        YES                    NO
                         │                     │
                         ▼                     ▼
        ┌─────────────────────────┐    ┌─────────────┐
        │  Calculate Score        │    │  Skip pair  │
        └─────────────────────────┘    └─────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ URGENCY      │ │ EXCLUSIVITY  │ │ STATE MATCH  │
│ (40%)        │ │ (35%)        │ │ (15%)        │
│              │ │              │ │              │
│ gap/ideal    │ │ 1/options    │ │ exact=1.0    │
│ 0.0 to 1.0   │ │ 0.0 to 1.0   │ │ N/A=0.5      │
└──────────────┘ └──────────────┘ └──────────────┘
        │                │                │
        └────────────────┼────────────────┘
                         │
                         ▼
                ┌─────────────────┐
                │  SKILL MATCH    │
                │  (10%)          │
                │                 │
                │  single=1.0     │
                │  multi=0.5      │
                └─────────────────┘
                         │
                         ▼
                ┌─────────────────┐
                │  Total Score =  │
                │  Σ components   │
                │  (0.0 to 1.0)   │
                └─────────────────┘
                         │
                         ▼
                ┌─────────────────┐
                │  Push to Heap   │
                │  (-score, entry)│
                └─────────────────┘
```

### 6.3 Ideal FTE Calculation Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    IDEAL FTE CALCULATION FLOW                           │
└─────────────────────────────────────────────────────────────────────────┘

                    ┌───────────────────────────────┐
                    │  Input: Week W                │
                    │  Available Resources: R       │
                    │  Demands: D₁, D₂, ... Dₙ     │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Count Available Resources    │
                    │  total_available = |R|        │
                    │  (e.g., 50 resources)         │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Sum All Forecasts            │
                    │  total_forecast = Σ Dᵢ.forecast│
                    │  (e.g., 5000 cases)           │
                    └───────────────────────────────┘
                                    │
                                    ▼
            ┌───────────────────────────────────────────────┐
            │  FOR EACH Demand Dᵢ:                          │
            │                                               │
            │  proportion = Dᵢ.forecast / total_forecast    │
            │                                               │
            │  ideal_fte = total_available × proportion     │
            │                                               │
            │  Example:                                     │
            │  D1: 2000/5000 × 50 = 20.0 FTE               │
            │  D2: 1500/5000 × 50 = 15.0 FTE               │
            │  D3: 1000/5000 × 50 = 10.0 FTE               │
            │  D4: 500/5000 × 50 = 5.0 FTE                 │
            └───────────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Validate: Σ ideal_fte =      │
                    │           total_available     │
                    │  (20+15+10+5 = 50) ✓          │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Store ideal_fte per demand   │
                    │  for gap tracking             │
                    └───────────────────────────────┘
```

### 6.4 Multi-Skilled Resource Decision Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│               MULTI-SKILLED RESOURCE ALLOCATION DECISION                │
└─────────────────────────────────────────────────────────────────────────┘

Resource R: Skills = {FTC-Basic, ADJ-COB}, States = {FL, GA, N/A}

                    ┌───────────────────────────────┐
                    │  Find all eligible demands    │
                    │  D1: FL FTC-Basic (gap=5)     │
                    │  D2: GA FTC-Basic (gap=3)     │
                    │  D3: FL ADJ-COB (gap=2)       │
                    │  D4: TX FTC-Basic (gap=4)     │◄── R cannot serve (no TX)
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Calculate scores for each:   │
                    │                               │
                    │  D1: urgency=0.25 × 0.40      │
                    │      exclusivity=0.33 × 0.35  │
                    │      state=1.0 × 0.15         │
                    │      skill=0.5 × 0.10         │
                    │      = 0.10 + 0.12 + 0.15     │
                    │        + 0.05 = 0.42          │
                    │                               │
                    │  D2: urgency=0.15 × 0.40      │
                    │      exclusivity=0.33 × 0.35  │
                    │      state=1.0 × 0.15         │
                    │      = 0.06 + 0.12 + 0.15     │
                    │        + 0.05 = 0.38          │
                    │                               │
                    │  D3: urgency=0.10 × 0.40      │
                    │      exclusivity=0.33 × 0.35  │
                    │      state=1.0 × 0.15         │
                    │      = 0.04 + 0.12 + 0.15     │
                    │        + 0.05 = 0.36          │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Select highest score:        │
                    │  D1 (0.42) wins               │
                    │                               │
                    │  R → D1 (FL FTC-Basic)        │
                    └───────────────────────────────┘
```

---

## 8. Complexity Analysis

### 7.1 Time Complexity

| Phase | Operation | Complexity | Notes |
|-------|-----------|------------|-------|
| **Init** | Load resources | O(r) | Database query |
| **Init** | Build skill index | O(r × s) | s = avg skills per resource |
| **Init** | Build state index | O(r × t) | t = avg states per resource |
| **Init** | Load demands | O(d) | Database query |
| **Ideal FTE** | Calculate proportions | O(d) | Simple division |
| **Exclusive** | Find single-option | O(r) | Single pass |
| **Scored** | Build heap | O(r × d × log(rd)) | All pairs scored |
| **Scored** | Process heap | O(r × log(rd)) | Extract max r times |
| **Remainder** | Sort remainders | O(d log d) | Once |
| **Remainder** | Distribute | O(r × d) | Worst case |
| **Persist** | Bulk insert | O(a) | a = assignments |

**Total Time Complexity:** O(r × d × log(rd))

For typical values (r=500 resources, d=100 demands):
- r × d = 50,000 pairs
- log(50,000) ≈ 16
- Total operations ≈ 800,000

**At 1M operations/second = ~1ms per week allocation**

### 7.2 Space Complexity

| Structure | Space | Notes |
|-----------|-------|-------|
| Resource list | O(r) | r resources |
| Skill index | O(r × s) | s skills per resource |
| State index | O(r × t) | t states per resource |
| Demand list | O(d) | d demands |
| Eligibility matrix | O(r × d) sparse | Only valid pairs stored |
| Score heap | O(r × d) | All valid pairs |
| Allocated set | O(r) | Just CNs |

**Total Space Complexity:** O(r × d + r × s)

For typical values:
- r × d = 50,000 pairs × 48 bytes = 2.4 MB
- r × s = 500 × 5 × 32 bytes = 80 KB
- **Total: ~3 MB per week**

### 7.3 Optimization Techniques

```python
# 1. SPARSE ELIGIBILITY MATRIX
# Instead of dense r×d matrix, use dict of sets
class SparseEligibility:
    """Only store valid pairs"""
    def __init__(self):
        self.resource_to_demands: Dict[str, Set[int]] = {}
        self.demand_to_resources: Dict[int, Set[str]] = {}

    def add(self, resource_cn: str, demand_id: int):
        self.resource_to_demands.setdefault(resource_cn, set()).add(demand_id)
        self.demand_to_resources.setdefault(demand_id, set()).add(resource_cn)

    def get_demands_for_resource(self, cn: str) -> Set[int]:
        return self.resource_to_demands.get(cn, set())

    def can_serve(self, cn: str, demand_id: int) -> bool:
        return demand_id in self.resource_to_demands.get(cn, set())


# 2. LAZY SCORE CALCULATION
# Don't pre-calculate all scores, calculate on-demand
class LazyScoreHeap:
    """Calculate scores only when needed"""
    def __init__(self, ctx: AllocationContext):
        self.ctx = ctx
        self.heap = []
        self._initialize_with_rough_scores()

    def _initialize_with_rough_scores(self):
        """Start with urgency-only scores for speed"""
        for demand in self.ctx.demands.values():
            rough_score = demand.gap / max(demand.ideal_fte, 1)
            for cn in self.ctx.eligibility.demand_to_resources[demand.demand_id]:
                heapq.heappush(self.heap, (-rough_score, cn, demand.demand_id))


# 3. BATCH DATABASE OPERATIONS
# Collect all assignments, insert in one transaction
def persist_assignments_batch(assignments: List[Assignment], db: Session):
    """Bulk insert for performance"""
    db.bulk_insert_mappings(WeeklyResourceAssignment, [
        {
            'resource_cn': a.resource_cn,
            'demand_id': a.demand_id,
            'year': a.year,
            'week_number': a.week_number,
            'capacity_tier_id': a.capacity_tier_id,
            'weekly_capacity': a.weekly_capacity
        }
        for a in assignments
    ])
    db.commit()
```

---

## 9. Memory Optimization

### 8.1 String Interning

```python
# Intern frequently used strings to save memory
import sys

class InternedStrings:
    """Cache interned strings for memory efficiency"""
    _cache: Dict[str, str] = {}

    @classmethod
    def intern(cls, s: str) -> str:
        if s not in cls._cache:
            cls._cache[s] = sys.intern(s)
        return cls._cache[s]

# Usage: Store interned platform names
resource.platform = InternedStrings.intern(resource.platform)  # "Amisys" stored once
```

### 8.2 Use Slots for Dataclasses

```python
@dataclass(slots=True)  # Python 3.10+
class Resource:
    """Memory-efficient resource using slots"""
    cn: str
    platform: str
    location: str
    skills: frozenset
    state_list: frozenset
    available_from: date
    available_until: date

# Without slots: ~152 bytes per instance
# With slots: ~104 bytes per instance
# Savings: 32% for 10,000 resources = 480 KB saved
```

### 8.3 Generator-Based Processing

```python
def iter_available_resources(year: int, week: int, db: Session):
    """Stream resources instead of loading all at once"""

    week_start, week_end = get_week_dates(year, week)

    query = db.query(ResourceModel).filter(
        ResourceModel.is_active == True,
        ResourceModel.available_from <= week_start,
        or_(
            ResourceModel.available_until.is_(None),
            ResourceModel.available_until >= week_end
        )
    ).yield_per(1000)  # Fetch in batches of 1000

    for resource in query:
        yield resource
```

### 8.4 Index-Based References

```python
# Instead of storing full objects, store indices
class CompactAllocationState:
    """Memory-efficient state using numpy arrays"""

    def __init__(self, num_resources: int, num_demands: int):
        # Use numpy for compact storage
        import numpy as np

        # Resource allocation status (1 byte each)
        self.allocated = np.zeros(num_resources, dtype=np.bool_)

        # Demand current FTE (2 bytes each)
        self.current_fte = np.zeros(num_demands, dtype=np.int16)

        # Demand ideal FTE (4 bytes each)
        self.ideal_fte = np.zeros(num_demands, dtype=np.float32)
```

---

## 10. Implementation Plan

### 9.1 File Structure

```
code/logics/
├── allocation_v2/
│   ├── __init__.py
│   ├── models.py           # Data structures
│   ├── indices.py          # Resource indexing
│   ├── ideal_fte.py        # FTE calculation
│   ├── scoring.py          # Allocation scoring
│   ├── allocator.py        # Main algorithm
│   ├── persistence.py      # Database operations
│   └── tests/
│       ├── test_indices.py
│       ├── test_scoring.py
│       ├── test_allocator.py
│       └── test_integration.py
```

### 9.2 Implementation Phases

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| **1. Data Structures** | Week 1 | models.py, indices.py with tests |
| **2. Ideal FTE** | Week 1 | ideal_fte.py with tests |
| **3. Scoring** | Week 2 | scoring.py with tests |
| **4. Core Algorithm** | Week 2-3 | allocator.py with tests |
| **5. Persistence** | Week 3 | persistence.py, integration tests |
| **6. API Integration** | Week 4 | allocation_router_v2.py |
| **7. Performance Tuning** | Week 4 | Benchmarks, optimization |

### 9.3 Testing Strategy

```python
# Example test case
def test_fair_allocation_multi_skilled():
    """Multi-skilled resources should be distributed fairly"""

    # Setup
    resources = [
        Resource(cn="R1", skills={"FTC"}, states={"FL"}),      # Exclusive to FL FTC
        Resource(cn="R2", skills={"FTC", "ADJ"}, states={"FL", "GA"}),  # Multi
        Resource(cn="R3", skills={"ADJ"}, states={"GA"}),      # Exclusive to GA ADJ
    ]

    demands = [
        Demand(id=1, case_type="FTC", state="FL", forecast=100),
        Demand(id=2, case_type="FTC", state="GA", forecast=80),
        Demand(id=3, case_type="ADJ", state="GA", forecast=60),
    ]

    # Execute
    result = allocate_week(resources, demands)

    # Assert fair distribution
    assert result.assignments["R1"].demand_id == 1  # Exclusive to D1
    assert result.assignments["R3"].demand_id == 3  # Exclusive to D3
    assert result.assignments["R2"].demand_id == 2  # R2 is only option for D2
```

---

## Summary

This algorithm provides:

| Feature | Benefit |
|---------|---------|
| **Proportional allocation** | Fair distribution based on forecast |
| **Exclusivity awareness** | Single-option resources allocated first |
| **Scoring system** | Multi-factor decision making |
| **O(r × d × log(rd)) time** | Fast enough for real-time allocation |
| **O(r × d) space** | Reasonable memory for typical workloads |
| **Weekly granularity** | Respects availability windows |
| **Audit trail** | Full tracking of allocation decisions |

---

*Document Version: 1.4*
*Created: 2025-02-18*
*Updated: 2025-02-19*
*Changelog:*
- *v1.1: Added Eligibility Gate section for misfit prevention*
- *v1.2: Clarified weekly granularity for Ideal FTE calculation*
- *v1.3: Added working days weighted distribution (holidays, partial weeks)*
- *v1.4: Added location-aware distribution (each demand uses its locality's calendar, ideal FTE per location group)*
*Author: V2 Architecture Team*
