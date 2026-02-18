# V2 Architecture - System Design

This document contains system design and component architecture diagrams for the V2 Weekly Capacity & Multi-Group Resource Tracking system.

---

## 1. System Architecture Overview

```mermaid
graph TB
    subgraph Clients["Client Layer"]
        BROWSER["Web Browser"]
        POWERBI["PowerBI"]
        EXCEL_CLIENT["Excel"]
    end

    subgraph API["API Layer - FastAPI"]
        GATEWAY["API Gateway /api/v2"]
        RESOURCE_R["Resource Router"]
        ASSIGN_R["Assignment Router"]
        POLICY_R["Policy Router"]
        TIER_R["Tier Router"]
        WEEKCFG_R["Week Config Router"]
        REPORT_R["Reports Router"]
        ALLOC_R["Allocation Router"]
    end

    subgraph Logic["Business Logic Layer"]
        ALLOC_SVC["Allocation Service"]
        CAPACITY_SVC["Capacity Calculator"]
        AVAIL_SVC["Availability Service"]
        POLICY_SVC["Policy Service"]
        PLACEHOLDER_U["Placeholder Utils"]
        AGGREGATION_U["Aggregation Utils"]
        EXPORT_U["Export Utils"]
    end

    subgraph Data["Data Layer"]
        MODELS["V2 Models"]
        MSSQL[("MSSQL Server - Production")]
        SQLITE[("SQLite - Debug")]
    end

    subgraph External["External Systems"]
        EXCEL_FILE["Excel Files - Upload"]
        EXPORT_FILE["Excel Files - Export"]
    end

    BROWSER --> GATEWAY
    POWERBI --> GATEWAY
    EXCEL_CLIENT --> GATEWAY

    GATEWAY --> RESOURCE_R
    GATEWAY --> ASSIGN_R
    GATEWAY --> POLICY_R
    GATEWAY --> TIER_R
    GATEWAY --> WEEKCFG_R
    GATEWAY --> REPORT_R
    GATEWAY --> ALLOC_R

    RESOURCE_R --> ALLOC_SVC
    ASSIGN_R --> ALLOC_SVC
    ALLOC_R --> ALLOC_SVC

    ALLOC_SVC --> CAPACITY_SVC
    ALLOC_SVC --> AVAIL_SVC
    AVAIL_SVC --> POLICY_SVC

    ALLOC_SVC --> PLACEHOLDER_U
    REPORT_R --> AGGREGATION_U
    REPORT_R --> EXPORT_U

    CAPACITY_SVC --> MODELS
    AVAIL_SVC --> MODELS
    POLICY_SVC --> MODELS
    PLACEHOLDER_U --> MODELS
    AGGREGATION_U --> MODELS

    MODELS --> MSSQL
    MODELS --> SQLITE

    EXCEL_FILE --> GATEWAY
    EXPORT_U --> EXPORT_FILE
```

---

## 2. Component Architecture

```mermaid
graph TB
    subgraph API_Layer["API Layer - V2 Routers"]
        R1["resource_router_v2.py"]
        R2["assignment_router_v2.py"]
        R3["policy_router_v2.py"]
        R4["capacity_tier_router.py"]
        R5["week_config_router.py"]
        R6["reports_router_v2.py"]
        R7["allocation_router_v2.py"]
    end

    subgraph Models_Layer["Models - models_v2.py"]
        M1["ResourceModel"]
        M2["WeeklyResourceAssignment"]
        M3["MonthlyCapacitySummary"]
        M4["ProductionCapacityTier"]
        M5["WeekConfiguration"]
        M6["AvailabilityPolicy"]
    end

    subgraph Services_Layer["Services"]
        S1["allocation_v2.py"]
        S2["capacity_calculations_v2.py"]
        S3["availability_utils.py"]
        S4["policy_utils.py"]
        S5["placeholder_utils.py"]
        S6["aggregation_utils.py"]
    end

    subgraph Tests_Layer["Test Layer"]
        T1["test_capacity_calculations_v2.py"]
        T2["test_availability_utils.py"]
        T3["test_policy_utils.py"]
        T4["test_placeholder_utils.py"]
        T5["test_allocation_v2.py"]
        T6["test_reports_v2.py"]
    end

    R1 --> M1
    R2 --> M2
    R3 --> M6
    R4 --> M4
    R5 --> M5
    R6 --> M3
    R7 --> S1

    S1 --> S2
    S1 --> S3
    S1 --> S5
    S3 --> S4
    R6 --> S6

    T1 --> S2
    T2 --> S3
    T3 --> S4
    T4 --> S5
    T5 --> S1
    T6 --> S6
```

---

