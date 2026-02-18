# V2 Implementation Proposal: Weekly Capacity & Multi-Group Resource Tracking

## Overview

This document outlines the proposed implementation for enhancing the forecast system to support:
- Multiple resource groups with varying production capacities (100%, 75%, 50%, etc.)
- Week-by-week capacity tracking that aggregates to monthly values
- **Placeholder/Tentative resources** for future planning (TBH-001, TBH-002, etc.)
- Flexible resource assignment and reallocation
- Enhanced reporting for PowerBI and JavaScript dashboards

---

## Confirmed Design Decisions

Based on user feedback, the following design decisions are **confirmed**:

| Decision | Choice | Impact |
|----------|--------|--------|
| Production % Changes | Week-level granularity | Percentage applies for the whole week, changes take effect at week boundaries |
| Resource Assignment | Single assignment per resource per week | Unique constraint: (resource_cn, year, week_number) |
| Dashboard Formats | Support both PowerBI (flat) and JavaScript (nested JSON) | Dual endpoint formats for reporting |
| Placeholder Resources | Supported | TBH-001 style placeholders that can be converted to actual people |

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

---

### 1.3 ResourceModel (with Placeholder Support)

**Purpose:** Master resource table supporting both **actual people** and **placeholder/tentative resources** for future planning.

```python
class ResourceModel(SQLModel, table=True):
    __tablename__ = "resource_v2"

    id: int = Field(primary_key=True)
    cn: str                                   # "CN12345" (actual) or "TBH-001" (placeholder)

    # Resource type - KEY FIELD
    resource_type: str                        # "actual" | "placeholder"
    display_name: str                         # "John Smith" or "Planned Hire - Claims"

    # Personal info (NULL for placeholders)
    first_name: Optional[str]
    last_name: Optional[str]
    opid: Optional[str]

    # Skills and capabilities (REQUIRED for both types - used for matching)
    primary_platform: str                     # "Amisys", "Facets"
    location: str                             # "Domestic", "Global"
    state_list: str                           # Pipe-delimited: "FL|GA|TX"
    skills: str                               # Comma-separated case types

    # Current status
    is_active: bool = True
    hire_date: Optional[date]                 # NULL for placeholders

    # Placeholder-specific fields
    created_for_week: Optional[int]           # Week this placeholder was created for
    created_for_year: Optional[int]
    replaced_by_cn: Optional[str]             # When converted, link to actual CN
    replaced_at: Optional[datetime]

    # Audit
    created_datetime: datetime
    updated_datetime: datetime

    # Unique: cn
```

**Key Points:**
- `resource_type="actual"`: Real people with CN numbers (e.g., CN12345)
- `resource_type="placeholder"`: Tentative/planned resources (e.g., TBH-001, TBH-002)
- Placeholders have the same skills/platform/location as actual resources (required for allocation matching)
- When a placeholder is converted to an actual person, `replaced_by_cn` tracks the link

---

### 1.4 WeeklyResourceAssignmentModel

**Purpose:** Weekly assignment of resources (actual + placeholder) to demands with capacity tracking. This is the core transactional table.

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
    resource_cn: str                          # FK to ResourceModel.cn (actual or placeholder)

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
- Works identically for actual and placeholder resources

---

### 1.5 MonthlyCapacitySummaryModel (with Actual/Placeholder Breakdown)

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
    total_fte_count: int                      # Count of unique resources (actual + placeholder)
    actual_fte_count: int                     # Count of actual resources only
    placeholder_fte_count: int                # Count of placeholder resources only
    total_fte_equivalent: float               # Sum of production_percentage
    actual_fte_equivalent: float              # Actual resources only
    placeholder_fte_equivalent: float         # Placeholder resources only
    total_capacity: float                     # Sum of weekly_capacity

    # Derived metrics
    fte_required: int                         # Calculated from forecast
    capacity_gap: float                       # capacity - forecast

    # Breakdown by capacity tier (JSON with actual/placeholder split)
    tier_breakdown: str                       # JSON (see format below)

    # Computed timestamp
    computed_datetime: datetime
