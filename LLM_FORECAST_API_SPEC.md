# LLM Forecast Data API Specification

**Version:** 1.1
**Last Updated:** 2026-01-27
**Target Audience:** LLM tools, AI agents, chatbots, automated systems

---

## Overview

The LLM Forecast Data endpoint provides comprehensive forecast data optimized for Large Language Model consumption. It includes rich metadata, configuration details, business insights, and calculated metrics that help LLMs understand capacity planning and resource allocation scenarios.

### Key Features

- **Rich Metadata**: Field descriptions, units, and calculation formulas
- **Configuration Context**: Working days, shrinkage, and occupancy parameters
- **Business Insights**: Staffing status, trend analysis, and risk indicators
- **Flexible Filtering**: Multiple filter options with intelligent precedence rules
- **Gap Analysis**: Automatic calculation of capacity vs forecast gaps
- **Cached Responses**: 60-second cache TTL for improved performance

---

## Endpoints

This API provides three endpoints:

0. **`GET /api/llm/forecast/available-reports`** - Discover available forecast reports (use this first!)
1. **`GET /api/llm/forecast/filter-options`** - Get available filter values for a specific report
2. **`GET /api/llm/forecast`** - Get comprehensive forecast data

### Recommended Workflow for LLMs

1. **Discover**: Call `/api/llm/forecast/available-reports` to see what forecast reports are available
2. **Validate**: Check if the user's requested month/year is in the available reports list
3. **Get filters**: Call `/api/llm/forecast/filter-options` for the month/year to get valid filter values
4. **Validate inputs**: Check user's filter values against the available options
5. **Query data**: Call `/api/llm/forecast` with validated parameters

---

## Endpoint 0: Available Reports

### Base Information

- **URL**: `/api/llm/forecast/available-reports`
- **Method**: `GET`
- **Purpose**: Discover which forecast reports are available
- **Authentication**: None (internal API)
- **Content-Type**: `application/json`
- **Cache TTL**: 5 minutes

### Query Parameters

None required. This endpoint returns all available forecast reports.

### Success Response (200 OK)

```json
{
  "success": true,
  "reports": [
    {
      "value": "2025-Mar",
      "display": "March 2025",
      "month": "March",
      "year": 2025,
      "is_valid": true,
      "status": "SUCCESS",
      "allocation_execution_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "forecast_file": "forecast_Mar_2025.xlsx",
      "roster_file": "roster_Mar_2025.xlsx",
      "created_at": "2025-03-15T10:30:00",
      "has_bench_allocation": true,
      "records_count": 1250,
      "data_freshness": "current"
    },
    {
      "value": "2025-Feb",
      "display": "February 2025",
      "month": "February",
      "year": 2025,
      "is_valid": false,
      "status": "SUCCESS",
      "allocation_execution_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "forecast_file": "forecast_Feb_2025.xlsx",
      "roster_file": "roster_Feb_2025.xlsx",
      "created_at": "2025-02-15T10:30:00",
      "has_bench_allocation": true,
      "records_count": 1180,
      "data_freshness": "outdated",
      "invalidated_at": "2025-03-01T09:00:00",
      "invalidated_reason": "New forecast uploaded"
    }
  ],
  "total_reports": 2,
  "valid_reports": 1,
  "outdated_reports": 1,
  "description": "List of available forecast reports. Use 'value' field to query /api/llm/forecast?month={month}&year={year}",
  "timestamp": "2025-01-27T10:30:00.000000Z"
}
```

### Response Fields

#### Report Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `value` | string | Formatted as "YYYY-MMM" for easy parsing (e.g., "2025-Mar") |
| `display` | string | Human-readable format "Month YYYY" (e.g., "March 2025") |
| `month` | string | Full month name for querying (e.g., "March") |
| `year` | integer | 4-digit year (e.g., 2025) |
| `is_valid` | boolean | True if allocation is current, False if invalidated |
| `status` | string | Allocation execution status ("SUCCESS", "FAILED", "PARTIAL_SUCCESS") |
| `allocation_execution_id` | string | UUID linking to allocation execution |
| `forecast_file` | string | Source forecast filename |
| `roster_file` | string | Source roster filename |
| `created_at` | string | When allocation was created (ISO 8601) |
| `has_bench_allocation` | boolean | Whether bench allocation completed |
| `records_count` | integer | Number of forecast records (optional) |
| `data_freshness` | string | "current" \| "outdated" - indicates data validity status |
| `invalidated_at` | string | When invalidated (ISO 8601, only if `is_valid=false`) |
| `invalidated_reason` | string | Why invalidated (only if `is_valid=false`) |

#### Summary Fields

| Field | Type | Description |
|-------|------|-------------|
| `total_reports` | integer | Total number of reports available |
| `valid_reports` | integer | Count of reports with `is_valid=true` |
| `outdated_reports` | integer | Count of reports with `is_valid=false` |

### Use Cases

**1. Discovery**
```
User: "What forecast data do you have?"
LLM: Calls /api/llm/forecast/available-reports
LLM: "I have forecast data for: March 2025 (current), February 2025 (outdated), January 2025 (current)"
```

**2. Validation Before Query**
```
User: "Show me forecast for December 2030"
LLM: Calls /api/llm/forecast/available-reports
LLM: Checks if "2030-Dec" is in available reports
LLM: "I don't have data for December 2030. Available reports: March 2025, February 2025, January 2025"
```

