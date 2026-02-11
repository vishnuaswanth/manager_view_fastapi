# Configuration API Specification

## Overview

This document describes the API endpoints for managing configuration data used in allocation calculations. It covers two configuration types:

1. **Month Configuration** - Working parameters (working days, occupancy, shrinkage, work hours) per month/year/work type
2. **Target CPH Configuration** - Cases Per Hour values per Main LOB and Case Type

**Base URL:** `http://your-domain.com`

**Version:** v1

---

## Table of Contents

### Month Configuration
1. [Get Month Configurations](#1-get-month-configurations)
2. [Create Month Configuration](#2-create-month-configuration)
3. [Bulk Create Month Configurations](#3-bulk-create-month-configurations)
4. [Update Month Configuration](#4-update-month-configuration)
5. [Delete Month Configuration](#5-delete-month-configuration)
6. [Seed Initial Month Data](#6-seed-initial-month-data)
7. [Validate Month Configurations](#7-validate-month-configurations)

### Target CPH Configuration
8. [Get Target CPH Configurations](#8-get-target-cph-configurations)
9. [Get Target CPH by ID](#9-get-target-cph-by-id)
10. [Create Target CPH Configuration](#10-create-target-cph-configuration)
11. [Bulk Create Target CPH Configurations](#11-bulk-create-target-cph-configurations)
12. [Update Target CPH Configuration](#12-update-target-cph-configuration)
13. [Delete Target CPH Configuration](#13-delete-target-cph-configuration)
14. [Get Distinct Main LOBs](#14-get-distinct-main-lobs)
15. [Get Distinct Case Types](#15-get-distinct-case-types)
16. [Get Target CPH Count](#16-get-target-cph-count)

### Appendix
- [Data Models](#data-models)
- [FTE Calculation Formulas](#fte-calculation-formulas)
- [Caching Strategy](#caching-strategy)
- [Error Handling](#error-handling)

---

# Part 1: Month Configuration API

**Base Path:** `/api/month-config`

## Important Concepts

### Work Types
All month configurations must specify a work type:
- **Domestic**: For domestic workforce calculations
- **Global**: For offshore/global workforce calculations

### Pairing Rule
**Each (month, year) combination MUST have BOTH Domestic AND Global configurations.**

This ensures consistent allocation calculations. The API prevents creating orphaned records by default.

### Configuration Parameters

| Parameter | Type | Range | Description |
|-----------|------|-------|-------------|
| `working_days` | integer | 1-31 | Business days in the month |
| `occupancy` | float | 0.0-1.0 | Occupancy rate (e.g., 0.95 = 95%) |
| `shrinkage` | float | 0.0-1.0 | Shrinkage rate (e.g., 0.10 = 10%) |
| `work_hours` | float | 1-24 | Work hours per day |

---

## 1. Get Month Configurations

### Endpoint
```http
GET /api/month-config
```

### Description
Retrieve month configurations with optional filtering by month, year, and work type.

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `month` | string | No | - | Filter by month name (e.g., "January") |
| `year` | integer | No | - | Filter by year (e.g., 2025) |
| `work_type` | string | No | - | Filter by work type: "Domestic" or "Global" |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "data": {
    "count": 24,
    "configurations": [
      {
        "id": 1,
        "month": "January",
        "year": 2025,
        "work_type": "Domestic",
        "working_days": 21,
        "occupancy": 0.95,
        "shrinkage": 0.10,
        "work_hours": 9,
        "created_by": "admin",
        "updated_by": "admin",
        "created_datetime": "2025-01-15T10:30:00",
        "updated_datetime": "2025-01-15T10:30:00"
      },
      {
        "id": 2,
        "month": "January",
        "year": 2025,
        "work_type": "Global",
        "working_days": 21,
        "occupancy": 0.90,
        "shrinkage": 0.15,
        "work_hours": 9,
        "created_by": "admin",
        "updated_by": "admin",
        "created_datetime": "2025-01-15T10:30:00",
        "updated_datetime": "2025-01-15T10:30:00"
      }
    ]
  }
}
```

### Example Requests

```bash
# Get all configurations
GET /api/month-config

# Get configurations for specific month/year
GET /api/month-config?month=January&year=2025

# Get only Domestic configurations
GET /api/month-config?work_type=Domestic

# Get Domestic configs for January 2025
GET /api/month-config?month=January&year=2025&work_type=Domestic
```

### Caching
- **TTL:** 15 minutes (900 seconds)
- **Cache Key:** `month_config:v1:{month}:{year}:{work_type}`

---

## 2. Create Month Configuration

### Endpoint
```http
POST /api/month-config
```

### Description
Add a single month configuration to the database.

### Request Body

```json
{
  "month": "January",
  "year": 2025,
  "work_type": "Domestic",
  "working_days": 21,
  "occupancy": 0.95,
  "shrinkage": 0.10,
  "work_hours": 9,
  "created_by": "john.doe"
}
```

### Request Parameters

| Parameter | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `month` | string | Yes | Valid month name | January-December |
| `year` | integer | Yes | 2020-2100 | Year |
| `work_type` | string | Yes | "Domestic" or "Global" | Work type |
| `working_days` | integer | Yes | 1-31 | Business days in month |
| `occupancy` | float | Yes | 0.0-1.0 | Occupancy rate |
| `shrinkage` | float | Yes | 0.0-1.0 | Shrinkage rate |
| `work_hours` | float | Yes | 1-24 | Work hours per day |
| `created_by` | string | Yes | Non-empty | Username |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "message": "Configuration for January 2025 (Domestic) added successfully"
}
```

### Error Responses

**400 Bad Request** - Duplicate or validation error
```json
{
  "success": false,
  "error": "Configuration for January 2025 (Domestic) already exists"
}
```

---

## 3. Bulk Create Month Configurations

### Endpoint
```http
POST /api/month-config/bulk
```

### Description
Bulk add multiple month configurations. Validates pairing by default (each month/year must have both Domestic and Global).

### Request Body

```json
{
  "created_by": "john.doe",
  "skip_pairing_validation": false,
  "configurations": [
    {
      "month": "January",
      "year": 2025,
      "work_type": "Domestic",
      "working_days": 21,
      "occupancy": 0.95,
      "shrinkage": 0.10,
      "work_hours": 9
    },
    {
      "month": "January",
      "year": 2025,
      "work_type": "Global",
      "working_days": 21,
      "occupancy": 0.90,
      "shrinkage": 0.15,
      "work_hours": 9
    }
  ]
}
```

### Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `configurations` | array | Yes | - | Array of configuration objects |
| `created_by` | string | Yes | - | Username |
| `skip_pairing_validation` | boolean | No | false | Skip pairing validation |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "data": {
    "total": 24,
    "succeeded": 24,
    "failed": 0,
    "errors": [],
    "validation_errors": []
  },
  "message": "Bulk operation completed"
}
```

### Error Response - Pairing Validation Failed

**Status Code:** `400 Bad Request`

```json
{
  "message": "Batch validation failed",
  "validation_errors": [
    "Batch validation failed: Missing pairs for the following month-years:\n  - January 2025: Has Domestic, missing Global"
  ],
  "total": 1
}
```

---

## 4. Update Month Configuration

### Endpoint
```http
PUT /api/month-config/{config_id}
```

### Description
Update an existing month configuration. All parameters are optional - only provided fields will be updated.

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `config_id` | integer | Yes | Configuration ID to update |

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `working_days` | integer | No | New working days value |
| `occupancy` | float | No | New occupancy value |
| `shrinkage` | float | No | New shrinkage value |
| `work_hours` | float | No | New work hours value |
| `updated_by` | string | No | Username (default: "System") |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "message": "Configuration updated successfully"
}
```

### Error Response

**Status Code:** `404 Not Found`

```json
{
  "success": false,
  "error": "Configuration with ID 123 not found"
}
```

---

## 5. Delete Month Configuration

### Endpoint
```http
DELETE /api/month-config/{config_id}
```

### Description
Delete a month configuration. By default, prevents deletion if it would orphan the paired configuration.

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `config_id` | integer | Yes | Configuration ID to delete |

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `allow_orphan` | boolean | No | false | Allow deletion even if it orphans the pair |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "message": "Configuration deleted successfully"
}
```

### Error Response - Would Orphan

**Status Code:** `409 Conflict`

```json
{
  "success": false,
  "error": "Cannot delete Domestic configuration for January 2025 (ID: 1). This would orphan the Global configuration (ID: 2). Please delete both configurations together, or set allow_orphan=True to force deletion."
}
```

---

## 6. Seed Initial Month Data

### Endpoint
```http
POST /api/month-config/seed
```

### Description
Seed the database with initial month configuration data. Creates configurations for all 12 months for the specified number of years, for both Domestic and Global work types.

### Request Body

```json
{
  "base_year": 2025,
  "num_years": 2,
  "created_by": "System"
}
```

### Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `base_year` | integer | No | 2025 | Starting year |
| `num_years` | integer | No | 2 | Number of years to seed |
| `created_by` | string | No | "System" | Username |

### Default Configuration Values

| Parameter | Value |
|-----------|-------|
| Occupancy | 0.95 (95%) |
| Shrinkage | 0.10 (10%) |
| Work Hours | 9 |
| Working Days | 20-22 (varies by month) |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "data": {
    "total": 48,
    "succeeded": 48,
    "failed": 0,
    "errors": []
  },
  "message": "Seeded 48/48 configurations"
}
```

---

## 7. Validate Month Configurations

### Endpoint
```http
GET /api/month-config/validate
```

### Description
Validate data integrity of month configurations. Checks for orphaned records where a month-year has only Domestic OR only Global configuration.

### Response Format

**Status Code:** `200 OK`

**Valid Configuration:**
```json
{
  "success": true,
  "data": {
    "is_valid": true,
    "orphaned_records": [],
    "total_configs": 48,
    "paired_count": 24,
    "orphaned_count": 0,
    "recommendations": []
  }
}
```

**Invalid Configuration (has orphans):**
```json
{
  "success": true,
  "data": {
    "is_valid": false,
    "orphaned_records": [
      {
        "month": "January",
        "year": 2025,
        "existing_type": "Domestic",
        "existing_id": 1,
        "missing_type": "Global",
        "working_days": 21,
        "occupancy": 0.95,
        "shrinkage": 0.10,
        "work_hours": 9
      }
    ],
    "total_configs": 47,
    "paired_count": 23,
    "orphaned_count": 1,
    "recommendations": [
      "Found 1 orphaned configuration(s). Add the missing work type for each month-year to fix.",
      "Use POST /api/month-config to add missing configurations, or DELETE /api/month-config/{id} to remove orphaned records."
    ]
  }
}
```

---

# Part 2: Target CPH Configuration API

**Base Path:** `/api/target-cph`

## Important Concepts

### What is Target CPH?
Target CPH (Cases Per Hour) represents the expected productivity rate for a specific combination of:
- **Main LOB** (Line of Business): e.g., "Amisys Medicaid GLOBAL", "Facets Medicare Domestic"
- **Case Type**: e.g., "FTC-Basic/Non MMP", "Claims Processing"

### CPH Values
- Typical range: 3.0 to 17.0 (configurable: 0.1 to 200.0)
- Higher CPH = More productive (more cases processed per hour)
- Used in FTE calculations for allocation

### Data Structure
Each configuration record has:
- **MainLOB**: The line of business identifier
- **CaseType**: The case type identifier
- **TargetCPH**: The target cases per hour value

---

## 8. Get Target CPH Configurations

### Endpoint
```http
GET /api/target-cph
```

### Description
Retrieve Target CPH configurations with optional filtering by Main LOB and Case Type.

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `main_lob` | string | No | - | Filter by Main LOB (partial match, case-insensitive) |
| `case_type` | string | No | - | Filter by Case Type (partial match, case-insensitive) |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "data": {
    "count": 95,
    "configurations": [
      {
        "id": 1,
        "main_lob": "Amisys Medicaid GLOBAL",
        "case_type": "FTC-Basic/Non MMP",
        "target_cph": 12.0,
        "created_by": "admin",
        "updated_by": "admin",
        "created_datetime": "2025-02-09T10:30:00",
        "updated_datetime": "2025-02-09T10:30:00"
      },
      {
        "id": 2,
        "main_lob": "Amisys Medicaid GLOBAL",
        "case_type": "Claims Processing",
        "target_cph": 8.5,
        "created_by": "admin",
        "updated_by": "admin",
        "created_datetime": "2025-02-09T10:30:00",
        "updated_datetime": "2025-02-09T10:30:00"
      }
    ]
  }
}
```

### Example Requests

```bash
# Get all configurations
GET /api/target-cph

# Filter by Main LOB (partial match)
GET /api/target-cph?main_lob=Amisys

# Filter by Case Type
GET /api/target-cph?case_type=FTC

# Filter by both
GET /api/target-cph?main_lob=Amisys&case_type=Claims
```

### Caching
- **TTL:** 15 minutes (900 seconds)
- **Cache Key:** `target_cph:v1:{main_lob}:{case_type}`

---

## 9. Get Target CPH by ID

### Endpoint
```http
GET /api/target-cph/{config_id}
```

### Description
Get a specific Target CPH configuration by ID.

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `config_id` | integer | Yes | Configuration ID |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "data": {
    "id": 1,
    "main_lob": "Amisys Medicaid GLOBAL",
    "case_type": "FTC-Basic/Non MMP",
    "target_cph": 12.0,
    "created_by": "admin",
    "updated_by": "admin",
    "created_datetime": "2025-02-09T10:30:00",
    "updated_datetime": "2025-02-09T10:30:00"
  }
}
```

### Error Response

**Status Code:** `404 Not Found`

```json
{
  "success": false,
  "error": "Configuration with ID 999 not found"
}
```

---

## 10. Create Target CPH Configuration

### Endpoint
```http
POST /api/target-cph
```

### Description
Add a single Target CPH configuration to the database.

### Request Body

```json
{
  "main_lob": "Amisys Medicaid GLOBAL",
  "case_type": "FTC-Basic/Non MMP",
  "target_cph": 12.0,
  "created_by": "john.doe"
}
```

### Request Parameters

| Parameter | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `main_lob` | string | Yes | 1-255 chars, non-empty | Main line of business |
| `case_type` | string | Yes | 1-255 chars, non-empty | Case type identifier |
| `target_cph` | float | Yes | 0.1-200.0 | Target cases per hour |
| `created_by` | string | Yes | 1-100 chars, non-empty | Username |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "message": "Configuration added successfully (ID: 96)"
}
```

### Error Responses

**400 Bad Request** - Duplicate
```json
{
  "success": false,
  "error": "Configuration for MainLOB='Amisys Medicaid GLOBAL', CaseType='FTC-Basic/Non MMP' already exists (ID: 1)"
}
```

**400 Bad Request** - Validation Error
```json
{
  "success": false,
  "error": "TargetCPH must be at least 0.1, got -5.0"
}
```

### Example Request

```bash
curl -X POST http://your-domain.com/api/target-cph \
  -H "Content-Type: application/json" \
  -d '{
    "main_lob": "Amisys Medicaid GLOBAL",
    "case_type": "FTC-Basic/Non MMP",
    "target_cph": 12.0,
    "created_by": "john.doe"
  }'
```

---

## 11. Bulk Create Target CPH Configurations

### Endpoint
```http
POST /api/target-cph/bulk
```

### Description
Bulk add multiple Target CPH configurations. Duplicates are skipped automatically.

### Request Body

```json
{
  "configurations": [
    {
      "main_lob": "Amisys Medicaid GLOBAL",
      "case_type": "FTC-Basic/Non MMP",
      "target_cph": 12.0,
      "created_by": "admin"
    },
    {
      "main_lob": "Amisys Medicaid GLOBAL",
      "case_type": "Claims Processing",
      "target_cph": 8.5,
      "created_by": "admin"
    },
    {
      "main_lob": "Facets Medicare Domestic",
      "case_type": "Appeals",
      "target_cph": 5.0,
      "created_by": "admin"
    }
  ]
}
```

### Request Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `configurations` | array | Yes | Array of configuration objects (min 1) |

Each configuration object:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `main_lob` | string | Yes | Main line of business |
| `case_type` | string | Yes | Case type identifier |
| `target_cph` | float | Yes | Target cases per hour |
| `created_by` | string | Yes | Username |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "data": {
    "total": 95,
    "succeeded": 93,
    "failed": 0,
    "duplicates_skipped": 2,
    "errors": []
  },
  "message": "Bulk operation completed"
}
```

### Error Response - All Failed

**Status Code:** `400 Bad Request`

```json
{
  "success": false,
  "message": "All configurations failed",
  "data": {
    "total": 3,
    "succeeded": 0,
    "failed": 3,
    "duplicates_skipped": 0,
    "errors": [
      "Config 1 (Amisys/FTC): TargetCPH must be at least 0.1, got -5.0",
      "Config 2 (Facets/Claims): MainLOB cannot be empty",
      "Config 3 (/Appeals): CaseType cannot be empty"
    ]
  }
}
```

### Example Request

```bash
curl -X POST http://your-domain.com/api/target-cph/bulk \
  -H "Content-Type: application/json" \
  -d '{
    "configurations": [
      {
        "main_lob": "Amisys Medicaid GLOBAL",
        "case_type": "FTC-Basic/Non MMP",
        "target_cph": 12.0,
        "created_by": "admin"
      },
      {
        "main_lob": "Facets Medicare Domestic",
        "case_type": "Appeals",
        "target_cph": 5.0,
        "created_by": "admin"
      }
    ]
  }'
```

---

## 12. Update Target CPH Configuration

### Endpoint
```http
PUT /api/target-cph/{config_id}
```

### Description
Update an existing Target CPH configuration. Can update target_cph, main_lob, and/or case_type.

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `config_id` | integer | Yes | Configuration ID to update |

### Request Body

```json
{
  "target_cph": 15.0,
  "main_lob": "Updated LOB Name",
  "case_type": "Updated Case Type",
  "updated_by": "john.doe"
}
```

### Request Parameters

| Parameter | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `target_cph` | float | No | 0.1-200.0 | New Target CPH value |
| `main_lob` | string | No | 1-255 chars | New Main LOB value |
| `case_type` | string | No | 1-255 chars | New Case Type value |
| `updated_by` | string | Yes | 1-100 chars | Username |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "message": "Configuration updated successfully"
}
```

### Error Responses

**404 Not Found**
```json
{
  "success": false,
  "error": "Configuration with ID 999 not found"
}
```

**400 Bad Request** - No changes
```json
{
  "success": false,
  "error": "No changes provided"
}
```

**409 Conflict** - Would create duplicate
```json
{
  "success": false,
  "error": "Update would create duplicate: MainLOB and CaseType combination already exists"
}
```

### Example Request

```bash
# Update only target_cph
curl -X PUT http://your-domain.com/api/target-cph/1 \
  -H "Content-Type: application/json" \
  -d '{
    "target_cph": 15.0,
    "updated_by": "john.doe"
  }'

# Update all fields
curl -X PUT http://your-domain.com/api/target-cph/1 \
  -H "Content-Type: application/json" \
  -d '{
    "target_cph": 15.0,
    "main_lob": "Updated LOB",
    "case_type": "Updated Case",
    "updated_by": "john.doe"
  }'
```

---

## 13. Delete Target CPH Configuration

### Endpoint
```http
DELETE /api/target-cph/{config_id}
```

### Description
Delete a Target CPH configuration by ID.

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `config_id` | integer | Yes | Configuration ID to delete |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "message": "Configuration deleted successfully"
}
```

### Error Response

**Status Code:** `404 Not Found`

```json
{
  "success": false,
  "error": "Configuration with ID 999 not found"
}
```

### Example Request

```bash
curl -X DELETE http://your-domain.com/api/target-cph/1
```

---

## 14. Get Distinct Main LOBs

### Endpoint
```http
GET /api/target-cph/distinct/main-lobs
```

### Description
Get a sorted list of distinct Main LOB values. Useful for populating dropdown filters.

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "data": {
    "count": 12,
    "main_lobs": [
      "Amisys Medicaid DOMESTIC",
      "Amisys Medicaid GLOBAL",
      "Amisys Medicare DOMESTIC",
      "Amisys Medicare GLOBAL",
      "Facets Medicaid DOMESTIC",
      "Facets Medicaid GLOBAL",
      "Facets Medicare DOMESTIC",
      "Facets Medicare GLOBAL",
      "OIC Volumes DOMESTIC",
      "OIC Volumes GLOBAL"
    ]
  }
}
```

---

## 15. Get Distinct Case Types

### Endpoint
```http
GET /api/target-cph/distinct/case-types
```

### Description
Get a sorted list of distinct Case Type values. Can be filtered by Main LOB.

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `main_lob` | string | No | Filter Case Types by Main LOB |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "data": {
    "count": 15,
    "case_types": [
      "Appeals",
      "Claims Processing",
      "Enrollment",
      "FTC-Basic/Non MMP",
      "FTC-Complex",
      "Member Services",
      "Provider Services"
    ]
  }
}
```

### Example Requests

```bash
# Get all distinct case types
GET /api/target-cph/distinct/case-types

# Get case types for Amisys LOBs only
GET /api/target-cph/distinct/case-types?main_lob=Amisys
```

---

## 16. Get Target CPH Count

### Endpoint
```http
GET /api/target-cph/count
```

### Description
Get the total count of Target CPH configurations in the database.

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "data": {
    "count": 95
  }
}
```

---

# Appendix

## Data Models

### MonthConfigurationModel

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | INTEGER | No | Primary key |
| Month | VARCHAR(15) | No | Month name (January-December) |
| Year | INTEGER | No | Year (e.g., 2025) |
| WorkType | VARCHAR(20) | No | "Domestic" or "Global" |
| WorkingDays | INTEGER | No | Business days in month |
| Occupancy | FLOAT | No | Occupancy rate (0.0-1.0) |
| Shrinkage | FLOAT | No | Shrinkage rate (0.0-1.0) |
| WorkHours | FLOAT | No | Work hours per day |
| CreatedBy | VARCHAR(100) | No | Username who created |
| CreatedDateTime | DATETIME | No | Creation timestamp |
| UpdatedBy | VARCHAR(100) | No | Username who last updated |
| UpdatedDateTime | DATETIME | No | Last update timestamp |

**Constraints:**
- Unique: `(Month, Year, WorkType)`
- Indexes: `(Month, Year, WorkType)`, `(Month, Year)`

### TargetCPHModel

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | INTEGER | No | Primary key |
| MainLOB | VARCHAR(255) | No | Main line of business |
| CaseType | VARCHAR(255) | No | Case type identifier |
| TargetCPH | FLOAT | No | Target cases per hour |
| CreatedBy | VARCHAR(100) | No | Username who created |
| CreatedDateTime | DATETIME | No | Creation timestamp |
| UpdatedBy | VARCHAR(100) | No | Username who last updated |
| UpdatedDateTime | DATETIME | No | Last update timestamp |

**Constraints:**
- Unique: `(MainLOB, CaseType)`
- Indexes: `MainLOB`, `CaseType`, `(MainLOB, CaseType)`

---

## FTE Calculation Formulas

### FTE Required Formula
```
FTE Required = ceil(Client_Forecast / (Target_CPH × WorkHours × (1 - Shrinkage) × WorkingDays))
```

**Note:** Occupancy is NOT used in FTE Required calculation.

### Capacity Formula
```
Capacity = Target_CPH × FTE_Available × (1 - Shrinkage) × WorkingDays × WorkHours
```

### Example Calculation

Given:
- Client Forecast: 10,000 cases
- Target CPH: 12.0
- Work Hours: 9
- Shrinkage: 0.10 (10%)
- Working Days: 21

```
FTE Required = ceil(10000 / (12.0 × 9 × 0.90 × 21))
             = ceil(10000 / 2041.2)
             = ceil(4.899)
             = 5 FTEs
```

---

## Caching Strategy

### Month Configuration Cache

| Cache | TTL | Max Size | Key Pattern |
|-------|-----|----------|-------------|
| `month_config_cache` | 15 min | 20 | `month_config:v1:{month}:{year}:{work_type}` |

### Target CPH Cache

| Cache | TTL | Max Size | Key Pattern |
|-------|-----|----------|-------------|
| `target_cph_cache` | 15 min | 20 | `target_cph:v1:{main_lob}:{case_type}` |
| `target_cph_lookup_cache` | 30 min | 1 | `target_cph_lookup:v1` |

### Cache Invalidation

Caches are automatically invalidated on:
- **CREATE** (POST) operations
- **UPDATE** (PUT) operations
- **DELETE** operations

---

## Error Handling

### Standard Error Response Format

```json
{
  "success": false,
  "error": "Error message",
  "details": "Optional additional details"
}
```

### HTTP Status Codes

| Code | Meaning | When Used |
|------|---------|-----------|
| 200 | OK | Successful operation |
| 400 | Bad Request | Validation error, duplicate, no changes |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Would orphan record, would create duplicate |
| 422 | Unprocessable Entity | Pydantic validation failed |
| 500 | Internal Server Error | Unexpected server error |

### Common Error Messages

**Month Configuration:**
- "Configuration for {month} {year} ({work_type}) already exists"
- "Configuration with ID {id} not found"
- "Cannot delete - would orphan {opposite_type} configuration"
- "Batch validation failed: Missing pairs..."

**Target CPH:**
- "Configuration for MainLOB='{lob}', CaseType='{type}' already exists"
- "Configuration with ID {id} not found"
- "TargetCPH must be at least 0.1, got {value}"
- "TargetCPH cannot exceed 200.0, got {value}"
- "MainLOB cannot be empty"
- "CaseType cannot be empty"
- "No changes provided"

---

## Changelog

### Version 1.1.0 (2025-02-09)
- Added Target CPH Configuration API
- Combined Month Config and Target CPH into single specification
- Added batch lookup functionality for Target CPH
- Added distinct value endpoints for dropdowns

### Version 1.0.0 (2025-01-03)
- Initial Month Configuration API specification
- CRUD endpoints for month configurations
- Pairing validation
- Bulk operations
- Data integrity validation