```

**Tier Breakdown JSON Format:**
```json
{
  "tiers": [
    {"tier_name": "Full Production", "percentage": 1.0, "actual": 15, "placeholder": 0, "total": 15, "capacity": 6750},
    {"tier_name": "75% Ramp", "percentage": 0.75, "actual": 8, "placeholder": 5, "total": 13, "capacity": 4387.5},
    {"tier_name": "50% Ramp", "percentage": 0.5, "actual": 5, "placeholder": 10, "total": 15, "capacity": 3375},
    {"tier_name": "25% Ramp", "percentage": 0.25, "actual": 2, "placeholder": 3, "total": 5, "capacity": 562.5}
  ],
  "totals": {
    "actual_headcount": 30,
    "placeholder_headcount": 18,
    "total_headcount": 48,
    "actual_fte_equivalent": 28.5,
    "placeholder_fte_equivalent": 11.25,
    "total_fte_equivalent": 39.75,
    "total_capacity": 15075
  }
}
```

---

## 2. New API Endpoints

### 2.1 Resource Management (`/api/v2/resources`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v2/resources` | List resources with filters (platform, location, active, resource_type) |
| GET | `/api/v2/resources/{cn}` | Get single resource by CN |
| POST | `/api/v2/resources` | Create new actual resource |
| PUT | `/api/v2/resources/{cn}` | Update resource details |
| DELETE | `/api/v2/resources/{cn}` | Deactivate resource (soft delete) |
| POST | `/api/v2/resources/bulk-import` | Import from roster file |

### 2.2 Placeholder Resource Management (`/api/v2/resources/placeholders`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v2/resources/placeholders` | Create placeholder resources (batch) |
| GET | `/api/v2/resources/placeholders` | List placeholders with filters |
| POST | `/api/v2/resources/{placeholder_cn}/convert` | Convert placeholder to actual resource |
| DELETE | `/api/v2/resources/placeholders/{cn}` | Remove placeholder |

**Create Placeholders Request:**
```json
{
    "count": 5,
    "platform": "Amisys",
    "location": "Domestic",
    "skills": "Claims Processing",
    "state_list": "FL|GA|TX",
    "display_name_prefix": "Planned Hire - Claims"
}
```

**Response:**
```json
{
    "created": ["TBH-001", "TBH-002", "TBH-003", "TBH-004", "TBH-005"]
}
```

**Convert Placeholder Request:**
```json
{
    "actual_cn": "CN12345",
    "first_name": "John",
    "last_name": "Smith",
    "transfer_assignments": true
}
```

### 2.3 Weekly Assignment Management (`/api/v2/assignments`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v2/assignments` | List assignments with filters (week, resource, demand) |
| GET | `/api/v2/assignments/{id}` | Get single assignment |
| POST | `/api/v2/assignments` | Create assignment (assign resource to demand) |
| PUT | `/api/v2/assignments/{id}` | Update assignment (change production %) |
| DELETE | `/api/v2/assignments/{id}` | Deallocate (soft delete) |
| POST | `/api/v2/assignments/bulk` | Bulk assign resources |
| POST | `/api/v2/assignments/bulk-placeholders` | Bulk assign placeholders to demand |

### 2.4 Auto-Generation: Set Week Targets (`/api/v2/assignments/set-week-targets`)

**Purpose:** User enters target headcount per tier, system auto-creates placeholders to fill gaps.

**Request:**
```json
{
    "week_number": 12,
    "year": 2025,
    "forecast_month_index": 3,
    "demand_main_lob": "Amisys Medicaid Domestic",
    "demand_state": "FL",
    "demand_case_type": "Claims Processing",
    "targets": [
        {"capacity_tier_id": 1, "target_count": 25},
        {"capacity_tier_id": 2, "target_count": 15},
        {"capacity_tier_id": 3, "target_count": 10}
    ]
}
```

**Response:**
```json
{
    "week_number": 12,
    "demand": "Amisys Medicaid Domestic / FL / Claims Processing",
    "results": [
        {
            "tier": "100%",
            "target": 25,
            "actual_existing": 20,
            "placeholders_existing": 0,
            "placeholders_created": 5,
            "final_total": 25
        },
        {
            "tier": "75%",
            "target": 15,
            "actual_existing": 8,
            "placeholders_existing": 0,
            "placeholders_created": 7,
            "final_total": 15
        },
        {
            "tier": "50%",
            "target": 10,
            "actual_existing": 3,
            "placeholders_existing": 0,
            "placeholders_created": 7,
            "final_total": 10
        }
    ],
    "placeholders_created": ["TBH-001", "TBH-002", "...", "TBH-019"]
}
```

