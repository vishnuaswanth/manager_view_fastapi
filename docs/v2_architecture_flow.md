# V2 Architecture - Flow Diagrams

This document contains flow diagrams for the V2 Weekly Capacity & Multi-Group Resource Tracking system.

---

## 1. High-Level Data Flow

```mermaid
flowchart TB
    subgraph Input["Data Input Layer"]
        ROSTER[("Roster File<br/>(Excel)")]
        FORECAST[("Forecast File<br/>(Excel)")]
        CONFIG[("Month Config")]
    end

    subgraph Processing["Processing Layer"]
        UPLOAD["Upload Router"]
        MIGRATION["Data Migration"]
        WEEKGEN["Week Config<br/>Generator"]
    end

    subgraph Storage["Data Storage Layer"]
        subgraph V2Tables["V2 Tables"]
            RESOURCE[("ResourceModel")]
            WEEKCONFIG[("WeekConfiguration")]
            TIERS[("CapacityTiers")]
            POLICY[("Policies")]
            ASSIGN[("WeeklyAssignments")]
            SUMMARY[("MonthlySummary")]
        end
        subgraph V1Tables["V1 Tables (Reference)"]
            FORECASTDB[("ForecastModel")]
            MONTHCONFIG[("MonthConfig")]
            TARGETCPH[("TargetCPH")]
        end
    end

    subgraph Output["Output Layer"]
        POWERBI["PowerBI<br/>(Flat Tables)"]
        DASHBOARD["JS Dashboard<br/>(Nested JSON)"]
        EXCEL["Excel Export"]
    end

    ROSTER --> UPLOAD
    FORECAST --> UPLOAD
    CONFIG --> UPLOAD

    UPLOAD --> MIGRATION
    MIGRATION --> RESOURCE
    MIGRATION --> FORECASTDB

    MONTHCONFIG --> WEEKGEN
    WEEKGEN --> WEEKCONFIG

    RESOURCE --> ASSIGN
    FORECASTDB --> ASSIGN
    WEEKCONFIG --> ASSIGN
    TIERS --> ASSIGN
    POLICY --> ASSIGN

    ASSIGN --> SUMMARY

    SUMMARY --> POWERBI
    SUMMARY --> DASHBOARD
    SUMMARY --> EXCEL
```

---

## 2. Allocation Process Flow

```mermaid
flowchart TD
    START([Start Allocation])

    subgraph Inputs["1. Gather Inputs"]
        GET_FORECAST["Get Forecast Demands"]
        GET_RESOURCES["Get Available Resources"]
        GET_CONFIG["Get Week Configuration"]
        GET_POLICY["Get Active Policies"]
    end

    subgraph Validation["2. Validation"]
        CHECK_AVAIL{"Check Resource<br/>Availability Window"}
        CHECK_SKILLS{"Match Skills &<br/>Platform"}
        CHECK_STATE{"Match State"}
        FILTER_RESOURCES["Filter Eligible<br/>Resources"]
    end

    subgraph Allocation["3. Allocation Engine"]
        MATCH["Match Resources<br/>to Demands"]
        CALC_CAPACITY["Calculate Weekly<br/>Capacity"]
        ASSIGN_TIER["Assign Production<br/>Tier (%)"]
        CREATE_ASSIGN["Create Assignment<br/>Records"]
    end

    subgraph Aggregation["4. Aggregation"]
        AGG_WEEKLY["Sum Weekly<br/>Capacities"]
        AGG_MONTHLY["Create Monthly<br/>Summary"]
        CALC_GAP["Calculate<br/>Capacity Gap"]
    end

    subgraph Output["5. Output"]
        STORE["Store in DB"]
        REPORT["Generate Reports"]
    end

    FINISH([End])

    START --> GET_FORECAST
    START --> GET_RESOURCES
    START --> GET_CONFIG
    START --> GET_POLICY

    GET_RESOURCES --> CHECK_AVAIL
    GET_POLICY --> CHECK_AVAIL
    CHECK_AVAIL -->|Available| CHECK_SKILLS
    CHECK_AVAIL -->|Not Available| FILTER_RESOURCES

    CHECK_SKILLS -->|Match| CHECK_STATE
    CHECK_SKILLS -->|No Match| FILTER_RESOURCES

    CHECK_STATE -->|Match| FILTER_RESOURCES
    CHECK_STATE -->|No Match| FILTER_RESOURCES

    GET_FORECAST --> MATCH
    GET_CONFIG --> MATCH
    FILTER_RESOURCES --> MATCH

    MATCH --> CALC_CAPACITY
    CALC_CAPACITY --> ASSIGN_TIER
    ASSIGN_TIER --> CREATE_ASSIGN

    CREATE_ASSIGN --> AGG_WEEKLY
    AGG_WEEKLY --> AGG_MONTHLY
    AGG_MONTHLY --> CALC_GAP

    CALC_GAP --> STORE
    STORE --> REPORT
    REPORT --> FINISH
```

---

## 3. Capacity Calculation Flow