**3. Data Freshness Check**
```
User: "Is the February data current?"
LLM: Calls /api/llm/forecast/available-reports
LLM: Checks is_valid and data_freshness fields for February 2025
LLM: "February 2025 data was invalidated on March 1st due to 'New forecast uploaded'. The current data is for March 2025."
```

**4. Latest Data Auto-Selection**
```
User: "Show me the latest forecast"
LLM: Calls /api/llm/forecast/available-reports
LLM: Finds first report with is_valid=true (reports are sorted newest first)
LLM: "I'll show you the latest forecast for March 2025"
```

### Error Response (500 Internal Server Error)

```json
{
  "success": false,
  "error": "Internal server error",
  "status_code": 500,
  "timestamp": "2025-01-27T10:30:00.000000Z"
}
```

### Implementation Notes

- Reports are sorted by year DESC, then month DESC (newest first)
- If no reports are available, returns `"reports": []` with `"total_reports": 0` (not an error)
- Only reports that have completed allocation execution are returned
- Cache TTL is 5 minutes to balance freshness and performance
- Reports with `is_valid=false` are still returned but marked as outdated

---

## Endpoint 1: Filter Options

### Base Information

- **URL**: `/api/llm/forecast/filter-options`
- **Method**: `GET`
- **Purpose**: Get available filter values for validation and discovery
- **Authentication**: None (internal API)
- **Content-Type**: `application/json`
- **Cache TTL**: 5 minutes

### Query Parameters

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `month` | string | Report month (full name) | `"January"`, `"February"` |
| `year` | integer | Report year | `2025`, `2026` |

### Success Response (200 OK)

```json
{
  "success": true,
  "month": "March",
  "year": 2025,
  "filter_options": {
    "platforms": ["Amisys", "Facets", "Xcelys"],
    "markets": ["Medicaid", "Medicare", "OIC Volumes"],
    "localities": ["Domestic", "Global"],
    "main_lobs": [
      "Amisys Medicaid Domestic",
      "Amisys Medicare Global",
      "Facets Medicaid Domestic",
      "Facets OIC Volumes"
    ],
    "states": ["CA", "FL", "GA", "N/A", "TX"],
    "case_types": [
      "Claims Processing",
      "Enrollment",
      "Member Services"
    ],
    "forecast_months": ["Apr-25", "May-25", "Jun-25", "Jul-25", "Aug-25", "Sep-25"]
  },
  "record_count": 1250,
  "description": "Available filter values for the specified month and year. Use these to validate user input before querying /api/llm/forecast.",
  "timestamp": "2025-01-23T10:30:00.000000Z"
}
```

### Use Cases

**1. Input Validation**
```
User: "Show me forecast for Amyss platform"
LLM: Calls filter-options, sees available platforms: ["Amisys", "Facets", "Xcelys"]
LLM: "Did you mean 'Amisys'? (Note: 'Amyss' is not available)"
```

**2. Auto-Correction**
```
User: "Filter by state TX and californa"
LLM: Calls filter-options, sees states: ["CA", "FL", "TX", ...]
LLM: Corrects "californa" → "CA", keeps "TX"
LLM: Queries with state[]=TX&state[]=CA
```

**3. Discovery**
```
User: "What platforms are available?"
LLM: Calls filter-options
LLM: "Available platforms for March 2025: Amisys, Facets, Xcelys"
```

**4. Spelling Suggestions**
```
User: "Show Facetz data"
LLM: Calls filter-options, finds closest match using fuzzy matching
LLM: "Did you mean 'Facets'? Other options: Amisys, Xcelys"
```

---

## Endpoint 2: Forecast Data

### Base Information

- **URL**: `/api/llm/forecast`
- **Method**: `GET`
- **Purpose**: Get comprehensive forecast data with insights
- **Authentication**: None (internal API)
- **Content-Type**: `application/json`
- **Cache TTL**: 60 seconds

### Rate Limiting

Responses are cached for 60 seconds with a maximum of 64 cache entries. Subsequent requests with identical parameters within the cache window return cached data.

---

## Query Parameters

### Required Parameters

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `month` | string | Report month (full name) | `"January"`, `"February"` |
| `year` | integer | Report year | `2025`, `2026` |

### Optional Filter Parameters (Multi-value)

All optional filters accept multiple values using array syntax (`param[]=value1&param[]=value2`).

| Parameter | Type | Description | Example | Multi-value |
|-----------|------|-------------|---------|-------------|
| `platform` | string[] | Technology platforms | `"Amisys"`, `"Facets"`, `"Xcelys"` | Yes |
| `market` | string[] | Insurance market segments | `"Medicaid"`, `"Medicare"` | Yes |
| `locality` | string[] | Workforce location types | `"Domestic"`, `"Global"` | Yes |
| `main_lob` | string[] | Specific LOB strings | `"Amisys Medicaid Domestic"` | Yes |
| `state` | string[] | US state codes or 'N/A' | `"CA"`, `"TX"`, `"N/A"` | Yes |
| `case_type` | string[] | Work process types | `"Claims Processing"` | Yes |
| `forecast_months` | string[] | Month labels to include | `"Apr-25"`, `"May-25"` | Yes |

---

## Filter Logic Rules

### 1. Filter Precedence