**Auto-Generation Logic:**
1. Get current assignments for week/demand
2. Group by capacity tier
3. For each tier:
   - Count actual + existing placeholders
   - If count < target: create new placeholders
   - If count > target: deactivate excess placeholders (FIFO, never deactivate actual resources)
4. Return summary

**Important:** If target is below actual resource count, system returns warning and does not deactivate actual resources.

### 2.5 Capacity Tier Management (`/api/v2/capacity-tiers`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v2/capacity-tiers` | List all tiers |
| POST | `/api/v2/capacity-tiers` | Add new tier |
| PUT | `/api/v2/capacity-tiers/{id}` | Update tier |
| DELETE | `/api/v2/capacity-tiers/{id}` | Deactivate tier |

### 2.6 Week Configuration (`/api/v2/week-config`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v2/week-config` | Get week configs by year/month |
| POST | `/api/v2/week-config` | Set week parameters |
| POST | `/api/v2/week-config/generate` | Auto-generate from month config |

### 2.7 Reporting Endpoints (`/api/v2/reports`)

| Method | Endpoint | Description | Format |
|--------|----------|-------------|--------|
| GET | `/api/v2/reports/powerbi/monthly-summary` | Monthly summary flat table | PowerBI (flat) |
| GET | `/api/v2/reports/powerbi/weekly-detail` | Weekly detail flat table | PowerBI (flat) |
| GET | `/api/v2/reports/powerbi/resource-assignments` | Resource assignments flat | PowerBI (flat) |
| GET | `/api/v2/reports/dashboard/hierarchy` | Hierarchical data | JavaScript (nested JSON) |
| GET | `/api/v2/reports/dashboard/charts-data` | Chart-ready data | JavaScript (nested JSON) |
| GET | `/api/v2/reports/capacity-by-tier` | Breakdown by production % | Both formats |
| GET | `/api/v2/reports/comparison` | Current vs prior month | Both formats |

**All reports include actual vs placeholder breakdown.**

### 2.8 Allocation V2 (`/api/v2/allocation`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v2/allocation/execute` | Run allocation with tier awareness |
| GET | `/api/v2/allocation/preview` | Preview allocation without committing |
| POST | `/api/v2/allocation/rebalance` | Rebalance existing assignments |

---

## 3. Capacity Calculation Logic

### 3.1 Weekly Capacity Formula

