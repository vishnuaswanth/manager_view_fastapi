# V2 Implementation Proposal: Weekly Capacity & Multi-Group Resource Tracking

## Overview

This document outlines the proposed implementation for enhancing the forecast system to support:
- Multiple resource groups with varying production capacities (100%, 75%, 50%, etc.)
- Week-by-week capacity tracking that aggregates to monthly values
- Flexible resource assignment and reallocation
- Enhanced reporting for PowerBI and JavaScript dashboards

---

## 1. New Database Models

### 1.1 WeekConfigurationModel

**Purpose:** Store week-level configuration for capacity calculations (working days, hours, occupancy, shrinkage per week).

```python
class WeekConfigurationModel(SQLModel, table=True):
    __tablename__ = "week_configuration"

    id: int = Field(primary_key=True)
    year: int                                 # e.g., 2025
    week_number: int                          # ISO week (1-53)
    week_start_date: date                     # Monday of the week
    week_end_date: date                       # Sunday of the week
    month: str                                # Parent month name (e.g., "April")
    work_type: str                            # "Domestic" or "Global"
    working_days: int                         # Typically 5, less for holidays
    work_hours: float                         # e.g., 9
    occupancy: float                          # e.g., 0.95
    shrinkage: float                          # e.g., 0.10

    # Unique: (year, week_number, work_type)
```

**Questions for Review:**
- Should we auto-generate week configurations from MonthConfigurationModel?
- Do you need different work_hours per week (e.g., shorter weeks)?

---

### 1.2 ProductionCapacityTierModel

**Purpose:** Define standard production capacity tiers (100%, 75%, 50%, etc.).

```python
class ProductionCapacityTierModel(SQLModel, table=True):
    __tablename__ = "production_capacity_tier"

    id: int = Field(primary_key=True)
    tier_name: str                            # "Full Production", "75% Ramp", "50% Ramp", "Training"
    capacity_percentage: float                # 1.0, 0.75, 0.50, 0.25
    description: str
    is_active: bool = True
    display_order: int                        # For UI ordering

    # Unique: tier_name
```

**Default Tiers (seeded on startup):**
| Tier Name | Percentage | Description |
|-----------|------------|-------------|
| Full Production | 100% | Fully ramped resources |
| 75% Ramp | 75% | Resources in final ramp stage |
| 50% Ramp | 50% | Resources mid-ramp |
| 25% Ramp | 25% | Resources in early ramp/training |

**Questions for Review:**
- Are these tiers correct? Need more/fewer?
- Should users be able to add custom tiers via API?

---

### 1.3 ResourceModel

**Purpose:** Master resource table - one row per unique person (replaces/extends ProdTeamRosterModel for V2).

```python
class ResourceModel(SQLModel, table=True):
    __tablename__ = "resource_v2"

    id: int = Field(primary_key=True)
    cn: str                                   # Unique identifier (CN#)
    first_name: str
    last_name: str
    opid: str

    # Skills and capabilities
    primary_platform: str                     # "Amisys", "Facets"
    location: str                             # "Domestic", "Global"
    state_list: str                           # Pipe-delimited: "FL|GA|TX"
    skills: str                               # Comma-separated case types

    # Current status
    is_active: bool = True
    hire_date: date

    # Audit
    created_datetime: datetime
    updated_datetime: datetime

    # Unique: cn
```

**Migration Note:** Will import from existing ProdTeamRosterModel data.

---

### 1.4 WeeklyResourceAssignmentModel

**Purpose:** Weekly assignment of resources to demands with capacity tracking. This is the core transactional table.

