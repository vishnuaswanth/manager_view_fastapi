# V2 Implementation Proposal: Weekly Capacity & Multi-Group Resource Tracking

---

# PART A: Management Overview

*Quick read for stakeholders - Key decisions, assumptions, and business policies*

---

## Executive Summary

This V2 implementation enhances the Centene Forecasting system to support:

| Feature | Benefit |
|---------|---------|
| **Week-by-week capacity tracking** | Granular planning that aggregates to monthly values |
| **Multiple production capacity tiers** | Track resources at 100%, 75%, 50%, 25% productivity |
| **Placeholder/Tentative resources** | Plan future hires (TBH-001, TBH-002) before actual people are hired |
| **Resource availability windows** | Define when resources become available and when they leave |
| **Configurable business policies** | System adapts to changing business rules without code changes |
| **Dual reporting formats** | PowerBI (flat tables) and JavaScript dashboards (nested JSON) |

---

## Key Decisions & Rationale

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | **Production % Granularity** | Week-level | Percentage applies for the whole week; changes take effect at week boundaries. Simpler than daily tracking while still capturing ramp progression. |
| 2 | **Resource Assignment Constraint** | One assignment per resource per week | Unique constraint `(resource_cn, year, week_number)` prevents double-booking and simplifies capacity calculations. |
| 3 | **Placeholder Support** | TBH-001 style placeholders | Enables forward planning with tentative resources that convert to actual people when hired. |
| 4 | **Availability Window** | `available_from` and `available_until` dates | Resources auto-exclude from allocation outside their availability window. Handles start dates, end dates, and leaves. |
| 5 | **Policy Configuration** | Database-driven policies | Business rules stored in `AvailabilityPolicyModel` allow behavior changes without code deployment. |
| 6 | **Report Formats** | Dual format support | PowerBI needs flat tables; JavaScript dashboards need nested JSON. Both include actual vs placeholder breakdown. |

---

## Assumptions

| # | Assumption | Impact if Wrong | Mitigation |
|---|------------|-----------------|------------|
| A1 | Week boundaries align with ISO weeks (Monday-Sunday) | Capacity calculations would be inconsistent | Week start/end dates stored explicitly in `WeekConfigurationModel` |
| A2 | Resources work for a single demand per week | Cannot split a person across multiple demands in same week | Constraint enforced at database level; business process handles exceptions |
| A3 | Placeholder resources have same skills/platform requirements as actual resources | Allocation matching would fail when placeholders convert | Required fields enforced on placeholder creation |
| A4 | Capacity tiers are finite and predefined (100%, 75%, 50%, 25%) | Missed productivity levels | Tiers are configurable via `ProductionCapacityTierModel` |
| A5 | Availability dates are known at resource creation time | Resources may be allocated outside their valid period | Default policy: resources available indefinitely if dates not set |
| A6 | Month configuration exists before week configuration is generated | Week config generation would fail | Validation check before generation; fallback to defaults |

---

## Policies (Configurable Business Rules)

Policies are stored in `AvailabilityPolicyModel` and control system behavior:

### Policy: Availability Window Enforcement

| Policy Key | Default Value | Description |
|------------|---------------|-------------|
| `ENFORCE_AVAILABLE_FROM` | `true` | When `true`, resources cannot be allocated before their `available_from` date |
| `ENFORCE_AVAILABLE_UNTIL` | `true` | When `true`, resources cannot be allocated after their `available_until` date |
| `DEFAULT_AVAILABILITY_DAYS` | `365` | Days a resource is available if no `available_until` is set (from hire/creation date) |
| `PLACEHOLDER_DEFAULT_WEEKS` | `26` | Default number of weeks a placeholder is valid for |

### Policy: Allocation Behavior

| Policy Key | Default Value | Description |
|------------|---------------|-------------|
| `ALLOW_OVER_ALLOCATION` | `false` | When `true`, allows allocating more FTEs than forecast requires |
| `AUTO_CREATE_PLACEHOLDERS` | `true` | When using set-week-targets API, automatically create placeholders to fill gaps |
| `PLACEHOLDER_PREFIX` | `TBH-` | Prefix for auto-generated placeholder CNs (e.g., TBH-001) |
| `MAX_PLACEHOLDERS_PER_REQUEST` | `100` | Maximum placeholders that can be created in a single request |

### Policy: Reporting

| Policy Key | Default Value | Description |
|------------|---------------|-------------|
| `INCLUDE_PLACEHOLDERS_IN_REPORTS` | `true` | When `true`, placeholder resources appear in capacity reports |
| `SEPARATE_PLACEHOLDER_COLUMNS` | `true` | When `true`, reports have separate columns for actual vs placeholder counts |