**If `main_lob[]` is provided:** The `platform[]`, `market[]`, and `locality[]` filters are **IGNORED**.

This allows specific LOB filtering without needing to decompose into components.

**Example:**
```
GET /api/llm/forecast?month=March&year=2025&main_lob[]=Amisys Medicaid Domestic
```
This will filter only by Main_LOB, ignoring any platform/market/locality filters.

### 2. Locality Determination Algorithm

Locality is determined using a multi-step process:

1. **Parse Main_LOB**: Extract the last word if it matches known localities (`Domestic`, `Global`, `Offshore`, `Onshore`)

2. **Special Case - OIC Volumes**: If Main_LOB contains both "oic" AND "volumes":
   - Check `Case_Type` field
   - If Case_Type contains "domestic" → `Domestic`
   - Otherwise → `Global`

3. **Normalization**: Apply standard normalization:
   - `"Offshore"` or `"OFFSHORE"` → `"Global"`
   - `"Onshore"` or `"DOMESTIC"` → `"Domestic"`

4. **Default**: If no locality found, default to `"Global"`

### 3. Multi-value Filter Behavior

All filters use **AND logic** between different filter types and **OR logic** within the same filter type.

**Example:**
```
GET /api/llm/forecast?month=March&year=2025&platform[]=Amisys&state[]=CA&state[]=TX
```

This returns records where:
- Platform is "Amisys" **AND**
- State is "CA" **OR** "TX"

### 4. Case-Insensitive Matching

**All filter matching is case-insensitive.** You can use any case combination and it will match correctly.

**Examples:**

| User Input | Database Value | Match Result |
|------------|----------------|--------------|
| `platform[]=amisys` | `"Amisys"` | ✅ Match |
| `platform[]=AMISYS` | `"Amisys"` | ✅ Match |
| `platform[]=Amisys` | `"Amisys"` | ✅ Match |
| `state[]=ca` | `"CA"` | ✅ Match |
| `state[]=Ca` | `"CA"` | ✅ Match |
| `market[]=medicaid` | `"Medicaid"` | ✅ Match |
| `case_type[]=CLAIMS PROCESSING` | `"Claims Processing"` | ✅ Match |
| `main_lob[]=amisys medicaid domestic` | `"Amisys Medicaid Domestic"` | ✅ Match |

**Implementation:**
- All filter values are converted to lowercase before comparison
- All database values are converted to lowercase before comparison
- Original case is preserved in the response data

**LLM Benefit:** You don't need to worry about case normalization - just pass the user's input as-is!

### 4. forecast_months Filter

The `forecast_months[]` parameter filters which months appear in the response output, not which records are returned.

**Example:**
```
GET /api/llm/forecast?month=March&year=2025&forecast_months[]=Apr-25&forecast_months[]=May-25
```

Returns all records but only includes Apr-25 and May-25 month data in the `months` object.

---

## Response Schema

### Success Response (200 OK)

