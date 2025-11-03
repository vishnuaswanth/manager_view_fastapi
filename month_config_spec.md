# Month Configuration API Specification

## Overview
This document describes the API endpoints for managing month configuration data used in allocation calculations. Month configurations store working parameters (working days, occupancy, shrinkage, work hours) for each month and year, separated by work type (Domestic vs Global).

**Base URL:** `http://your-domain.com`

**Version:** v1

---

## Table of Contents
1. [Get Month Configurations](#1-get-month-configurations)
2. [Create Month Configuration](#2-create-month-configuration)
3. [Bulk Create Configurations](#3-bulk-create-configurations)
4. [Update Month Configuration](#4-update-month-configuration)
5. [Delete Month Configuration](#5-delete-month-configuration)
6. [Seed Initial Data](#6-seed-initial-data)
7. [Validate Configurations](#7-validate-configurations)
8. [Pairing Rules](#pairing-rules)
9. [Example Use Cases](#example-use-cases)
10. [Performance Notes](#performance-notes)

---

## Important Concepts

### Work Types
All configurations must specify a work type:
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
| `work_hours` | integer | 1-24 | Work hours per day |

### FTE Calculation Formula
```
FTE Required = Volume / (Target_CPH × WorkHours × Occupancy × (1 - Shrinkage) × WorkingDays)
```

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

**Get all configurations:**
```bash
GET /api/month-config
```

**Get configurations for specific month/year:**
```bash
GET /api/month-config?month=January&year=2025
```

**Get only Domestic configurations:**
```bash
GET /api/month-config?work_type=Domestic
```

**Get Domestic configs for January 2025:**
```bash
GET /api/month-config?month=January&year=2025&work_type=Domestic
```

**Get all configurations for 2025:**
```bash
GET /api/month-config?year=2025
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique configuration ID |
| `month` | string | Month name (January-December) |
| `year` | integer | Year (2020-2100) |
| `work_type` | string | "Domestic" or "Global" |
| `working_days` | integer | Number of working days |
| `occupancy` | float | Occupancy rate (0.0-1.0) |
| `shrinkage` | float | Shrinkage rate (0.0-1.0) |
| `work_hours` | integer | Work hours per day |
| `created_by` | string | Username who created the config |
| `updated_by` | string | Username who last updated |
| `created_datetime` | string (ISO 8601) | Creation timestamp |
| `updated_datetime` | string (ISO 8601) | Last update timestamp |

### Error Responses

**500 Internal Server Error**
```json
{
  "success": false,
  "error": "Internal server error",
  "details": "Error message",
  "status_code": 500
}
```

### Ordering
Results are ordered by:
1. Year (descending)
2. Month (chronological)
3. Work type (alphabetical)

### Caching
- **TTL:** 15 minutes (900 seconds)
- **Cache Key:** `month_config:v1:{month}:{year}:{work_type}`
- **Invalidation:** Automatically cleared on create/update/delete operations

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
| `work_hours` | integer | Yes | 1-24 | Work hours per day |
| `created_by` | string | Yes | Non-empty | Username |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "message": "Configuration added successfully"
}
```

### Example Request

```bash
curl -X POST http://your-domain.com/api/month-config \
  -H "Content-Type: application/json" \
  -d '{
    "month": "January",
    "year": 2025,
    "work_type": "Domestic",
    "working_days": 21,
    "occupancy": 0.95,
    "shrinkage": 0.10,
    "work_hours": 9,
    "created_by": "john.doe"
  }'
```

### Error Responses

**400 Bad Request** - Validation error
```json
{
  "success": false,
  "error": "Configuration already exists for January 2025 Domestic",
  "status_code": 400
}
```

**500 Internal Server Error**
```json
{
  "success": false,
  "error": "Internal server error",
  "details": "Error message",
  "status_code": 500
}
```

### Notes
- Duplicate configurations (same month/year/work_type) will be rejected
- Cache is automatically invalidated after successful creation
- Remember to create BOTH Domestic and Global configs for each month/year

---

## 3. Bulk Create Configurations

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
| `skip_pairing_validation` | boolean | No | false | Skip pairing validation (use with caution) |

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

### Example Request

```bash
curl -X POST http://your-domain.com/api/month-config/bulk \
  -H "Content-Type: application/json" \
  -d '{
    "created_by": "admin",
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
  }'
```

### Pairing Validation

When `skip_pairing_validation` is `false` (default), the API validates that for each (month, year) in the batch, BOTH Domestic and Global configurations are present.

**Valid Batch Example:**
```json
[
  {"month": "January", "year": 2025, "work_type": "Domestic", ...},
  {"month": "January", "year": 2025, "work_type": "Global", ...}
]
```

**Invalid Batch Example (missing Global):**
```json
[
  {"month": "January", "year": 2025, "work_type": "Domestic", ...}
]
```

### Error Responses

**400 Bad Request** - Validation failed
```json
{
  "message": "Batch validation failed",
  "validation_errors": [
    "Missing Global configuration for January 2025"
  ],
  "total": 1
}
```

**500 Internal Server Error**
```json
{
  "success": false,
  "error": "Internal server error",
  "details": "Error message",
  "status_code": 500
}
```

### Notes
- Cache is invalidated only if at least one configuration is successfully added
- Partial success is possible - check the `succeeded` and `failed` counts
- Use `skip_pairing_validation: true` only for migrations or special cases

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

### Request Body

```json
{
  "working_days": 22,
  "occupancy": 0.96,
  "shrinkage": 0.12,
  "work_hours": 8,
  "updated_by": "john.doe"
}
```

### Request Parameters

| Parameter | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `working_days` | integer | No | 1-31 | New working days value |
| `occupancy` | float | No | 0.0-1.0 | New occupancy rate |
| `shrinkage` | float | No | 0.0-1.0 | New shrinkage rate |
| `work_hours` | integer | No | 1-24 | New work hours value |
| `updated_by` | string | No | Non-empty | Username (default: "System") |

### Response Format

**Status Code:** `200 OK`

```json
{
  "success": true,
  "message": "Configuration updated successfully"
}
```

### Example Requests

**Update all parameters:**
```bash
curl -X PUT http://your-domain.com/api/month-config/123 \
  -H "Content-Type: application/json" \
  -d '{
    "working_days": 22,
    "occupancy": 0.96,
    "shrinkage": 0.12,
    "work_hours": 8,
    "updated_by": "john.doe"
  }'
```

**Update only occupancy:**
```bash
curl -X PUT http://your-domain.com/api/month-config/123 \
  -H "Content-Type: application/json" \
  -d '{
    "occupancy": 0.97,
    "updated_by": "john.doe"
  }'
```

### Error Responses

**404 Not Found** - Configuration doesn't exist
```json
{
  "success": false,
  "error": "Configuration with ID 123 not found",
  "status_code": 404
}
```

**500 Internal Server Error**
```json
{
  "success": false,
  "error": "Internal server error",
  "details": "Error message",
  "status_code": 500
}
```

### Notes
- You cannot update `month`, `year`, or `work_type` - delete and recreate instead
- Cache is automatically invalidated after successful update
- `updated_datetime` is automatically set to current timestamp

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

### Example Requests

**Normal delete (with orphan protection):**
```bash
DELETE /api/month-config/123
```

**Force delete (ignore orphan protection):**
```bash
DELETE /api/month-config/123?allow_orphan=true
```

### Orphan Prevention

By default, the API prevents creating orphaned records:

**Scenario:** You have both Domestic and Global configs for January 2025
- Deleting Domestic: **Blocked** (would orphan Global)
- Deleting Global: **Blocked** (would orphan Domestic)
- Deleting both: **Allowed** (no orphan created)

**Override with `allow_orphan=true`:**
```bash
DELETE /api/month-config/123?allow_orphan=true
```

⚠️ **Warning:** Using `allow_orphan=true` may cause inconsistent allocation calculations.

### Error Responses

**404 Not Found** - Configuration doesn't exist
```json
{
  "success": false,
  "error": "Configuration with ID 123 not found",
  "status_code": 404
}
```

**409 Conflict** - Would orphan paired configuration
```json
{
  "success": false,
  "error": "Cannot delete: would orphan Global configuration for January 2025. Delete both or use allow_orphan=true",
  "status_code": 409
}
```

**500 Internal Server Error**
```json
{
  "success": false,
  "error": "Internal server error",
  "details": "Error message",
  "status_code": 500
}
```

### Notes
- Cache is automatically invalidated after successful deletion
- Consider using bulk operations to delete pairs atomically

---

## 6. Seed Initial Data

### Endpoint
```http
POST /api/month-config/seed
```

### Description
Seed the database with initial month configuration data for deployment. Creates configurations for all 12 months for the specified number of years, for both Domestic and Global work types.

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

| Parameter | Domestic | Global |
|-----------|----------|--------|
| Occupancy | 0.95 (95%) | 0.90 (90%) |
| Shrinkage | 0.10 (10%) | 0.15 (15%) |
| Work Hours | 9 | 9 |
| Working Days | 20-22 (varies by month) | 20-22 (varies by month) |

### Working Days by Month

| Month | Working Days |
|-------|--------------|
| January | 21 |
| February | 20 |
| March | 22 |
| April | 21 |
| May | 21 |
| June | 21 |
| July | 22 |
| August | 22 |
| September | 21 |
| October | 22 |
| November | 21 |
| December | 21 |

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

### Example Requests

**Seed 2 years starting from 2025 (default):**
```bash
POST /api/month-config/seed
```

**Seed 3 years starting from 2024:**
```bash
curl -X POST http://your-domain.com/api/month-config/seed \
  -H "Content-Type: application/json" \
  -d '{
    "base_year": 2024,
    "num_years": 3,
    "created_by": "admin"
  }'
```

**Result:** Creates 72 configurations (12 months × 3 years × 2 work types)

### Error Responses

**500 Internal Server Error**
```json
{
  "success": false,
  "error": "Internal server error",
  "details": "Error message",
  "status_code": 500
}
```

### Notes
- Use this endpoint for initial deployment or data reset
- Configurations already exist will be skipped (not duplicated)
- This endpoint does not invalidate cache (intentional for bulk seeding)

---

## 7. Validate Configurations

### Endpoint
```http
GET /api/month-config/validate
```

### Description
Validate data integrity of month configurations. Checks for orphaned records where a month-year has only Domestic OR only Global configuration.

### Response Format

**Status Code:** `200 OK`

**Valid Configuration (all paired):**
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
        "id": 123,
        "month": "January",
        "year": 2025,
        "work_type": "Domestic",
        "issue": "Missing Global configuration"
      }
    ],
    "total_configs": 47,
    "paired_count": 23,
    "orphaned_count": 1,
    "recommendations": [
      "Add Global configuration for January 2025",
      "Or delete Domestic configuration for January 2025"
    ]
  }
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `is_valid` | boolean | True if all configurations are properly paired |
| `orphaned_records` | array | List of orphaned configurations |
| `total_configs` | integer | Total configurations in database |
| `paired_count` | integer | Number of properly paired month-years |
| `orphaned_count` | integer | Number of orphaned configurations |
| `recommendations` | array | Suggested actions to fix issues |

### Example Request

```bash
GET /api/month-config/validate
```

### Use Cases

1. **Pre-deployment Check:** Validate before running allocation
2. **Data Integrity Audit:** Regular checks for data consistency
3. **Troubleshooting:** Identify missing configurations
4. **QA Testing:** Verify bulk operations completed successfully

### Error Responses

**500 Internal Server Error**
```json
{
  "success": false,
  "error": "Internal server error",
  "details": "Error message",
  "status_code": 500
}
```

### Caching
- **TTL:** 5 minutes (300 seconds)
- **Cache Key:** `month_config_validate:v1`
- **Invalidation:** Automatically cleared on any configuration change

---

## Pairing Rules

### What is Pairing?

Each **(month, year)** combination MUST have BOTH:
- One **Domestic** configuration
- One **Global** configuration

### Why Pairing Matters

Allocation calculations require both Domestic and Global parameters:

```
Total FTE = Domestic FTE + Global FTE

Where:
- Domestic FTE uses Domestic configuration
- Global FTE uses Global configuration
```

Missing either configuration causes allocation failures.

### Valid Configuration

✅ **Properly Paired:**
```
January 2025:
  ├─ Domestic (id=1, occupancy=0.95, ...)
  └─ Global   (id=2, occupancy=0.90, ...)

February 2025:
  ├─ Domestic (id=3, occupancy=0.95, ...)
  └─ Global   (id=4, occupancy=0.90, ...)
```

### Invalid Configuration

❌ **Orphaned Record:**
```
January 2025:
  └─ Domestic (id=1, occupancy=0.95, ...)
  (Missing Global configuration!)
```

### API Enforcement

| Operation | Enforcement |
|-----------|-------------|
| **POST /api/month-config** | No enforcement (allows creating one at a time) |
| **POST /api/month-config/bulk** | ✅ Enforced by default (can be skipped) |
| **DELETE /api/month-config/{id}** | ✅ Enforced by default (can be overridden) |
| **GET /api/month-config/validate** | ✅ Reports violations |

### Best Practices

1. **Use bulk operations:** Create pairs atomically
2. **Validate before deployment:** Run validate endpoint
3. **Delete pairs together:** Avoid orphaning
4. **Monitor validation:** Set up periodic checks

---

## Example Use Cases

### Use Case 1: Initial Setup

Create configurations for entire year:

```bash
# Option 1: Use seed endpoint (fastest)
curl -X POST http://your-domain.com/api/month-config/seed \
  -H "Content-Type: application/json" \
  -d '{
    "base_year": 2025,
    "num_years": 1,
    "created_by": "admin"
  }'

# Option 2: Use bulk endpoint with custom values
curl -X POST http://your-domain.com/api/month-config/bulk \
  -H "Content-Type: application/json" \
  -d '{
    "created_by": "admin",
    "configurations": [
      {"month": "January", "year": 2025, "work_type": "Domestic", ...},
      {"month": "January", "year": 2025, "work_type": "Global", ...},
      ...
    ]
  }'
```

---

### Use Case 2: Monthly Configuration Update

Update configurations for a specific month:

```bash
# Step 1: Get current configurations for January 2025
GET /api/month-config?month=January&year=2025

# Step 2: Update Domestic configuration
curl -X PUT http://your-domain.com/api/month-config/123 \
  -H "Content-Type: application/json" \
  -d '{
    "working_days": 22,
    "updated_by": "john.doe"
  }'

# Step 3: Update Global configuration
curl -X PUT http://your-domain.com/api/month-config/124 \
  -H "Content-Type: application/json" \
  -d '{
    "working_days": 22,
    "updated_by": "john.doe"
  }'
```

---

### Use Case 3: Holiday Adjustments

Adjust working days for holiday months:

```bash
# December has fewer working days due to holidays
curl -X PUT http://your-domain.com/api/month-config/145 \
  -H "Content-Type: application/json" \
  -d '{
    "working_days": 18,
    "updated_by": "admin"
  }'

curl -X PUT http://your-domain.com/api/month-config/146 \
  -H "Content-Type: application/json" \
  -d '{
    "working_days": 18,
    "updated_by": "admin"
  }'
```

---

### Use Case 4: Data Integrity Check

Validate before running allocation:

```bash
# Step 1: Validate all configurations
GET /api/month-config/validate

# Step 2: If invalid, identify issues
# Response shows orphaned records and recommendations

# Step 3: Fix issues (add missing configs or delete orphans)
```

---

### Use Case 5: Reporting

Generate configuration report for specific period:

```bash
# Get all 2025 configurations
GET /api/month-config?year=2025

# Frontend can then:
# - Display in table format
# - Export to Excel
# - Compare Domestic vs Global parameters
# - Identify configuration trends
```

---

## Performance Notes

### 1. Caching Strategy

**GET Endpoint:**
- Cached for 15 minutes
- Separate cache keys for different filter combinations
- Cache invalidated on any write operation (POST/PUT/DELETE)

**Validate Endpoint:**
- Cached for 5 minutes
- Single cache key (validates all configs)
- Cache invalidated on any configuration change

**Benefits:**
- Reduced database queries
- Faster response times
- Automatic invalidation ensures data freshness

---

### 2. Bulk Operations

**Advantages:**
- Atomic operations (all succeed or all fail)
- Single database transaction
- Automatic pairing validation
- Single cache invalidation

**Best Practices:**
- Prefer bulk operations over multiple single creates
- Use bulk for initial setup (seed or bulk endpoint)
- Batch updates when possible

---

### 3. Database Optimization

**Recommended Indexes:**
```sql
CREATE INDEX idx_month_year ON month_configuration (month, year);
CREATE INDEX idx_work_type ON month_configuration (work_type);
CREATE INDEX idx_month_year_work_type ON month_configuration (month, year, work_type);
```

**Query Performance:**
- List query (filtered): ~20ms
- List query (unfiltered): ~50ms
- Single update: ~10ms
- Validation query: ~30ms

---

### 4. Validation Overhead

**Pairing Validation:**
- Adds ~50-100ms to bulk operations
- Prevents data integrity issues
- Can be skipped with `skip_pairing_validation: true`

**Orphan Prevention:**
- Adds ~20ms to delete operations
- Critical for data integrity
- Can be overridden with `allow_orphan=true`

**Trade-off:** Small performance cost for significant data integrity benefit.

---

## Common Errors and Solutions

### Error: "Configuration already exists"

**Cause:** Attempting to create duplicate configuration (same month/year/work_type)

**Solution:**
- Check existing configurations first: `GET /api/month-config?month=January&year=2025`
- Use PUT to update instead of POST to create

---

### Error: "Missing Global configuration"

**Cause:** Bulk operation with incomplete pairs

**Solution:**
- Ensure each (month, year) has BOTH Domestic and Global
- Or use `skip_pairing_validation: true` (not recommended)

---

### Error: "Cannot delete - would orphan"

**Cause:** Attempting to delete one config from a pair

**Solution:**
- Delete both Domestic and Global configs
- Or use `allow_orphan=true` query parameter (not recommended)

---

### Error: "Invalid month name"

**Cause:** Month name must be full name (e.g., "January" not "Jan")

**Solution:** Use full month names: January, February, March, etc.

---

### Error: "Year out of range"

**Cause:** Year must be between 2020-2100

**Solution:** Use valid year range

---

## Notes

### Configuration Lifecycle

1. **Create** (POST) - Add new configuration
2. **Read** (GET) - Retrieve configurations
3. **Update** (PUT) - Modify parameters
4. **Delete** (DELETE) - Remove configuration
5. **Validate** (GET validate) - Check integrity

### Audit Trail

All configurations track:
- `created_by`: Who created it
- `created_datetime`: When created
- `updated_by`: Who last updated it
- `updated_datetime`: When last updated

### Future Enhancements

Potential improvements:
- Configuration versioning
- Bulk update endpoint
- Configuration templates
- Approval workflow
- Historical tracking

---

## Changelog

### Version 1.0.0 (2025-01-03)
- Initial API specification
- Added CRUD endpoints for month configurations
- Implemented pairing validation
- Added bulk operations
- Implemented caching with 15-minute TTL
- Added data integrity validation endpoint