```mermaid
flowchart LR
    subgraph Inputs["Inputs"]
        PROD_PCT["Production %<br/>(0.25, 0.50, 0.75, 1.0)"]
        WORK_DAYS["Working Days<br/>(e.g., 5)"]
        WORK_HRS["Work Hours<br/>(e.g., 9)"]
        SHRINK["Shrinkage<br/>(e.g., 0.10)"]
        CPH["Target CPH<br/>(e.g., 12.5)"]
    end

    subgraph Formula["Capacity Formula"]
        CALC["Weekly Capacity =<br/>Prod% × Days × Hours × (1-Shrink) × CPH"]
    end

    subgraph Output["Output"]
        WEEKLY["Weekly Capacity<br/>(cases/week)"]
        MONTHLY["Monthly Capacity<br/>(sum of weeks)"]
    end

    PROD_PCT --> CALC
    WORK_DAYS --> CALC
    WORK_HRS --> CALC
    SHRINK --> CALC
    CPH --> CALC

    CALC --> WEEKLY
    WEEKLY -->|"Σ all weeks"| MONTHLY
```

---

## 4. Placeholder Lifecycle Flow

```mermaid
flowchart TD
    subgraph Creation["1. Creation"]
        CREATE["Create Placeholder<br/>TBH-001, TBH-002..."]
        SET_SKILLS["Set Skills/Platform/<br/>Location/States"]
        SET_AVAIL["Set Availability<br/>Window"]
    end

    subgraph Planning["2. Planning Phase"]
        ASSIGN_DEMAND["Assign to Demand"]
        SET_TIER["Set Production Tier"]
        CALC_PLAN["Calculate Planned<br/>Capacity"]
    end

    subgraph Conversion["3. Conversion"]
        HIRE["New Hire Onboarded"]
        CONVERT["Convert Placeholder<br/>to Actual Resource"]
        TRANSFER["Transfer Assignments"]
        LINK["Link via<br/>replaced_by_cn"]
    end

    subgraph Active["4. Active Resource"]
        ACTUAL["Actual Resource<br/>CN12345"]
        TRACK["Track Real<br/>Capacity"]
    end

    CREATE --> SET_SKILLS
    SET_SKILLS --> SET_AVAIL
    SET_AVAIL --> ASSIGN_DEMAND
    ASSIGN_DEMAND --> SET_TIER
    SET_TIER --> CALC_PLAN

    CALC_PLAN -.->|"Hire Happens"| HIRE
    HIRE --> CONVERT
    CONVERT --> TRANSFER
    TRANSFER --> LINK
    LINK --> ACTUAL
    ACTUAL --> TRACK
```

---

## 5. Availability Window Check Flow

```mermaid
flowchart TD
    START([Check Availability])

    GET_RESOURCE["Get Resource"]
    GET_WEEK["Get Week Start/End Dates"]

    CHECK_FROM{"available_from<br/>is set?"}
    CHECK_FROM_DATE{"week_start >=<br/>available_from?"}

    CHECK_UNTIL{"available_until<br/>is set?"}
    CHECK_UNTIL_DATE{"week_end <=<br/>available_until?"}

    GET_POLICY_FROM["Get Policy:<br/>ENFORCE_AVAILABLE_FROM"]
    GET_POLICY_UNTIL["Get Policy:<br/>ENFORCE_AVAILABLE_UNTIL"]

    ENFORCE_FROM{"Policy<br/>enabled?"}
    ENFORCE_UNTIL{"Policy<br/>enabled?"}

    AVAILABLE([Resource Available])
    NOT_AVAILABLE([Resource NOT Available])

    START --> GET_RESOURCE
    START --> GET_WEEK

    GET_RESOURCE --> CHECK_FROM
    GET_WEEK --> CHECK_FROM

    CHECK_FROM -->|No| CHECK_UNTIL
    CHECK_FROM -->|Yes| GET_POLICY_FROM

    GET_POLICY_FROM --> ENFORCE_FROM
    ENFORCE_FROM -->|No| CHECK_UNTIL
    ENFORCE_FROM -->|Yes| CHECK_FROM_DATE

    CHECK_FROM_DATE -->|Yes| CHECK_UNTIL
    CHECK_FROM_DATE -->|No| NOT_AVAILABLE

    CHECK_UNTIL -->|No| AVAILABLE
    CHECK_UNTIL -->|Yes| GET_POLICY_UNTIL

    GET_POLICY_UNTIL --> ENFORCE_UNTIL
    ENFORCE_UNTIL -->|No| AVAILABLE
    ENFORCE_UNTIL -->|Yes| CHECK_UNTIL_DATE

    CHECK_UNTIL_DATE -->|Yes| AVAILABLE
    CHECK_UNTIL_DATE -->|No| NOT_AVAILABLE
```

---

## 6. Week Configuration Generation Flow