## 3. Database Schema Overview

```mermaid
erDiagram
    ResourceModel ||--o{ WeeklyResourceAssignment : "assigned_to"
    ProductionCapacityTier ||--o{ WeeklyResourceAssignment : "tier"
    WeekConfiguration ||--o{ WeeklyResourceAssignment : "week"
    ForecastModel ||--o{ WeeklyResourceAssignment : "demand"
    WeeklyResourceAssignment }o--|| MonthlyCapacitySummary : "aggregates"
    AvailabilityPolicy ||--o{ ResourceModel : "governs"

    ResourceModel {
        int id PK
        string cn UK
        string resource_type
        date available_from
        date available_until
        string primary_platform
        string location
        string state_list
        string skills
        bool is_active
    }

    WeeklyResourceAssignment {
        int id PK
        int year
        int week_number
        string resource_cn FK
        int capacity_tier_id FK
        float production_percentage
        float weekly_capacity
        bool is_active
    }

    MonthlyCapacitySummary {
        int id PK
        string report_month
        int report_year
        int actual_fte_count
        int placeholder_fte_count
        float total_capacity
        float capacity_gap
        string tier_breakdown
    }

    ProductionCapacityTier {
        int id PK
        string tier_name UK
        float capacity_percentage
        bool is_active
    }

    WeekConfiguration {
        int id PK
        int year
        int week_number
        int working_days
        float work_hours
        float shrinkage
    }

    AvailabilityPolicy {
        int id PK
        string policy_key UK
        string policy_value
        string category
        bool is_active
    }

    ForecastModel {
        int id PK
        string Main_LOB
        string State
        string Case_Type
        int Forecast_Month1_6
    }
```

---

## 4. API Endpoint Structure

```mermaid
graph TD
    subgraph Root["/api/v2"]
        RESOURCES["/resources"]
        ASSIGNMENTS["/assignments"]
        POLICIES["/policies"]
        TIERS["/capacity-tiers"]
        WEEKCFG["/week-config"]
        REPORTS["/reports"]
        ALLOCATION["/allocation"]
    end

    subgraph Resources_Sub["/resources Endpoints"]
        R_LIST["GET / - List"]
        R_GET["GET /cn - Get"]
        R_CREATE["POST / - Create"]
        R_UPDATE["PUT /cn - Update"]
        R_DELETE["DELETE /cn - Deactivate"]
        R_BULK["POST /bulk-import"]
        R_PLACE["POST /placeholders"]
        R_CONVERT["POST /cn/convert"]
    end

    subgraph Assignments_Sub["/assignments Endpoints"]
        A_LIST["GET / - List"]
        A_GET["GET /id - Get"]
        A_CREATE["POST / - Create"]
        A_UPDATE["PUT /id - Update"]
        A_DELETE["DELETE /id - Deallocate"]
        A_BULK["POST /bulk"]
    end

    subgraph Policies_Sub["/policies Endpoints"]
        P_LIST["GET / - List All"]
        P_GET["GET /key - Get"]
        P_UPDATE["PUT /key - Update"]
        P_RESET["POST /reset"]
    end

    subgraph Reports_Sub["/reports Endpoints"]
        REP_PBI["GET /powerbi/*"]
        REP_DASH["GET /dashboard/*"]
        REP_TIER["GET /capacity-by-tier"]
    end

    subgraph Allocation_Sub["/allocation Endpoints"]
        AL_EXEC["POST /execute"]
        AL_PREVIEW["GET /preview"]
        AL_REBAL["POST /rebalance"]
    end

    RESOURCES --> Resources_Sub
    ASSIGNMENTS --> Assignments_Sub
    POLICIES --> Policies_Sub
    REPORTS --> Reports_Sub
    ALLOCATION --> Allocation_Sub
```

---

## 5. Layered Architecture

```mermaid
graph TB
    subgraph Presentation["Presentation Layer"]
        WEB["Web Dashboard"]
        PBI["PowerBI"]
        API_DOC["API Docs - Swagger"]
    end

    subgraph Application["Application Layer"]
        R_V2["V2 Routers"]
        R_V1["V1 Routers - Legacy"]
        AUTH["Authentication"]
        LOG["Logging"]
        CACHE["Caching"]
    end

    subgraph Business["Business Logic Layer"]
        ALLOC["Allocation"]
        CAPACITY["Capacity"]
        AVAIL["Availability"]
        POLICY["Policy"]
        PLACEHOLDER["Placeholder"]
        AGGREGATION["Aggregation"]
    end

    subgraph Data["Data Access Layer"]
        ORM["SQLModel ORM"]
        REPO["Repository Pattern"]
        CONN["Connection Pool"]
    end

    subgraph Infrastructure["Infrastructure Layer"]
        DB_PROD["MSSQL - Production"]
        DB_DEV["SQLite - Development"]
        FILES["File Storage"]
    end

    Presentation --> Application
    Application --> Business
    Business --> Data
    Data --> Infrastructure
```