### Example Policy Usage

```python
# Check if resource is available for a given week
def is_resource_available(resource: ResourceModel, week_start: date, week_end: date) -> bool:
    policy = get_policy("ENFORCE_AVAILABLE_FROM")

    if policy.value == "true" and resource.available_from:
        if week_start < resource.available_from:
            return False

    policy = get_policy("ENFORCE_AVAILABLE_UNTIL")

    if policy.value == "true" and resource.available_until:
        if week_end > resource.available_until:
            return False

    return True
```

---

## Availability Window Feature

### Overview

The **Availability Window** feature allows defining when a resource is available for allocation:

| Field | Type | Description |
|-------|------|-------------|
| `available_from` | `date` | First date the resource can be allocated (e.g., start date, return from leave) |
| `available_until` | `date` | Last date the resource can be allocated (e.g., last day, planned departure) |

### Use Cases

| Scenario | `available_from` | `available_until` |
|----------|------------------|-------------------|
| New hire starting May 1 | `2025-05-01` | `NULL` (indefinite) |
| Contractor ending July 31 | `NULL` (already available) | `2025-07-31` |
| Temp worker June 1-30 | `2025-06-01` | `2025-06-30` |
| Resource on leave April 15-30 | Create separate record or use custom logic | |
| Placeholder for Q3 planning | `2025-07-01` | `2025-09-30` |

### Behavior Rules

1. **NULL `available_from`**: Resource is available immediately (no start restriction)
2. **NULL `available_until`**: Resource is available indefinitely (no end restriction)
3. **Both NULL**: Resource is always available (current behavior, backward compatible)
4. **Allocation outside window**: Resource is excluded from allocation matching
5. **Reports**: Can filter by "currently available" vs "all resources"

---

## Visual Summary: Data Flow

```
Forecast Demand                    Resource Pool
     |                                  |
     v                                  v
+----------------+            +------------------+
| ForecastModel  |            | ResourceModel    |
| - demand data  |            | - actual/placeholder
| - 6 months     |            | - availability window
+----------------+            | - skills/platform
     |                        +------------------+
     |                                  |
     +----------+  Allocation  +--------+
                |   Engine     |
                v              v
       +------------------------+
       | WeeklyResourceAssignment|
       | - resource_cn          |
       | - demand reference     |
       | - capacity tier (%)    |
       | - week context         |
       +------------------------+
                |
                | Aggregation
                v
       +------------------------+
       | MonthlyCapacitySummary |
       | - actual counts        |
       | - placeholder counts   |
       | - tier breakdown       |
       +------------------------+
                |
        +-------+-------+
        |               |
        v               v
   PowerBI          JavaScript
   (flat)           (nested JSON)
```

---

# PART B: Developer Guide

*Detailed technical specifications for implementation*

---

## 1. Data Models

### 1.1 WeekConfigurationModel

**Purpose:** Store week-level configuration for capacity calculations.

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

**Purpose:** Define standard production capacity tiers.

```python
class ProductionCapacityTierModel(SQLModel, table=True):
    __tablename__ = "production_capacity_tier"

    id: int = Field(primary_key=True)
    tier_name: str                            # "Full Production", "75% Ramp", etc.
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

### 1.3 AvailabilityPolicyModel (NEW)

**Purpose:** Store configurable business policies for availability and allocation behavior.

```python
class AvailabilityPolicyModel(SQLModel, table=True):
    __tablename__ = "availability_policy"

    id: int = Field(primary_key=True)
    policy_key: str                           # Unique policy identifier
    policy_value: str                         # Value (string, parsed as needed)
    value_type: str                           # "boolean", "integer", "string", "float"
    description: str                          # Human-readable description
    category: str                             # "availability", "allocation", "reporting"
    is_active: bool = True
    created_datetime: datetime
    updated_datetime: datetime

    # Unique: policy_key