```json
{
  "success": true,
  "metadata": {
    "description": "Forecast data for capacity planning and resource allocation",
    "field_descriptions": {
      "forecast": "Client forecast demand (number of cases expected)",
      "fte_available": "Full-Time Equivalents available (number of resources)",
      "fte_required": "Full-Time Equivalents required to meet forecast demand",
      "capacity": "Total processing capacity (number of cases that can be handled)",
      "gap": "Capacity gap (capacity - forecast). Positive = overstaffed, negative = understaffed",
      "target_cph": "Target Cases Per Hour (productivity metric)",
      "platform": "Technology platform (Amisys, Facets, or Xcelys)",
      "market": "Insurance market segment (e.g., Medicaid, Medicare)",
      "locality": "Workforce location type (Domestic or Global/Offshore)",
      "main_lob": "Line of Business - combination of platform, market, and locality",
      "state": "US state code (e.g., CA, TX) or 'N/A' for non-state-specific work",
      "case_type": "Type of work or process (e.g., Claims Processing, Enrollment)",
      "case_id": "Unique identifier for the work type"
    },
    "units": {
      "forecast": "cases",
      "fte_available": "FTEs (Full-Time Equivalents)",
      "fte_required": "FTEs (Full-Time Equivalents)",
      "capacity": "cases",
      "gap": "cases",
      "target_cph": "cases per hour"
    },
    "formulas": {
      "fte_required": "ceil(forecast / (working_days × work_hours × (1 - shrinkage) × target_cph))",
      "capacity": "fte_available × working_days × work_hours × (1 - shrinkage) × target_cph",
      "gap": "capacity - forecast"
    }
  },
  "configuration": {
    "Apr-25": {
      "Domestic": {
        "working_days": 21,
        "work_hours": 9,
        "occupancy": 0.95,
        "shrinkage": 0.10,
        "description": "Domestic workforce parameters for FTE and capacity calculations"
      },
      "Global": {
        "working_days": 21,
        "work_hours": 9,
        "occupancy": 0.90,
        "shrinkage": 0.15,
        "description": "Global (Offshore) workforce parameters for FTE and capacity calculations"
      }
    },
    "May-25": {
      "Domestic": {
        "working_days": 22,
        "work_hours": 9,
        "occupancy": 0.95,
        "shrinkage": 0.10,
        "description": "Domestic workforce parameters for FTE and capacity calculations"
      },
      "Global": {
        "working_days": 22,
        "work_hours": 9,
        "occupancy": 0.90,
        "shrinkage": 0.15,
        "description": "Global (Offshore) workforce parameters for FTE and capacity calculations"
      }
    }
  },
  "months": {
    "Month1": "Apr-25",
    "Month2": "May-25",
    "Month3": "Jun-25",
    "Month4": "Jul-25",
    "Month5": "Aug-25",
    "Month6": "Sep-25"
  },
  "month": "March",
  "year": 2025,
  "records": [
    {
      "main_lob": "Amisys Medicaid Domestic",
      "state": "CA",
      "case_type": "Claims Processing",
      "case_id": "CP001",
      "target_cph": 50.0,
      "platform": "Amisys",
      "market": "Medicaid",
      "locality": "Domestic",
      "months": {
        "Apr-25": {
          "forecast": 1000.0,
          "fte_available": 10,
          "fte_required": 9,
          "capacity": 9500.0,
          "gap": 8500.0
        },
        "May-25": {
          "forecast": 1200.0,
          "fte_available": 10,
          "fte_required": 11,
          "capacity": 9500.0,
          "gap": 8300.0
        }
      }
    }
  ],
  "totals": {
    "Apr-25": {
      "forecast_total": 50000.0,
      "fte_available_total": 500,
      "fte_required_total": 475,
      "capacity_total": 475000.0,
      "gap_total": 425000.0
    },
    "May-25": {
      "forecast_total": 55000.0,
      "fte_available_total": 500,
      "fte_required_total": 522,
      "capacity_total": 475000.0,
      "gap_total": 420000.0
    }
  },
  "business_insights": {
    "staffing_status": {
      "Apr-25": {
        "status": "overstaffed",
        "gap_percentage": 850.0,
        "description": "Capacity is 850.0% above forecast demand"
      },
      "May-25": {
        "status": "overstaffed",
        "gap_percentage": 763.6,
        "description": "Capacity is 763.6% above forecast demand"
      }
    },
    "trend_analysis": {
      "forecast_trend": "increasing",
      "capacity_trend": "stable",
      "average_forecast_change_percentage": 10.0,
      "average_capacity_change_percentage": 0.0,
      "description": "Forecast demand increasing while capacity remains stable - potential future shortage"
    },
    "risk_indicators": [
      {
        "month": "Apr-25",
        "severity": "high",
        "message": "Significant capacity surplus (850.0% above demand)"
      }
    ]
  },
  "total_records": 1,
  "filters_applied": {
    "platform": [],
    "market": [],
    "locality": [],
    "main_lob": [],
    "state": [],
    "case_type": [],
    "forecast_months": []
  },
  "timestamp": "2025-01-23T10:30:00.000000Z"
}
```

### Error Responses

#### 400 Bad Request - Invalid Parameters

```json
{
  "success": false,
  "error": "month and year are required parameters",
  "status_code": 400,
  "timestamp": "2025-01-23T10:30:00.000000Z"
}
```

#### 400 Bad Request - Invalid Year

```json
{
  "success": false,
  "error": "Invalid year: 3000 (must be between 1900 and 2100)",
  "status_code": 400,
  "timestamp": "2025-01-23T10:30:00.000000Z"
}
```

#### 404 Not Found - No Data Uploaded

When no forecast data exists for the specified month and year:

```json
{
  "success": false,
  "error": "No forecast data found for March 2025",
  "message": "Please upload forecast data for March 2025 before querying this endpoint",
  "status_code": 404,
  "month": "March",
  "year": 2025,
  "timestamp": "2025-01-23T10:30:00.000000Z"
}
```

**Action Required:** Upload forecast data for the specified month and year.

#### 404 Not Found - No Records Match Filters

When filters are applied but no records match the criteria:

```json
{
  "success": false,
  "error": "No records match the applied filter criteria",
  "message": "Found 1250 total records for March 2025, but none matched your filters. Please check your filter parameters and try again.",
  "status_code": 404,
  "month": "March",
  "year": 2025,
  "total_records_before_filtering": 1250,
  "filters_applied": {
    "platform": ["Amisys"],
    "state": ["ZZ"]
  },
  "suggestions": [
    "Remove some filters to broaden your search",
    "Check that filter values match exactly (case-insensitive)",
    "Try querying without filters first to see available values",
    "Use GET /api/forecast/platforms, /markets, /localities to see valid filter options"
  ],
  "timestamp": "2025-01-23T10:30:00.000000Z"
}
```

**Action Required:** Adjust your filter parameters or remove some filters to broaden the search.

#### 500 Internal Server Error

```json
{
  "success": false,
  "error": "Internal server error",
  "status_code": 500,
  "timestamp": "2025-01-23T10:30:00.000000Z"
}
```

---

## Usage Examples

### Example 0: Get Filter Options (Start Here!)

**Always start by getting available filter options:**

```bash
curl -X GET "http://localhost:8000/api/llm/forecast/filter-options?month=March&year=2025"
```

**Response:**
```json
{
  "success": true,
  "month": "March",
  "year": 2025,
  "filter_options": {
    "platforms": ["Amisys", "Facets", "Xcelys"],
    "markets": ["Medicaid", "Medicare", "OIC Volumes"],
    "localities": ["Domestic", "Global"],
    "main_lobs": ["Amisys Medicaid Domestic", "Facets Medicare Global", ...],
    "states": ["CA", "FL", "GA", "N/A", "TX"],
    "case_types": ["Claims Processing", "Enrollment", "Member Services"],
    "forecast_months": ["Apr-25", "May-25", "Jun-25", "Jul-25", "Aug-25", "Sep-25"]
  },
  "record_count": 1250,
  "description": "Available filter values...",
  "timestamp": "2025-01-23T10:30:00.000000Z"
}
```