---

## 6. Policy System Architecture

```mermaid
graph TB
    subgraph Config["Policy Configuration"]
        POLICY_DB[("AvailabilityPolicyModel")]
        DEFAULTS["Default Values - Seeded on Startup"]
    end

    subgraph Categories["Policy Categories"]
        CAT_AVAIL["Availability Policies"]
        CAT_ALLOC["Allocation Policies"]
        CAT_REPORT["Reporting Policies"]
    end

    subgraph Avail_Policies["Availability Policies"]
        P1["ENFORCE_AVAILABLE_FROM"]
        P2["ENFORCE_AVAILABLE_UNTIL"]
        P3["DEFAULT_AVAILABILITY_DAYS"]
        P4["PLACEHOLDER_DEFAULT_WEEKS"]
    end

    subgraph Alloc_Policies["Allocation Policies"]
        P5["ALLOW_OVER_ALLOCATION"]
        P6["AUTO_CREATE_PLACEHOLDERS"]
        P7["PLACEHOLDER_PREFIX"]
        P8["MAX_PLACEHOLDERS_PER_REQUEST"]
    end

    subgraph Report_Policies["Reporting Policies"]
        P9["INCLUDE_PLACEHOLDERS_IN_REPORTS"]
        P10["SEPARATE_PLACEHOLDER_COLUMNS"]
    end

    subgraph Usage["Policy Usage"]
        AVAIL_CHECK["Availability Check"]
        ALLOC_ENGINE["Allocation Engine"]
        REPORT_GEN["Report Generator"]
    end

    DEFAULTS --> POLICY_DB
    POLICY_DB --> CAT_AVAIL
    POLICY_DB --> CAT_ALLOC
    POLICY_DB --> CAT_REPORT

    CAT_AVAIL --> Avail_Policies
    CAT_ALLOC --> Alloc_Policies
    CAT_REPORT --> Report_Policies

    Avail_Policies --> AVAIL_CHECK
    Alloc_Policies --> ALLOC_ENGINE
    Report_Policies --> REPORT_GEN
```

---

## 7. Capacity Tier System

```mermaid
graph TB
    subgraph Tiers["Production Capacity Tiers"]
        T100["100% - Full Production"]
        T75["75% - Final Ramp"]
        T50["50% - Mid Ramp"]
        T25["25% - Early Ramp/Training"]
    end

    subgraph Resources["Resource Types"]
        ACTUAL["Actual Resources - CN12345"]
        PLACEHOLDER["Placeholders - TBH-001"]
    end

    subgraph Assignment["Weekly Assignment"]
        ASSIGN["WeeklyResourceAssignment"]
    end

    subgraph Calculation["Capacity Calculation"]
        CALC["Capacity = Tier% x Days x Hours x 1-Shrink x CPH"]
    end

    subgraph Output["Output Metrics"]
        FTE_COUNT["FTE Count"]
        FTE_EQUIV["FTE Equivalent - Sum of Tier%"]
        CAPACITY["Total Capacity"]
    end

    ACTUAL --> ASSIGN
    PLACEHOLDER --> ASSIGN

    T100 --> ASSIGN
    T75 --> ASSIGN
    T50 --> ASSIGN
    T25 --> ASSIGN

    ASSIGN --> CALC

    CALC --> FTE_COUNT
    CALC --> FTE_EQUIV
    CALC --> CAPACITY
```

---

## 8. Deployment Architecture

```mermaid
graph TB
    subgraph Development["Development Environment"]
        DEV_APP["FastAPI App"]
        DEV_DB[("SQLite test.db")]
        DEV_MODE["MODE=DEBUG"]
    end

    subgraph Production["Production Environment"]
        PROD_APP["FastAPI App - Uvicorn"]
        PROD_DB[("MSSQL Server")]
        PROD_MODE["MODE=PRODUCTION"]
    end

    subgraph Config["Configuration"]
        CONFIG_INI["config.ini"]
        ENV_VARS["Environment Variables"]
    end

    subgraph Clients["Clients"]
        WEB["Web Browser"]
        PBI["PowerBI"]
        SCRIPTS["Python Scripts"]
    end

    DEV_APP --> DEV_DB
    DEV_MODE --> DEV_APP
    CONFIG_INI --> DEV_MODE

    PROD_APP --> PROD_DB
    PROD_MODE --> PROD_APP
    CONFIG_INI --> PROD_MODE
    ENV_VARS --> PROD_APP

    WEB --> PROD_APP
    PBI --> PROD_APP
    SCRIPTS --> PROD_APP

    WEB --> DEV_APP
```