```mermaid
flowchart TD
    START([Start Generation])

    INPUT_MONTH["Input: Month & Year<br/>(e.g., April 2025)"]
    GET_MONTH_CONFIG["Get MonthConfiguration<br/>(Domestic & Global)"]

    CALC_WEEKS["Calculate ISO Weeks<br/>in Month"]

    subgraph ForEachWeek["For Each Week"]
        CREATE_WEEK["Create WeekConfigurationModel"]
        SET_DATES["Set week_start_date<br/>week_end_date"]
        SET_PARAMS["Set working_days,<br/>occupancy, shrinkage,<br/>work_hours"]
        ADJUST_HOLIDAYS["Adjust for Holidays<br/>(if needed)"]
    end

    SAVE["Save to Database"]
    FINISH([End])

    START --> INPUT_MONTH
    INPUT_MONTH --> GET_MONTH_CONFIG
    GET_MONTH_CONFIG --> CALC_WEEKS
    CALC_WEEKS --> CREATE_WEEK
    CREATE_WEEK --> SET_DATES
    SET_DATES --> SET_PARAMS
    SET_PARAMS --> ADJUST_HOLIDAYS
    ADJUST_HOLIDAYS -->|"Next Week"| CREATE_WEEK
    ADJUST_HOLIDAYS -->|"All Done"| SAVE
    SAVE --> FINISH
```

---

## 7. Report Generation Flow

```mermaid
flowchart TD
    START([Generate Report])

    subgraph Query["1. Query Data"]
        GET_SUMMARY["Get Monthly<br/>Capacity Summary"]
        GET_ASSIGNMENTS["Get Weekly<br/>Assignments"]
        GET_FORECAST["Get Forecast<br/>Demands"]
    end

    subgraph Transform["2. Transform"]
        SPLIT_ACTUAL["Split Actual vs<br/>Placeholder"]
        CALC_TIERS["Calculate Tier<br/>Breakdown"]
        CALC_EQUIV["Calculate FTE<br/>Equivalents"]
    end

    subgraph Format["3. Format Output"]
        CHECK_FORMAT{"Output<br/>Format?"}
        POWERBI["Flatten to<br/>PowerBI Table"]
        DASHBOARD["Nest to<br/>JSON Hierarchy"]
    end

    OUTPUT_POWERBI[("PowerBI<br/>Flat Rows")]
    OUTPUT_JS[("JavaScript<br/>Nested JSON")]

    START --> GET_SUMMARY
    START --> GET_ASSIGNMENTS
    START --> GET_FORECAST

    GET_SUMMARY --> SPLIT_ACTUAL
    GET_ASSIGNMENTS --> SPLIT_ACTUAL
    GET_FORECAST --> SPLIT_ACTUAL

    SPLIT_ACTUAL --> CALC_TIERS
    CALC_TIERS --> CALC_EQUIV

    CALC_EQUIV --> CHECK_FORMAT
    CHECK_FORMAT -->|"PowerBI"| POWERBI
    CHECK_FORMAT -->|"Dashboard"| DASHBOARD

    POWERBI --> OUTPUT_POWERBI
    DASHBOARD --> OUTPUT_JS
```

---

## 8. Data Migration Flow (V1 to V2)

```mermaid
flowchart TD
    START([Start Migration])

    subgraph Phase1["Phase 1: Setup"]
        CREATE_TABLES["Create V2 Tables"]
        SEED_TIERS["Seed Default<br/>Capacity Tiers"]
        SEED_POLICIES["Seed Default<br/>Policies"]
    end

    subgraph Phase2["Phase 2: Resources"]
        READ_ROSTER["Read ProdTeamRosterModel"]
        MAP_FIELDS["Map Fields to<br/>ResourceModel"]
        SET_TYPE["Set resource_type<br/>= 'actual'"]
        SET_AVAIL["Set available_from<br/>= hire_date"]
        SAVE_RESOURCES["Save to resource_v2"]
    end

    subgraph Phase3["Phase 3: Assignments"]
        READ_ALLOC["Read Existing<br/>Allocations"]
        CONVERT_WEEKLY["Convert Monthly<br/>to Weekly"]
        SET_100PCT["Set 100%<br/>Production Tier"]
        SAVE_ASSIGN["Save to<br/>weekly_resource_assignment"]
    end

    subgraph Phase4["Phase 4: Summaries"]
        CALC_SUMMARIES["Calculate Monthly<br/>Summaries"]
        SAVE_SUMMARIES["Save to<br/>monthly_capacity_summary"]
    end

    VERIFY["Verify Data<br/>Integrity"]
    FINISH([Migration Complete])

    START --> CREATE_TABLES
    CREATE_TABLES --> SEED_TIERS
    SEED_TIERS --> SEED_POLICIES
    SEED_POLICIES --> READ_ROSTER

    READ_ROSTER --> MAP_FIELDS
    MAP_FIELDS --> SET_TYPE
    SET_TYPE --> SET_AVAIL
    SET_AVAIL --> SAVE_RESOURCES

    SAVE_RESOURCES --> READ_ALLOC
    READ_ALLOC --> CONVERT_WEEKLY
    CONVERT_WEEKLY --> SET_100PCT
    SET_100PCT --> SAVE_ASSIGN

    SAVE_ASSIGN --> CALC_SUMMARIES
    CALC_SUMMARIES --> SAVE_SUMMARIES

    SAVE_SUMMARIES --> VERIFY
    VERIFY --> FINISH
```

---

*Document Version: 1.0*
*Created: 2026-02-18*