**Use this to:**
- Validate user input ("Is 'Amyss' a valid platform? No → suggest 'Amisys'")
- Show users available options ("Available platforms: Amisys, Facets, Xcelys")
- Auto-correct typos ("californa" → "CA")

---

### Example 1: Basic Query (No Filters)

Get all forecast data for March 2025:

```bash
curl -X GET "http://localhost:8000/api/llm/forecast?month=March&year=2025"
```

**Response:** All records for March 2025 with all 6 months of forecast data.

---

### Example 2: Filter by Platform and State

Get Amisys forecast data for California:

```bash
curl -X GET "http://localhost:8000/api/llm/forecast?month=March&year=2025&platform[]=Amisys&state[]=CA"
```

**Response:** Only Amisys records for California state.

**Case-insensitive variants (all work the same):**
```bash
# Lowercase
curl -X GET "http://localhost:8000/api/llm/forecast?month=March&year=2025&platform[]=amisys&state[]=ca"

# Uppercase
curl -X GET "http://localhost:8000/api/llm/forecast?month=March&year=2025&platform[]=AMISYS&state[]=CA"

# Mixed case
curl -X GET "http://localhost:8000/api/llm/forecast?month=March&year=2025&platform[]=AmIsYs&state[]=Ca"
```

All return identical results!

---

### Example 3: Filter by Specific Months

Get forecast data for only April and May 2025:

```bash
curl -X GET "http://localhost:8000/api/llm/forecast?month=March&year=2025&forecast_months[]=Apr-25&forecast_months[]=May-25"
```

**Response:** All records, but each record's `months` object only includes Apr-25 and May-25 data.

---

### Example 4: Filter by Main LOB

Get specific LOB data (overrides platform/market/locality filters):

```bash
curl -X GET "http://localhost:8000/api/llm/forecast?month=March&year=2025&main_lob[]=Amisys Medicaid Domestic"
```

**Response:** Only records matching "Amisys Medicaid Domestic" exactly.

---

### Example 5: Combine Multiple Filters

Get Domestic Medicaid data for California and Texas:

```bash
curl -X GET "http://localhost:8000/api/llm/forecast?month=March&year=2025&market[]=Medicaid&locality[]=Domestic&state[]=CA&state[]=TX"
```

**Response:** Medicaid records with Domestic locality for CA or TX states.

---

### Example 6: Full Validation Workflow (LLM Integration)

**Scenario:** User asks: "Show me Amyss forecast for Californa state"

**Step 1: Get filter options**
```bash
curl -X GET "http://localhost:8000/api/llm/forecast/filter-options?month=March&year=2025"
```

**Step 2: LLM validates input**
```
- User said "Amyss" → Check platforms: ["Amisys", "Facets", "Xcelys"]
  - Not found! Closest match: "Amisys" (1 character difference)
  - LLM response: "Did you mean 'Amisys'? (I couldn't find 'Amyss')"

- User said "Californa" → Check states: ["CA", "FL", "GA", "TX", ...]
  - Not found! But "Californa" looks like "California" → Map to "CA"
  - LLM response: "I'll filter by California (CA)"
```

**Step 3: Query with corrected filters**
```bash
curl -X GET "http://localhost:8000/api/llm/forecast?month=March&year=2025&platform[]=Amisys&state[]=CA"
```

**Step 4: LLM presents results**
```
"Here's the Amisys forecast for California (March 2025):
- Found 50 records
- Capacity status: Balanced (gap: 2.5%)
- Trend: Forecast increasing, capacity stable
- Recommendation: Monitor for potential shortage in coming months"
```

---

## Input Validation Patterns for LLMs

### Common Validation Scenarios

#### Scenario 1: Exact Match
```
User input: "Amisys"
Available: ["Amisys", "Facets", "Xcelys"]
Result: ✅ Valid - use as-is
```

#### Scenario 2: Case Mismatch (No Problem!)
```
User input: "amisys" or "AMISYS" or "AmIsYs"
Available: ["Amisys", "Facets", "Xcelys"]
Result: ✅ Valid - API is case-insensitive
Action: No correction needed - pass as-is
Note: API automatically handles case-insensitive matching
Response: "Filtering by Amisys platform..."
```

**Examples:**
```bash
# All of these work identically:
GET /api/llm/forecast?month=March&year=2025&platform[]=Amisys
GET /api/llm/forecast?month=March&year=2025&platform[]=amisys
GET /api/llm/forecast?month=March&year=2025&platform[]=AMISYS
GET /api/llm/forecast?month=March&year=2025&platform[]=AmIsYs
```

#### Scenario 3: Close Match (Typo)
```
User input: "Amyss"
Available: ["Amisys", "Facets", "Xcelys"]
Closest match: "Amisys" (edit distance: 1)
Action: Ask user "Did you mean 'Amisys'?"
```