```

**Default Policies (seeded on startup):**

| policy_key | policy_value | value_type | category |
|------------|--------------|------------|----------|
| `ENFORCE_AVAILABLE_FROM` | `true` | boolean | availability |
| `ENFORCE_AVAILABLE_UNTIL` | `true` | boolean | availability |
| `DEFAULT_AVAILABILITY_DAYS` | `365` | integer | availability |
| `PLACEHOLDER_DEFAULT_WEEKS` | `26` | integer | availability |
| `ALLOW_OVER_ALLOCATION` | `false` | boolean | allocation |
| `AUTO_CREATE_PLACEHOLDERS` | `true` | boolean | allocation |
| `PLACEHOLDER_PREFIX` | `TBH-` | string | allocation |
| `MAX_PLACEHOLDERS_PER_REQUEST` | `100` | integer | allocation |
| `INCLUDE_PLACEHOLDERS_IN_REPORTS` | `true` | boolean | reporting |
| `SEPARATE_PLACEHOLDER_COLUMNS` | `true` | boolean | reporting |

---

### 1.4 ResourceModel (with Placeholder & Availability Support)

**Purpose:** Master resource table supporting actual people, placeholders, and availability windows.

```python
class ResourceModel(SQLModel, table=True):
    __tablename__ = "resource_v2"

    id: int = Field(primary_key=True)
    cn: str                                   # "CN12345" (actual) or "TBH-001" (placeholder)

    # Resource type
    resource_type: str                        # "actual" | "placeholder"
    display_name: str                         # "John Smith" or "Planned Hire - Claims"

    # Personal info (NULL for placeholders)
    first_name: Optional[str]
    last_name: Optional[str]
    opid: Optional[str]

    # Skills and capabilities (REQUIRED for both types)
    primary_platform: str                     # "Amisys", "Facets"
    location: str                             # "Domestic", "Global"
    state_list: str                           # Pipe-delimited: "FL|GA|TX"
    skills: str                               # Comma-separated case types

    # Current status
    is_active: bool = True
    hire_date: Optional[date]                 # NULL for placeholders

    # AVAILABILITY WINDOW (NEW)
    available_from: Optional[date]            # First date resource can be allocated
    available_until: Optional[date]           # Last date resource can be allocated

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
- `resource_type="placeholder"`: Tentative/planned resources (e.g., TBH-001)
- `available_from`: Resource cannot be allocated before this date
- `available_until`: Resource cannot be allocated after this date
- Both availability fields are optional; NULL means no restriction

---

### 1.5 WeeklyResourceAssignmentModel

**Purpose:** Weekly assignment of resources to demands with capacity tracking.

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

    # Demand reference
    demand_main_lob: str
    demand_state: str
    demand_case_type: str

    # Capacity tier
    capacity_tier_id: int                     # FK to ProductionCapacityTierModel
    production_percentage: float              # Actual percentage (0.0-1.0)

    # Calculated values
    weekly_capacity: float                    # Calculated weekly output

    # Assignment metadata
    assignment_type: str                      # "primary", "bench", "manual"
    assigned_by: str
    assigned_datetime: datetime

    # Soft delete
    is_active: bool = True
    deallocated_datetime: datetime = None
    deallocated_by: str = None

    # UNIQUE: (resource_cn, year, week_number)
```

---

### 1.6 MonthlyCapacitySummaryModel

**Purpose:** Pre-aggregated monthly capacity for fast reporting.

```python
class MonthlyCapacitySummaryModel(SQLModel, table=True):
    __tablename__ = "monthly_capacity_summary"

    id: int = Field(primary_key=True)

    # Report context
    report_month: str
    report_year: int
    forecast_month_index: int                 # 1-6
    forecast_month: str
    forecast_year: int

    # Demand identification
    main_lob: str
    state: str
    case_type: str

    # Aggregated metrics
    total_forecast: int
    total_fte_count: int                      # Actual + placeholder
    actual_fte_count: int
    placeholder_fte_count: int
    total_fte_equivalent: float               # Sum of production_percentage
    actual_fte_equivalent: float
    placeholder_fte_equivalent: float
    total_capacity: float

    # Derived metrics
    fte_required: int
    capacity_gap: float

    # Breakdown
    tier_breakdown: str                       # JSON with actual/placeholder split

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

## 2. API Endpoints

### 2.1 Resource Management (`/api/v2/resources`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v2/resources` | List resources with filters (platform, location, active, resource_type, available_for_date) |
| GET | `/api/v2/resources/{cn}` | Get single resource by CN |
| POST | `/api/v2/resources` | Create new actual resource |
| PUT | `/api/v2/resources/{cn}` | Update resource details (including availability window) |
| DELETE | `/api/v2/resources/{cn}` | Deactivate resource (soft delete) |
| POST | `/api/v2/resources/bulk-import` | Import from roster file |