```python
class WeeklyResourceAssignmentModel(SQLModel, table=True):
    __tablename__ = "weekly_resource_assignment"

    id: int = Field(primary_key=True)

    # Time context
    year: int
    week_number: int                          # ISO week
    report_month: str                         # Parent report month
    report_year: int
    forecast_month_index: int                 # Which of the 6 forecast months (1-6)

    # Resource reference
    resource_cn: str                          # FK to ResourceModel.cn

    # Demand reference (composite key to ForecastModel)
    demand_main_lob: str
    demand_state: str
    demand_case_type: str

    # Capacity tier
    capacity_tier_id: int                     # FK to ProductionCapacityTierModel
    production_percentage: float              # Actual percentage (0.0-1.0)

    # Calculated values (denormalized for query performance)
    weekly_capacity: float                    # Calculated weekly output

    # Assignment metadata
    assignment_type: str                      # "primary", "bench", "manual"
    assigned_by: str
    assigned_datetime: datetime

    # Soft delete for history
    is_active: bool = True
    deallocated_datetime: datetime = None
    deallocated_by: str = None

    # UNIQUE: (resource_cn, year, week_number) - one assignment per resource per week
```

**Key Design Decision (Confirmed):**
- One assignment per resource per week (no split assignments)
- Production percentage applies for entire week
- Changes take effect at week boundaries

---

### 1.5 MonthlyCapacitySummaryModel

**Purpose:** Pre-aggregated monthly capacity (materialized view pattern for fast reporting).

```python
class MonthlyCapacitySummaryModel(SQLModel, table=True):
    __tablename__ = "monthly_capacity_summary"

    id: int = Field(primary_key=True)

    # Report context
    report_month: str
    report_year: int
    forecast_month_index: int                 # 1-6
    forecast_month: str                       # Actual month name
    forecast_year: int

    # Demand identification
    main_lob: str
    state: str
    case_type: str

    # Aggregated metrics (sum of weekly values)
    total_forecast: int                       # From ForecastModel
    total_fte_count: int                      # Count of unique resources
    total_fte_equivalent: float               # Sum of production_percentage
    total_capacity: float                     # Sum of weekly_capacity

    # Derived metrics
    fte_required: int                         # Calculated from forecast
    capacity_gap: float                       # capacity - forecast

    # Breakdown by capacity tier (JSON)
    tier_breakdown: str                       # JSON: {"100%": 15, "75%": 12, "50%": 20}

    # Computed timestamp
    computed_datetime: datetime
```

**Aggregation Strategy:**
- Recomputed when weekly assignments change
- Can be triggered manually or on schedule
- Used by reporting endpoints for fast queries

---

## 2. New API Endpoints

### 2.1 Resource Management (`/api/v2/resources`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v2/resources` | List resources with filters (platform, location, active) |
| GET | `/api/v2/resources/{cn}` | Get single resource by CN |
| POST | `/api/v2/resources` | Create new resource |
| PUT | `/api/v2/resources/{cn}` | Update resource details |
| DELETE | `/api/v2/resources/{cn}` | Deactivate resource (soft delete) |
| POST | `/api/v2/resources/bulk-import` | Import from roster file |

### 2.2 Weekly Assignment Management (`/api/v2/assignments`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v2/assignments` | List assignments with filters (week, resource, demand) |
| GET | `/api/v2/assignments/{id}` | Get single assignment |
| POST | `/api/v2/assignments` | Create assignment (assign resource to demand) |
| PUT | `/api/v2/assignments/{id}` | Update assignment (change production %) |
| DELETE | `/api/v2/assignments/{id}` | Deallocate (soft delete) |
| POST | `/api/v2/assignments/bulk` | Bulk assign resources |

### 2.3 Capacity Tier Management (`/api/v2/capacity-tiers`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v2/capacity-tiers` | List all tiers |
| POST | `/api/v2/capacity-tiers` | Add new tier |
| PUT | `/api/v2/capacity-tiers/{id}` | Update tier |
| DELETE | `/api/v2/capacity-tiers/{id}` | Deactivate tier |

### 2.4 Week Configuration (`/api/v2/week-config`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v2/week-config` | Get week configs by year/month |
| POST | `/api/v2/week-config` | Set week parameters |
| POST | `/api/v2/week-config/generate` | Auto-generate from month config |

### 2.5 Reporting Endpoints (`/api/v2/reports`)