#### Scenario 4: Abbreviation vs Full Name
```
User input: "California"
Available: ["CA", "FL", "GA", "TX", ...]
Action: Map state names to codes:
  - "California" → "CA"
  - "Texas" → "TX"
  - "Florida" → "FL"
Then validate against available codes
```

#### Scenario 5: Case + Typo (Need to Fix Typo Only)
```
User input: "AMYSS" (uppercase + typo)
Available: ["Amisys", "Facets", "Xcelys"]
Closest match: "Amisys" (edit distance: 1, case-insensitive)
Action: Typo needs correction, case doesn't matter
Response: "Did you mean 'Amisys'? (Note: case doesn't matter, but spelling does)"
```

#### Scenario 6: Invalid Value
```
User input: "Xylophone Platform"
Available: ["Amisys", "Facets", "Xcelys"]
Closest match: "Xcelys" (similarity: 30%)
Action: Too far to auto-correct
Response: "I couldn't find 'Xylophone Platform'. Available platforms are: Amisys, Facets, Xcelys"
```

#### Scenario 7: Multiple Typos
```
User input: "Facetz Medcaid Domestc"
Available:
  - platforms: ["Amisys", "Facets", "Xcelys"]
  - markets: ["Medicaid", "Medicare", "OIC Volumes"]
  - localities: ["Domestic", "Global"]

Corrections:
  - "Facetz" → "Facets" (1 char diff)
  - "Medcaid" → "Medicaid" (1 char diff)
  - "Domestc" → "Domestic" (1 char diff)

Action: Auto-correct all or ask for confirmation
Response: "I'll search for Facets Medicaid Domestic (corrected from 'Facetz Medcaid Domestc')"
```

### Summary: Case vs Typo

| Scenario | Issue | API Behavior | LLM Action |
|----------|-------|--------------|------------|
| `platform[]=amisys` | Different case | ✅ Matches "Amisys" | No action needed |
| `platform[]=AMISYS` | Different case | ✅ Matches "Amisys" | No action needed |
| `platform[]=Amyss` | Typo | ❌ No match | Suggest "Amisys" |
| `platform[]=AMYSS` | Case + Typo | ❌ No match | Suggest "Amisys" |
| `state[]=ca` | Different case | ✅ Matches "CA" | No action needed |
| `state[]=californa` | Typo | ❌ No match | Suggest "CA" or ask |

**Key Takeaway:** Case doesn't matter, spelling does!

### Fuzzy Matching Algorithm Recommendations

**For LLM implementations, use these techniques:**

1. **Levenshtein Distance** (edit distance)
   - Good for catching typos (1-2 character differences)
   - Threshold: Accept if distance ≤ 2

2. **Jaccard Similarity** (for multi-word)
   - Good for "Claims Processing" vs "Claim Processing"
   - Threshold: Accept if similarity ≥ 0.7

3. **Phonetic Matching** (optional)
   - Good for sound-alike errors: "Facets" vs "Facetz"
   - Use Soundex or Metaphone algorithms

**Example Implementation:**
```python
def find_best_match(user_input, valid_options, threshold=2):
    """Find closest match using Levenshtein distance."""
    from difflib import get_close_matches

    # Case-insensitive matching
    user_input_lower = user_input.lower()
    options_lower = {opt.lower(): opt for opt in valid_options}

    # Find close matches
    matches = get_close_matches(user_input_lower, options_lower.keys(), n=1, cutoff=0.6)

    if matches:
        # Return original case
        return options_lower[matches[0]]

    return None
```

### Error Response Handling

When filter-options returns 404:
```json
{
  "success": false,
  "error": "No forecast data found for December 2030",
  "message": "Please upload forecast data for December 2030 before querying filter options",
  "status_code": 404
}
```

**LLM Response:**
```
"I don't have forecast data for December 2030 yet.
Available data months: [list recent months]
Would you like to query a different month?"
```

---

## Business Insights Documentation

### Staffing Status

Indicates whether capacity is sufficient to meet forecast demand for each month.

#### Status Values

| Status | Condition | Description |
|--------|-----------|-------------|
| `understaffed` | gap% < -5% | Capacity is insufficient (more than 5% below demand) |
| `balanced` | -5% ≤ gap% ≤ 5% | Capacity is balanced with demand |
| `overstaffed` | gap% > 5% | Capacity exceeds demand (more than 5% above) |

#### Gap Percentage Formula

```
gap_percentage = (capacity - forecast) / forecast × 100
```

**Example:**
- Forecast: 1000 cases
- Capacity: 850 cases
- Gap: -150 cases
- Gap%: -15% (understaffed)

---

### Trend Analysis

Analyzes month-over-month changes in forecast and capacity.

#### Trend Values

| Trend | Condition | Description |
|-------|-----------|-------------|
| `increasing` | avg change > 5% | Value is increasing over time |
| `decreasing` | avg change < -5% | Value is decreasing over time |
| `stable` | -5% ≤ avg change ≤ 5% | Value remains relatively stable |

#### Interpretation

| Forecast Trend | Capacity Trend | Interpretation |
|----------------|----------------|----------------|
| Increasing | Stable | Potential future shortage - demand growing faster than capacity |
| Increasing | Increasing | Both growing - monitor gap percentage |
| Stable | Decreasing | Potential future shortage - losing capacity |
| Decreasing | Stable | Potential future surplus - demand declining |

---

### Risk Indicators

Flags months with significant staffing issues.

#### Severity Levels