**New Query Parameter: `available_for_date`**
```
GET /api/v2/resources?available_for_date=2025-06-15
```
Returns only resources where:
- `available_from` is NULL or <= 2025-06-15
- `available_until` is NULL or >= 2025-06-15

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
    "display_name_prefix": "Planned Hire - Claims",
    "available_from": "2025-06-01",
    "available_until": "2025-12-31"
}
```

### 2.3 Weekly Assignment Management (`/api/v2/assignments`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v2/assignments` | List assignments with filters |
| GET | `/api/v2/assignments/{id}` | Get single assignment |
| POST | `/api/v2/assignments` | Create assignment (validates availability window) |
| PUT | `/api/v2/assignments/{id}` | Update assignment |
| DELETE | `/api/v2/assignments/{id}` | Deallocate (soft delete) |
| POST | `/api/v2/assignments/bulk` | Bulk assign resources |

### 2.4 Policy Management (`/api/v2/policies`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v2/policies` | List all policies |
| GET | `/api/v2/policies/{policy_key}` | Get single policy |
| PUT | `/api/v2/policies/{policy_key}` | Update policy value |
| POST | `/api/v2/policies/reset` | Reset all policies to defaults |

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
| GET | `/api/v2/reports/powerbi/monthly-summary` | Monthly summary flat table | PowerBI |
| GET | `/api/v2/reports/powerbi/weekly-detail` | Weekly detail flat table | PowerBI |
| GET | `/api/v2/reports/dashboard/hierarchy` | Hierarchical data | JavaScript |
| GET | `/api/v2/reports/dashboard/charts-data` | Chart-ready data | JavaScript |
| GET | `/api/v2/reports/capacity-by-tier` | Breakdown by production % | Both |

### 2.8 Allocation V2 (`/api/v2/allocation`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v2/allocation/execute` | Run allocation (respects availability windows) |
| GET | `/api/v2/allocation/preview` | Preview allocation without committing |
| POST | `/api/v2/allocation/rebalance` | Rebalance existing assignments |

---