---

## 9. File Structure Diagram

```mermaid
graph TD
    subgraph Root["manager_view_fastapi/"]
        CODE["code/"]
        DOCS["docs/"]
        TESTS_ROOT["tests/"]
    end

    subgraph Code_Dir["code/"]
        MAIN["main.py"]
        SETTINGS["settings.py"]
        CACHE["cache.py"]
        API["api/"]
        LOGICS["logics/"]
    end

    subgraph API_Dir["api/"]
        ROUTERS["routers/"]
        DEPS["dependencies.py"]
        UTILS_API["utils/"]
    end

    subgraph Routers_Dir["routers/"]
        R_RESOURCE["resource_router_v2.py"]
        R_ASSIGN["assignment_router_v2.py"]
        R_POLICY["policy_router_v2.py"]
        R_TIER["capacity_tier_router.py"]
        R_WEEK["week_config_router.py"]
        R_REPORT["reports_router_v2.py"]
        R_ALLOC["allocation_router_v2.py"]
    end

    subgraph Logics_Dir["logics/"]
        MODELS["models_v2.py"]
        DB["db.py"]
        CAPACITY["capacity_calculations_v2.py"]
        AVAIL["availability_utils.py"]
        POLICY_U["policy_utils.py"]
        PLACEHOLDER["placeholder_utils.py"]
        ALLOC_V2["allocation_v2.py"]
        AGG["aggregation_utils.py"]
    end

    subgraph Docs_Dir["docs/"]
        PROPOSAL["V2_IMPLEMENTATION_PROPOSAL.md"]
        SCHEMA_MMD["v2_schema.mmd"]
        SCHEMA_HTML["v2_schema.html"]
        ARCH_FLOW["v2_architecture_flow.md"]
        ARCH_SYS["v2_system_design.md"]
        ARCH_INT["v2_user_interactions.md"]
        ARCH_HTML["v2_architecture.html"]
    end

    Root --> CODE
    Root --> DOCS
    Root --> TESTS_ROOT

    CODE --> MAIN
    CODE --> SETTINGS
    CODE --> CACHE
    CODE --> API
    CODE --> LOGICS

    API --> ROUTERS
    API --> DEPS
    API --> UTILS_API

    ROUTERS --> Routers_Dir
    LOGICS --> Logics_Dir
    DOCS --> Docs_Dir
```

---

## 10. Request Flow Diagram

```mermaid
sequenceDiagram
    participant Client
    participant FastAPI
    participant Router
    participant Service
    participant Model
    participant Database

    Client->>FastAPI: HTTP Request
    FastAPI->>Router: Route to Handler
    Router->>Service: Call Business Logic
    Service->>Model: Use Data Models
    Model->>Database: Query/Update
    Database-->>Model: Result
    Model-->>Service: Data Objects
    Service-->>Router: Process Result
    Router-->>FastAPI: Response Object
    FastAPI-->>Client: HTTP Response
```

---

## 11. Data Transformation Pipeline

```mermaid
graph LR
    subgraph Input["Input Data"]
        ROSTER["Roster Excel"]
        FORECAST["Forecast Excel"]
    end

    subgraph Transform["Transformation"]
        PARSE["Parse Files"]
        VALIDATE["Validate Data"]
        NORMALIZE["Normalize Fields"]
        ENRICH["Enrich with Defaults"]
    end

    subgraph Store["Storage"]
        RESOURCE_DB["ResourceModel"]
        FORECAST_DB["ForecastModel"]
        ASSIGN_DB["WeeklyAssignment"]
    end

    subgraph Output["Output"]
        POWERBI_OUT["PowerBI Report"]
        DASHBOARD_OUT["Dashboard JSON"]
        EXCEL_OUT["Excel Export"]
    end

    ROSTER --> PARSE
    FORECAST --> PARSE
    PARSE --> VALIDATE
    VALIDATE --> NORMALIZE
    NORMALIZE --> ENRICH
    ENRICH --> RESOURCE_DB
    ENRICH --> FORECAST_DB
    RESOURCE_DB --> ASSIGN_DB
    FORECAST_DB --> ASSIGN_DB
    ASSIGN_DB --> POWERBI_OUT
    ASSIGN_DB --> DASHBOARD_OUT
    ASSIGN_DB --> EXCEL_OUT
```

---

*Document Version: 1.1*
*Created: 2026-02-18*
*Updated: 2026-02-18 - Fixed Mermaid syntax issues*