| Severity | Condition | Description |
|----------|-----------|-------------|
| `high` | \|gap%\| > 10% | Critical staffing issue (>10% gap) |
| `medium` | 5% < \|gap%\| ≤ 10% | Moderate staffing issue (5-10% gap) |
| `low` | \|gap%\| ≤ 5% | Minor or no staffing issue |

---

## Caching Behavior

### Cache Strategy

- **TTL**: 60 seconds
- **Max Entries**: 64
- **Cache Key**: `llm:forecast:{year}:{month}:{filter_hash}`
- **Hash Function**: MD5 of sorted filter parameters (first 8 characters)

### Cache Invalidation

Cache entries automatically expire after 60 seconds. No manual invalidation is required.

### Cache Key Examples

```
llm:forecast:2025:March:a1b2c3d4
llm:forecast:2025:March:e5f6g7h8  # Different filters = different cache key
```

---

## Performance Notes

### Response Time

- **Cached**: < 10ms
- **Uncached (no filters)**: 100-500ms
- **Uncached (with filters)**: 150-600ms

### Response Size

- **Small dataset** (< 100 records): 50-100 KB
- **Medium dataset** (100-500 records): 100-500 KB
- **Large dataset** (> 500 records): 500 KB - 2 MB

### Optimization Tips

1. **Use specific filters** to reduce record count
2. **Limit forecast_months** to only needed months
3. **Reuse queries** within 60-second cache window
4. **Filter at database level** when possible (state, case_type)

---

## Integration Guide for LLM Tools

### Step-by-Step Integration Workflow

**Step 1: Get Available Filter Options**

Before accepting user filters, call the filter-options endpoint:

```python
# Example pseudo-code for LLM integration
response = GET("/api/llm/forecast/filter-options?month=March&year=2025")
available_options = response["filter_options"]

# Store for validation
valid_platforms = available_options["platforms"]  # ["Amisys", "Facets", "Xcelys"]
valid_states = available_options["states"]        # ["CA", "TX", "FL", ...]
valid_markets = available_options["markets"]      # ["Medicaid", "Medicare", ...]
```

**Step 2: Validate User Input**

Compare user input against available options (case-insensitive):

```python
user_input = "Show me forecast for AMYSS platform in californa"

# Extract entities
user_platform = "AMYSS"      # User's spelling (wrong + uppercase)
user_state = "californa"     # User's spelling (wrong + lowercase)

# Validate against available options (case-insensitive)
# Note: API does case-insensitive matching, but we still validate for typos

# Check platform (case-insensitive)
valid_platforms_lower = [p.lower() for p in valid_platforms]
if user_platform.lower() not in valid_platforms_lower:
    # Find closest match (fuzzy matching)
    suggestion = find_closest_match(user_platform, valid_platforms)
    # Ask user: "Did you mean 'Amisys'? (I couldn't find 'AMYSS')"

# Check state (case-insensitive)
valid_states_lower = [s.lower() for s in valid_states]
if user_state.lower() not in valid_states_lower:
    # Check if it's a state name vs code
    if user_state.lower() == "california":
        corrected_state = "CA"  # Auto-correct
    else:
        # Typo detected - "californa" is not valid
        # Ask user for clarification
```

**Important:** Even though the API is case-insensitive, you should still validate for typos. The case doesn't matter, but the spelling does!

**Step 3: Query Forecast Data**

Once filters are validated, query the main endpoint:

```python
# Build validated query
query_params = {
    "month": "March",
    "year": 2025,
    "platform[]": ["Amisys"],    # Validated
    "state[]": ["CA"]             # Corrected
}

response = GET("/api/llm/forecast", params=query_params)

if response["success"]:
    # Process data
    records = response["records"]
    insights = response["business_insights"]
else:
    # Handle error
    error_message = response["message"]
```

### Key Fields to Focus On

When parsing the forecast data response:

1. **metadata.field_descriptions**: Understand what each field represents
2. **metadata.formulas**: Learn how values are calculated
3. **business_insights.staffing_status**: Quick staffing assessment
4. **business_insights.risk_indicators**: Identify problem months
5. **totals**: High-level aggregated metrics
6. **configuration**: Month-specific workforce parameters

### Understanding Gap Calculations

**Positive Gap** (capacity > forecast):
- Status: Overstaffed
- Meaning: More resources than needed
- Action: Consider reallocating excess capacity

**Negative Gap** (capacity < forecast):
- Status: Understaffed
- Meaning: Insufficient resources
- Action: Need to add capacity or reduce forecast

**Near-Zero Gap** (balanced):
- Status: Balanced
- Meaning: Capacity matches demand
- Action: Monitor for changes

### Interpreting Trends

The `trend_analysis` section helps predict future issues:

- **Forecast increasing, Capacity stable**: Plan to add capacity
- **Forecast stable, Capacity decreasing**: Investigate capacity loss
- **Both increasing**: Monitor gap percentage to ensure balance

### Using Configuration Context

The `configuration` section provides context for calculations. Configurations are organized by month (e.g., `"Apr-25"`, `"May-25"`), with each month having separate Domestic and Global parameters.

**Configuration parameters per month:**

- **working_days**: How many days per month are worked (varies by month - e.g., February has fewer)
- **shrinkage**: Percentage of time lost to breaks, training, etc. (may vary by month)
- **occupancy**: Percentage of time spent on productive work (may vary by month)
- **work_hours**: Hours worked per day