## 3. Core Logic

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
    Works identically for actual and placeholder resources.
    """
    return (
        production_percentage *
        working_days *
        work_hours *
        (1 - shrinkage) *
        target_cph
    )

# Example: Resource at 100% production
# 1.0 * 5 * 9 * 0.9 * 12.5 = 506.25 cases/week
```

### 3.2 Availability Window Check

```python
def is_resource_available_for_week(
    resource: ResourceModel,
    week_start: date,
    week_end: date
) -> bool:
    """
    Check if resource is available for the entire week.
    Respects availability policies from AvailabilityPolicyModel.
    """
    # Get policies
    enforce_from = get_policy_bool("ENFORCE_AVAILABLE_FROM", default=True)
    enforce_until = get_policy_bool("ENFORCE_AVAILABLE_UNTIL", default=True)

    # Check available_from
    if enforce_from and resource.available_from:
        if week_start < resource.available_from:
            return False

    # Check available_until
    if enforce_until and resource.available_until:
        if week_end > resource.available_until:
            return False

    return True
```

### 3.3 Resource Matching with Availability

```python
def get_available_resources_for_demand(
    demand: ForecastModel,
    week_start: date,
    week_end: date,
    include_placeholders: bool = True
) -> List[ResourceModel]:
    """
    Get resources matching demand criteria AND available for the week.
    """
    query = session.query(ResourceModel).filter(
        ResourceModel.primary_platform == demand.platform,
        ResourceModel.location == demand.locality,
        ResourceModel.is_active == True
    )

    if not include_placeholders:
        query = query.filter(ResourceModel.resource_type == "actual")

    # Filter by availability window
    resources = []
    for resource in query.all():
        if is_resource_available_for_week(resource, week_start, week_end):
            if demand.state in resource.state_list.split("|"):
                resources.append(resource)

    return resources
```

### 3.4 Monthly Aggregation

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

---

## 4. Report Formats

### 4.1 PowerBI Format (Flat Table)

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
     15, 0, 8, 4, 5, 8, 2, 5]
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
  "months": ["May-25", "Jun-25", "Jul-25", "Aug-25", "Sep-25", "Oct-25"]
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
│   ├── placeholder_utils.py          # Placeholder creation, conversion
│   ├── availability_utils.py         # Availability window checks (NEW)
│   ├── policy_utils.py               # Policy retrieval helpers (NEW)
│   ├── allocation_v2.py              # V2 allocation algorithm
│   └── aggregation_utils.py          # Monthly aggregation helpers
├── api/
│   └── routers/
│       ├── resource_router_v2.py     # Resource + Placeholder CRUD
│       ├── assignment_router_v2.py   # Assignment CRUD
│       ├── capacity_tier_router.py   # Tier management
│       ├── policy_router_v2.py       # Policy management (NEW)
│       ├── week_config_router.py     # Week configuration
│       └── reports_router_v2.py      # V2 reporting endpoints
└── tests/
    ├── test_capacity_calculations_v2.py
    ├── test_availability_utils.py    # NEW
    ├── test_policy_utils.py          # NEW
    ├── test_placeholder_utils.py
    ├── test_allocation_v2.py
    └── test_reports_v2.py
```

### 5.2 Modified Files

| File | Changes |
|------|---------|
| `code/main.py` | Register V2 routers with `/api/v2` prefix |
| `code/logics/db.py` | Add V2 models or import from models_v2.py |
| `code/api/dependencies.py` | Add V2 dependencies if needed |

---

## 6. Migration Strategy

### 6.1 Data Migration

1. **ResourceModel**: Import from existing `ProdTeamRosterModel`
   - Map CN, names, platform, location, state, skills
   - Set `resource_type = "actual"` for all imported
   - Set `available_from = hire_date` if available
   - Set `available_until = NULL` (indefinite)

2. **WeeklyResourceAssignmentModel**: Import from existing allocations
   - Convert monthly allocations to weekly
   - Initially set all to 100% production tier

3. **AvailabilityPolicyModel**: Seed default policies

### 6.2 Rollout Phases

| Phase | Description |
|-------|-------------|
| Phase 1 | Create tables, seed tiers & policies, migration scripts |
| Phase 2 | Core calculation logic, availability checks, unit tests |
| Phase 3 | API endpoints including policy management |
| Phase 4 | Reporting endpoints (PowerBI + JS formats) |
| Phase 5 | Integration testing, bug fixes |

---

## 7. Verification Steps

### 7.1 Database Verification

```sql
-- Verify tables created
SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%v2%';

-- Verify default policies seeded
SELECT * FROM availability_policy;

-- Verify default tiers seeded
SELECT * FROM production_capacity_tier;
```

### 7.2 API Verification

```bash
# Test resource creation with availability window
curl -X POST /api/v2/resources -d '{
  "cn": "CN12345",
  "resource_type": "actual",
  "available_from": "2025-05-01",
  "available_until": null,
  ...
}'

# Test policy retrieval
curl GET /api/v2/policies

# Test availability filter
curl GET /api/v2/resources?available_for_date=2025-06-15
```

### 7.3 Availability Window Verification

```python
# Test case: Resource with future availability
resource = ResourceModel(
    cn="CN12345",
    available_from=date(2025, 6, 1),
    available_until=None
)

# Should return False (week before availability)
assert not is_resource_available_for_week(resource, date(2025, 5, 26), date(2025, 6, 1))

# Should return True (week after availability starts)
assert is_resource_available_for_week(resource, date(2025, 6, 2), date(2025, 6, 8))
```

---

## 8. Implementation Checklist

### Phase 1: Foundation
- [ ] Create WeekConfigurationModel
- [ ] Create ProductionCapacityTierModel
- [ ] Create AvailabilityPolicyModel (NEW)
- [ ] Create ResourceModel (with availability fields)
- [ ] Create WeeklyResourceAssignmentModel
- [ ] Create MonthlyCapacitySummaryModel
- [ ] Seed default capacity tiers
- [ ] Seed default policies (NEW)
- [ ] Write migration script for existing data

### Phase 2: Core Logic
- [ ] Implement weekly capacity calculation
- [ ] Implement availability window checks (NEW)
- [ ] Implement policy retrieval helpers (NEW)
- [ ] Implement monthly aggregation
- [ ] Implement tier breakdown calculation
- [ ] Implement placeholder creation/conversion
- [ ] Unit tests for all calculations

### Phase 3: API Development
- [ ] Resource CRUD endpoints (with availability)
- [ ] Placeholder resource endpoints
- [ ] Policy management endpoints (NEW)
- [ ] Assignment CRUD endpoints
- [ ] Week config endpoints
- [ ] Capacity tier endpoints
- [ ] API tests

### Phase 4: Reporting
- [ ] PowerBI flat format endpoints
- [ ] JavaScript nested JSON endpoints
- [ ] Monthly summary with tier breakdown
- [ ] Excel export

### Phase 5: Integration
- [ ] Manager view V2 integration
- [ ] End-to-end testing
- [ ] Performance optimization
- [ ] Documentation

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-18 | Initial proposal |
| 2.0 | 2026-02-18 | Added placeholder support, actual/placeholder breakdown |
| 3.0 | 2026-02-18 | Added availability window feature, policy configuration, restructured document with Management Overview + Developer Guide |

---

*Document Version: 3.0*
*Created: 2026-02-18*
*Last Updated: 2026-02-18*