**Same formula for both actual and placeholder resources:**

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
    Works identically for actual and placeholder resources.
    """
    return (
        production_percentage *
        working_days *
        work_hours *
        (1 - shrinkage) *
        target_cph
    )

# Examples:
# Actual resource CN12345 at 100%: 1.0 × 5 × 9 × 0.9 × 12.5 = 506.25
# Placeholder TBH-001 at 75%: 0.75 × 5 × 9 × 0.9 × 12.5 = 379.69
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

### 3.3 Tier Breakdown Calculation (with Actual/Placeholder Split)

```python
def calculate_tier_breakdown(
    assignments: List[WeeklyResourceAssignment],
    resources: Dict[str, ResourceModel],
    tiers: List[ProductionCapacityTier]
) -> Dict:
    """
    Count resources by capacity tier with actual/placeholder split.
    """
    breakdown = {"tiers": [], "totals": {}}

    for tier in tiers:
        tier_assignments = [a for a in assignments if a.capacity_tier_id == tier.id]
        actual_count = sum(1 for a in tier_assignments if resources[a.resource_cn].resource_type == "actual")
        placeholder_count = sum(1 for a in tier_assignments if resources[a.resource_cn].resource_type == "placeholder")

        breakdown["tiers"].append({
            "tier_name": tier.tier_name,
            "percentage": tier.capacity_percentage,
            "actual": actual_count,
            "placeholder": placeholder_count,
            "total": actual_count + placeholder_count
        })

    # Calculate totals
    breakdown["totals"] = {
        "actual_headcount": sum(t["actual"] for t in breakdown["tiers"]),
        "placeholder_headcount": sum(t["placeholder"] for t in breakdown["tiers"]),
        "total_headcount": sum(t["total"] for t in breakdown["tiers"])
    }

    return breakdown
```

---

## 4. Report Format Examples

### 4.1 PowerBI Format (Flat Table with Actual/Placeholder Columns)

```json
{
  "columns": [
    "main_lob", "case_type", "state", "month", "forecast",
    "fte_count", "actual_count", "placeholder_count",
    "fte_equivalent", "actual_equivalent", "placeholder_equivalent",
    "capacity", "gap",
    "tier_100_actual", "tier_100_placeholder",
    "tier_75_actual", "tier_75_placeholder",
    "tier_50_actual", "tier_50_placeholder",
    "tier_25_actual", "tier_25_placeholder"
  ],
  "rows": [
    ["Amisys Medicaid Domestic", "Claims Processing", "FL", "May-25", 5000,
     47, 30, 17, 37.0, 28.5, 8.5, 4800, -200,
     15, 0, 8, 4, 5, 8, 2, 5],
    ["Amisys Medicaid Domestic", "Claims Processing", "FL", "Jun-25", 5200,
     50, 32, 18, 40.0, 30.0, 10.0, 5100, -100,
     18, 0, 8, 4, 4, 10, 2, 4]
  ]
}
```

### 4.2 JavaScript Dashboard Format (Nested JSON with Actual/Placeholder)

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
        "actual_count": 100,
        "placeholder_count": 50,
        "fte_equivalent": 125.5,
        "actual_equivalent": 95.0,
        "placeholder_equivalent": 30.5
      },
      "tier_breakdown": {
        "100%": {"actual": 50, "placeholder": 0, "total": 50},
        "75%": {"actual": 30, "placeholder": 10, "total": 40},
        "50%": {"actual": 15, "placeholder": 30, "total": 45},
        "25%": {"actual": 5, "placeholder": 10, "total": 15}
      },
      "children": [...]
    }
  ],
  "months": ["May-25", "Jun-25", "Jul-25", "Aug-25", "Sep-25", "Oct-25"],
  "chart_series": {
    "forecast_trend": [50000, 52000, 54000, 53000, 51000, 50000],
    "capacity_trend": [48000, 50000, 52000, 52000, 51000, 50000],
    "actual_capacity_trend": [40000, 42000, 44000, 45000, 45000, 45000],
    "placeholder_capacity_trend": [8000, 8000, 8000, 7000, 6000, 5000]
  }
}
```

---

## 5. Week-by-Week Planning Example

**Scenario:** Planning for Month 3 (June 2025) - 4 weeks

```
Week 1 (June 2-6):
  - Actual resources: 20 at 100%
  - Placeholders: 0
  - Total capacity: 20 × 100% = 20.0 FTE equivalent

Week 2 (June 9-13):
  - Actual resources: 20 at 100%
  - Placeholders: 5 at 50% (new hires starting)
  - Total capacity: 20 + 2.5 = 22.5 FTE equivalent

Week 3 (June 16-20):
  - Actual resources: 20 at 100%
  - Placeholders: 5 at 75% (ramping up)
  - Total capacity: 20 + 3.75 = 23.75 FTE equivalent

Week 4 (June 23-27):
  - Actual resources: 20 at 100%
  - Placeholders: 5 at 100% (fully ramped) + 3 at 50% (more hires)
  - Total capacity: 20 + 5 + 1.5 = 26.5 FTE equivalent

Monthly Total: Sum of all weekly capacities
```

---

## 6. File Structure

### 6.1 New Files to Create

```
code/
├── logics/
│   ├── models_v2.py                  # V2 database models (with placeholder support)
│   ├── capacity_calculations_v2.py   # Weekly/monthly capacity logic
│   ├── placeholder_utils.py          # Placeholder creation, conversion, auto-generation
│   ├── allocation_v2.py              # V2 allocation algorithm
│   └── aggregation_utils.py          # Monthly aggregation helpers
├── api/
│   └── routers/
│       ├── resource_router_v2.py     # Resource + Placeholder CRUD
│       ├── assignment_router_v2.py   # Assignment CRUD + set-week-targets
│       ├── capacity_tier_router.py   # Tier management
│       ├── week_config_router.py     # Week configuration
│       └── reports_router_v2.py      # V2 reporting endpoints (PowerBI + JS)
└── tests/
    ├── test_capacity_calculations_v2.py
    ├── test_placeholder_utils.py
    ├── test_allocation_v2.py
    └── test_reports_v2.py
```

### 6.2 Modified Files

| File | Changes |
|------|---------|
| `code/main.py` | Register V2 routers with `/api/v2` prefix |
| `code/logics/db.py` | Add V2 models (or import from models_v2.py) |
| `code/api/dependencies.py` | Add V2 dependencies if needed |

---

## 7. Migration Strategy

### 7.1 Data Migration

1. **ResourceModel**: Import from existing `ProdTeamRosterModel`
   - Map CN, names, platform, location, state, skills
   - Set `resource_type = "actual"` for all imported
   - Set is_active based on PartofProduction

2. **WeeklyResourceAssignmentModel**: Import from existing `FTEAllocationMappingModel`
   - Convert monthly allocations to weekly
   - Initially set all to 100% production tier

3. **MonthlyCapacitySummaryModel**: Compute from existing ForecastModel + new assignments
   - Set `placeholder_fte_count = 0` initially

### 7.2 Rollout Phases

| Phase | Duration | Description |
|-------|----------|-------------|
| Phase 1 | Week 1-2 | Create V2 tables, seed tiers, write migration scripts, implement placeholder utils |
| Phase 2 | Week 3-4 | Implement core calculation logic (with actual/placeholder split), unit tests |
| Phase 3 | Week 5-6 | Create V2 API endpoints including set-week-targets |
| Phase 4 | Week 7-8 | Implement reporting endpoints (PowerBI + JS formats) |
| Phase 5 | Week 9-10 | Integration testing, bug fixes |

---

## 8. Implementation Checklist

### Phase 1: Foundation (Weeks 1-2)
- [ ] Create WeekConfigurationModel
- [ ] Create ProductionCapacityTierModel
- [ ] Create ResourceModel (with resource_type: actual/placeholder)
- [ ] Create WeeklyResourceAssignmentModel (with unique constraint)
- [ ] Create MonthlyCapacitySummaryModel (with actual/placeholder breakdown)
- [ ] Seed default capacity tiers (100%, 75%, 50%, 25%)
- [ ] Implement placeholder CN generator (TBH-001, TBH-002, etc.)
- [ ] Write migration script for existing roster data

### Phase 2: Core Logic (Weeks 3-4)
- [ ] Implement weekly capacity calculation (same for actual + placeholder)
- [ ] Implement monthly aggregation (sum of weeks)
- [ ] Implement tier breakdown calculation (with actual/placeholder split)
- [ ] Implement placeholder creation logic
- [ ] Implement placeholder-to-actual conversion logic
- [ ] Implement auto-generation logic (set-week-targets)
- [ ] Unit tests for all calculations

### Phase 3: API Development (Weeks 5-6)
- [ ] Resource CRUD endpoints (actual resources)
- [ ] Placeholder resource endpoints (create, list, convert)
- [ ] Assignment CRUD endpoints (with single-assignment validation)
- [ ] Bulk placeholder assignment endpoint
- [ ] Set-week-targets endpoint (auto-generation)
- [ ] Week config endpoints
- [ ] Capacity tier endpoints
- [ ] API tests

### Phase 4: Reporting (Weeks 7-8)
- [ ] PowerBI flat format endpoints (with actual/placeholder columns)
- [ ] JavaScript nested JSON endpoints
- [ ] Monthly summary with tier breakdown (actual vs placeholder)
- [ ] Prior month comparison
- [ ] Excel export with placeholder indicators

### Phase 5: Integration (Weeks 9-10)
- [ ] Manager view V2 integration
- [ ] End-to-end testing
- [ ] Performance optimization
- [ ] Documentation
- [ ] User acceptance testing

---

## 9. Approval Checklist

Please review and confirm:

- [ ] Database models structure is acceptable (including placeholder support)
- [ ] API endpoint design is acceptable (including set-week-targets)
- [ ] Capacity calculation formulas are correct (same for actual/placeholder)
- [ ] Report formats meet requirements (actual/placeholder breakdown)
- [ ] Migration strategy is acceptable
- [ ] Auto-generation logic is acceptable

---

## Next Steps

Once approved, I will:

1. Create V2 database models in `code/logics/models_v2.py`
2. Implement placeholder utilities in `code/logics/placeholder_utils.py`
3. Implement capacity calculation functions
4. Create API routers for V2 endpoints
5. Add reporting endpoints (both formats)
6. Register routers in main.py
7. Write unit tests
8. Create migration scripts

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-18 | Initial proposal |
| 2.0 | 2026-02-18 | Added placeholder/tentative resource support, auto-generation API, actual/placeholder breakdown in reports, confirmed design decisions |

---

*Document Version: 2.0*
*Created: 2026-02-18*
*Last Updated: 2026-02-18*