| Method | Endpoint | Description | Format |
|--------|----------|-------------|--------|
| GET | `/api/v2/reports/powerbi/monthly-summary` | Monthly summary flat table | PowerBI (flat) |
| GET | `/api/v2/reports/powerbi/weekly-detail` | Weekly detail flat table | PowerBI (flat) |
| GET | `/api/v2/reports/powerbi/resource-assignments` | Resource assignments flat | PowerBI (flat) |
| GET | `/api/v2/reports/dashboard/hierarchy` | Hierarchical data | JavaScript (nested JSON) |
| GET | `/api/v2/reports/dashboard/charts-data` | Chart-ready data | JavaScript (nested JSON) |
| GET | `/api/v2/reports/capacity-by-tier` | Breakdown by production % | Both formats |
| GET | `/api/v2/reports/comparison` | Current vs prior month | Both formats |

### 2.6 Allocation V2 (`/api/v2/allocation`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v2/allocation/execute` | Run allocation with tier awareness |
| GET | `/api/v2/allocation/preview` | Preview allocation without committing |
| POST | `/api/v2/allocation/rebalance` | Rebalance existing assignments |

---

## 3. Capacity Calculation Logic

### 3.1 Weekly Capacity Formula

```python
def calculate_weekly_capacity(
    production_percentage: float,    # 0.0 - 1.0
    working_days: int,               # e.g., 5
    work_hours: float,               # e.g., 9
    shrinkage: float,                # e.g., 0.10
    target_cph: float                # e.g., 12.5
) -> float:
    """
    Weekly capacity for a single resource at given production level.
    """
    return (
        production_percentage *
        working_days *
        work_hours *
        (1 - shrinkage) *
        target_cph
    )
```

### 3.2 Monthly Capacity Aggregation

```python
def calculate_monthly_capacity(
    weekly_assignments: List[WeeklyResourceAssignment],
    week_configs: Dict[int, WeekConfiguration]
) -> MonthlyCapacitySummary:
    """
    Sum weekly capacities for all weeks in the month.
    """
    total_capacity = sum(
        calculate_weekly_capacity(
            assignment.production_percentage,
            week_configs[assignment.week_number].working_days,
            week_configs[assignment.week_number].work_hours,
            week_configs[assignment.week_number].shrinkage,
            target_cph
        )
        for assignment in weekly_assignments
    )
    return total_capacity
```

### 3.3 Tier Breakdown Calculation

```python
def calculate_tier_breakdown(
    assignments: List[WeeklyResourceAssignment],
    tiers: List[ProductionCapacityTier]
) -> Dict[str, int]:
    """
    Count resources by capacity tier.
    Returns: {"100%": 15, "75%": 12, "50%": 20, "25%": 5}
    """
    breakdown = {}
    for tier in tiers:
        count = sum(
            1 for a in assignments
            if a.capacity_tier_id == tier.id
        )
        breakdown[tier.tier_name] = count
    return breakdown
```

---

## 4. Report Format Examples

### 4.1 PowerBI Format (Flat Table)

```json
{
  "columns": ["main_lob", "case_type", "state", "month", "forecast", "fte_count", "fte_equivalent", "capacity", "gap", "tier_100", "tier_75", "tier_50", "tier_25"],
  "rows": [
    ["Amisys Medicaid Domestic", "Claims Processing", "FL", "May-25", 5000, 47, 37.0, 4800, -200, 15, 12, 15, 5],
    ["Amisys Medicaid Domestic", "Claims Processing", "FL", "Jun-25", 5200, 50, 40.0, 5100, -100, 18, 12, 15, 5]
  ]
}
```

### 4.2 JavaScript Dashboard Format (Nested JSON)

```json
{
  "categories": [
    {
      "id": "amisys-onshore",
      "name": "Amisys Onshore",
      "metrics": {
        "forecast": 50000,
        "capacity": 48000,
        "gap": -2000,
        "fte_count": 150,
        "fte_equivalent": 125.5
      },
      "tier_breakdown": {
        "100%": 50,
        "75%": 40,
        "50%": 45,
        "25%": 15
      },
      "children": [
        {
          "id": "amisys-onshore-fl",
          "name": "Florida",
          "metrics": {...},
          "tier_breakdown": {...}
        }
      ]
    }
  ],
  "months": ["May-25", "Jun-25", "Jul-25", "Aug-25", "Sep-25", "Oct-25"],
  "chart_series": {
    "forecast_trend": [50000, 52000, 54000, 53000, 51000, 50000],
    "capacity_trend": [48000, 50000, 52000, 52000, 51000, 50000]
  }
}
```