**Example:**
```json
"configuration": {
  "Apr-25": {
    "Domestic": { "working_days": 21, "work_hours": 9, ... },
    "Global": { "working_days": 21, "work_hours": 9, ... }
  },
  "May-25": {
    "Domestic": { "working_days": 22, "work_hours": 9, ... },
    "Global": { "working_days": 22, "work_hours": 9, ... }
  }
}
```

Use these to understand why FTE requirements and capacity change across months.

---

## Additional Notes

### Month Offset

When a forecast file is uploaded for "March 2025", the Month1-Month6 columns represent:
- Month1 = April 2025 (report month + 1)
- Month2 = May 2025
- Month3 = June 2025
- Month4 = July 2025
- Month5 = August 2025
- Month6 = September 2025

This is why `month=March&year=2025` returns data starting with April 2025.

### Month-Specific Configurations

Each forecast month (Month1-Month6) has its own configuration parameters for both Domestic and Global workforces. The `configuration` section in the response is structured by month label:

```json
"configuration": {
  "Apr-25": { "Domestic": {...}, "Global": {...} },
  "May-25": { "Domestic": {...}, "Global": {...} },
  ...
}
```

**Why this matters:**
- **Working days vary**: February has fewer working days than March
- **Seasonal adjustments**: Shrinkage and occupancy may change based on training cycles, holidays, etc.
- **Year wraparound**: If the report is for August 2025, Month5 and Month6 will be January and February 2026, with configurations for those months in 2026

**Configuration lookup:**
The API automatically handles year wraparound. For example, if you query `month=October&year=2025`:
- Month1 = November 2025 (config from November 2025)
- Month2 = December 2025 (config from December 2025)
- Month3 = January 2026 (config from January 2026) ← Year wraparound handled automatically
- Month4 = February 2026 (config from February 2026)
- Month5 = March 2026 (config from March 2026)
- Month6 = April 2026 (config from April 2026)

### State Handling

- State codes are 2-letter US state abbreviations (e.g., "CA", "TX")
- "N/A" is used for non-state-specific work (e.g., national programs)
- Matching is case-insensitive

### Platform/Market/Locality Parsing

The system automatically parses `main_lob` into components:
- **Format**: `<platform> <market> [<locality>]`
- **Example**: "Amisys Medicaid Domestic"
  - Platform: "Amisys"
  - Market: "Medicaid"
  - Locality: "Domestic"

---

## Quick Reference

### Available Reports Endpoint

**URL:** `GET /api/llm/forecast/available-reports`

**Returns:** List of available forecast reports with metadata
- `reports[]` - Array of available reports
  - `value` - Formatted as "YYYY-MMM" (e.g., "2025-Mar")
  - `display` - Human-readable "Month YYYY"
  - `month` - Full month name for querying
  - `year` - 4-digit year
  - `is_valid` - True if current, False if outdated
  - `data_freshness` - "current" or "outdated"
- `total_reports` - Total count
- `valid_reports` - Count of current reports
- `outdated_reports` - Count of invalidated reports

**Cache:** 5 minutes

**Use this first!** Always call this endpoint to discover what data is available before querying specific reports.

### Filter Options Endpoint

**URL:** `GET /api/llm/forecast/filter-options?month={month}&year={year}`

**Returns:** Available filter values for validation
- `platforms` - Technology platforms (e.g., Amisys, Facets, Xcelys)
- `markets` - Insurance markets (e.g., Medicaid, Medicare)
- `localities` - Workforce types (Domestic, Global)
- `main_lobs` - Full LOB strings
- `states` - US state codes + N/A
- `case_types` - Work types/processes
- `forecast_months` - Available month labels (e.g., Apr-25, May-25)

**Cache:** 5 minutes

### Forecast Data Endpoint

**URL:** `GET /api/llm/forecast?month={month}&year={year}&[filters...]`

**Returns:** Comprehensive forecast data with insights
- `metadata` - Field descriptions, units, formulas
- `configuration` - Month-specific workforce parameters
- `records` - Forecast records with parsed fields
- `totals` - Aggregated metrics per month
- `business_insights` - Staffing status, trends, risks

**Cache:** 60 seconds

**🔑 Important:** All filter matching is **case-insensitive**. `platform[]=amisys`, `platform[]=AMISYS`, and `platform[]=Amisys` all work identically!

---

## Changelog

### Version 1.1 (2026-01-27)

- **New Feature**: Added `/api/llm/forecast/available-reports` endpoint for report discovery
- LLMs can now discover available forecast reports before querying data
- Returns metadata including validity status, allocation status, and data freshness indicators
- Updated workflow to include discovery step (5-step process)
- Enhanced Quick Reference section with available-reports documentation

### Version 1.0 (2026-01-23)

- Initial release
- Two endpoints: filter-options (validation) and forecast (data)
- Comprehensive filtering with intelligent precedence
- Month-specific configurations with year wraparound
- Rich metadata, business insights, and trend analysis
- Input validation support for LLMs
- Detailed error messages with suggestions
- Caching support (5 min for filters, 60s for data)
- Full documentation with integration guide

---

## Support

For questions or issues, please refer to:
- Repository: https://github.com/anthropics/claude-code/issues
- Internal documentation: `CLAUDE.md` in repository root