---

## 5. File Structure

### 5.1 New Files to Create

```
code/
├── logics/
│   ├── models_v2.py                  # V2 database models
│   ├── capacity_calculations_v2.py   # Weekly/monthly capacity logic
│   ├── allocation_v2.py              # V2 allocation algorithm
│   └── aggregation_utils.py          # Monthly aggregation helpers
├── api/
│   └── routers/
│       ├── resource_router_v2.py     # Resource CRUD
│       ├── assignment_router_v2.py   # Assignment CRUD
│       ├── capacity_tier_router.py   # Tier management
│       ├── week_config_router.py     # Week configuration
│       └── reports_router_v2.py      # V2 reporting endpoints
└── tests/
    ├── test_capacity_calculations_v2.py
    ├── test_allocation_v2.py
    └── test_reports_v2.py
```

### 5.2 Modified Files

| File | Changes |
|------|---------|
| `code/main.py` | Register V2 routers with `/api/v2` prefix |
| `code/logics/db.py` | Add V2 models (or import from models_v2.py) |
| `code/api/dependencies.py` | Add V2 dependencies if needed |

---

## 6. Migration Strategy

### 6.1 Data Migration

1. **ResourceModel**: Import from existing `ProdTeamRosterModel`
   - Map CN, names, platform, location, state, skills
   - Set is_active based on PartofProduction

2. **WeeklyResourceAssignmentModel**: Import from existing `FTEAllocationMappingModel`
   - Convert monthly allocations to weekly
   - Initially set all to 100% production tier

3. **MonthlyCapacitySummaryModel**: Compute from existing ForecastModel + new assignments

### 6.2 Rollout Phases

| Phase | Duration | Description |
|-------|----------|-------------|
| Phase 1 | Week 1-2 | Create V2 tables, seed tiers, write migration scripts |
| Phase 2 | Week 3-4 | Implement core calculation logic, unit tests |
| Phase 3 | Week 5-6 | Create V2 API endpoints |
| Phase 4 | Week 7-8 | Implement reporting endpoints |
| Phase 5 | Week 9-10 | Integration testing, bug fixes |

---

## 7. Questions for Review

### Data Model Questions

1. **Week Configuration Generation:**
   - Should we auto-generate week configs from month configs?
   - Or require manual entry for each week?

2. **Capacity Tiers:**
   - Are the default tiers (100%, 75%, 50%, 25%) sufficient?
   - Should users be able to create custom tiers?

3. **Resource Model:**
   - Should V2 resources be separate from V1 ProdTeamRosterModel?
   - Or should we extend the existing model?

### API Questions

4. **Versioning Strategy:**
   - Keep V1 endpoints running indefinitely?
   - Or deprecate after X months?

5. **Report Formats:**
   - Are the proposed PowerBI/JavaScript formats correct?
   - Any additional fields needed?

### Business Logic Questions

6. **Assignment Changes:**
   - When a resource's production % changes mid-week, does it apply:
     - From next week? (current proposal)
     - Immediately (pro-rated)?

7. **Historical Data:**
   - How far back should we migrate existing allocations?
   - Should we keep V1 allocation history separate?

---

## 8. Approval Checklist

Please review and confirm:

- [ ] Database models structure is acceptable
- [ ] API endpoint design is acceptable
- [ ] Capacity calculation formulas are correct
- [ ] Report formats meet requirements
- [ ] Migration strategy is acceptable
- [ ] Questions above are answered

---

## Next Steps

Once approved, I will:

1. Create V2 database models in `code/logics/models_v2.py`
2. Implement capacity calculation functions
3. Create API routers for V2 endpoints
4. Add reporting endpoints
5. Register routers in main.py
6. Write unit tests
7. Create migration scripts

---

*Document Version: 1.0*
*Created: 2026-02-18*
