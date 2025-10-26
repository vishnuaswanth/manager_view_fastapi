# Cascading Dropdown Filters API Specification

**Purpose**: Reference specification for forecast filter cascade microservice refactoring
**Version**: 1.0
**Date**: 2025-01-26
**Base URL**: `http://127.0.0.1:8888`

---

## Overview

The cascading filter system provides a hierarchical dropdown selection flow for forecast data filtering:

```
Year → Month → Platform → Market → Locality → Worktype
```

Each selection narrows down the available options for subsequent dropdowns based on actual data availability.

---

## Configuration

**Request Headers**:
```
Content-Type: application/json
Accept: application/json
```

**Timeout**: 30 seconds
**Caching**: All cascade endpoints are cached with TTL defined by `ForecastCacheConfig.CASCADE_TTL`
**Cache Key Pattern**: `cascade:{filter_type}:{sorted_params}`

---

## API Endpoints

### 1. Get Available Years

**Endpoint**: `GET /forecast/filter-years`

**Description**: Returns all years that have forecast data available

**Request Parameters**: None

**Success Response** (200 OK):
```json
{
  "years": [
    {"value": "2025", "display": "2025"},
    {"value": "2024", "display": "2024"},
    {"value": "2023", "display": "2023"}
  ]
}
```

**Error Response** (500 Internal Server Error):
```json
{
  "detail": "Failed to retrieve available years"
}
```

**Cache Key**: `cascade:years:ALL`

**Example**:
```bash
GET /forecast/filter-years
```

**Python Implementation Reference**:
```python
@cache_with_ttl(ttl=ForecastCacheConfig.CASCADE_TTL, key_prefix='cascade:years')
def get_forecast_filter_years(self) -> Dict[str, List[Dict[str, str]]]:
    return {
        'years': [
            {'value': '2025', 'display': '2025'},
            {'value': '2024', 'display': '2024'}
        ]
    }
```

---

### 2. Get Available Months for Year

**Endpoint**: `GET /forecast/months/{year}`

**Description**: Returns available months for the selected year based on data availability

**Path Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `year` | integer | Yes | Selected year (e.g., 2025) |

**Success Response** (200 OK):
```json
[
  {"value": "1", "display": "January"},
  {"value": "2", "display": "February"},
  {"value": "3", "display": "March"},
  {"value": "4", "display": "April"},
  {"value": "5", "display": "May"},
  {"value": "6", "display": "June"},
  {"value": "7", "display": "July"},
  {"value": "8", "display": "August"},
  {"value": "9", "display": "September"},
  {"value": "10", "display": "October"},
  {"value": "11", "display": "November"},
  {"value": "12", "display": "December"}
]
```

**Error Response** (400 Bad Request):
```json
{
  "detail": "Invalid year: {year}"
}
```

**Error Response** (404 Not Found):
```json
{
  "detail": "No data available for year {year}"
}
```

**Cache Key**: `cascade:months:year={year}`

**Example**:
```bash
GET /forecast/months/2025
```

**Python Implementation Reference**:
```python
@cache_with_ttl(ttl=ForecastCacheConfig.CASCADE_TTL, key_prefix='cascade:months')
def get_forecast_months_for_year(self, year: int) -> List[Dict[str, str]]:
    return [
        {'value': '1', 'display': 'January'},
        {'value': '2', 'display': 'February'},
        # ...
    ]
```

**Business Logic**:
- Query database for distinct months where forecast data exists for given year
- Return months in chronological order (1-12)
- Value should be numeric string for form compatibility
- Display should be full month name

---

### 3. Get Available Platforms

**Endpoint**: `GET /forecast/platforms`

**Description**: Returns available platforms (BOC - Basis of Calculation) for selected year and month

**Query Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `year` | integer | Yes | Selected year |
| `month` | integer | Yes | Selected month (1-12) |

**Success Response** (200 OK):
```json
[
  {"value": "Amisys", "display": "Amisys"},
  {"value": "Facets", "display": "Facets"},
  {"value": "QNXT", "display": "QNXT"}
]
```

**Error Response** (400 Bad Request):
```json
{
  "detail": "Invalid parameters: year and month are required"
}
```

**Error Response** (404 Not Found):
```json
{
  "detail": "No platforms found for year={year}, month={month}"
}
```

**Cache Key**: `cascade:platforms:month={month}&year={year}`

**Example**:
```bash
GET /forecast/platforms?year=2025&month=1
```

**Python Implementation Reference**:
```python
@cache_with_ttl(ttl=ForecastCacheConfig.CASCADE_TTL, key_prefix='cascade:platforms')
def get_forecast_platforms(self, year: int, month: int) -> List[Dict[str, str]]:
    return [
        {'value': 'Amisys', 'display': 'Amisys'},
        {'value': 'Facets', 'display': 'Facets'}
    ]
```

**Business Logic**:
- Query database for distinct platforms with forecast data for given year/month
- Return in alphabetical order
- Platform values should match database enum/string values exactly

---

### 4. Get Available Markets

**Endpoint**: `GET /forecast/markets`

**Description**: Returns available markets (insurance types) filtered by platform, year, and month

**Query Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `year` | integer | Yes | Selected year |
| `month` | integer | Yes | Selected month (1-12) |
| `platform` | string | Yes | Selected platform (e.g., "Amisys") |

**Success Response** (200 OK):
```json
[
  {"value": "Medicaid", "display": "Medicaid"},
  {"value": "Medicare", "display": "Medicare"},
  {"value": "Commercial", "display": "Commercial"}
]
```

**Error Response** (400 Bad Request):
```json
{
  "detail": "Missing required parameter: platform"
}
```

**Error Response** (404 Not Found):
```json
{
  "detail": "No markets found for platform={platform}, year={year}, month={month}"
}
```

**Cache Key**: `cascade:markets:month={month}&platform={platform}&year={year}`

**Example**:
```bash
GET /forecast/markets?year=2025&month=1&platform=Amisys
```

**Python Implementation Reference**:
```python
@cache_with_ttl(ttl=ForecastCacheConfig.CASCADE_TTL, key_prefix='cascade:markets')
def get_forecast_markets(
    self, year: int, month: int, platform: str
) -> List[Dict[str, str]]:
    return [
        {'value': 'Medicaid', 'display': 'Medicaid'},
        {'value': 'Medicare', 'display': 'Medicare'}
    ]
```

**Business Logic**:
- Query database for distinct markets filtered by year, month, and platform
- Return in alphabetical order
- Market values should be case-sensitive and match database values

---

### 5. Get Available Localities

**Endpoint**: `GET /forecast/localities`

**Description**: Returns available localities for selected platform and market (optional filter)

**Query Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `year` | integer | Yes | Selected year |
| `month` | integer | Yes | Selected month (1-12) |
| `platform` | string | Yes | Selected platform |
| `market` | string | Yes | Selected market |

**Success Response** (200 OK):
```json
[
  {"value": "", "display": "-- All Localities --"},
  {"value": "DOMESTIC", "display": "Domestic"},
  {"value": "OFFSHORE", "display": "Offshore"}
]
```

**Error Response** (400 Bad Request):
```json
{
  "detail": "Missing required parameters: year, month, platform, market"
}
```

**Error Response** (404 Not Found):
```json
{
  "detail": "No localities found for given filters"
}
```

**Cache Key**: `cascade:localities:market={market}&month={month}&platform={platform}&year={year}`

**Example**:
```bash
GET /forecast/localities?year=2025&month=1&platform=Amisys&market=Medicaid
```

**Python Implementation Reference**:
```python
@cache_with_ttl(ttl=ForecastCacheConfig.CASCADE_TTL, key_prefix='cascade:localities')
def get_forecast_localities(
    self, year: int, month: int, platform: str, market: str
) -> List[Dict[str, str]]:
    return [
        {'value': '', 'display': '-- All Localities --'},
        {'value': 'DOMESTIC', 'display': 'Domestic'},
        {'value': 'OFFSHORE', 'display': 'Offshore'}
    ]
```

**Business Logic**:
- Always include empty value option `{"value": "", "display": "-- All Localities --"}` as first item
- Query database for distinct localities filtered by year, month, platform, market
- Return in alphabetical order (after "All" option)
- Locality is an **optional filter** - empty value is valid for worktype query

---

### 6. Get Available Worktypes

**Endpoint**: `GET /forecast/worktypes`

**Description**: Returns available worktypes (processes) for selected filters. This is the final step in the cascade.

**Query Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `year` | integer | Yes | Selected year |
| `month` | integer | Yes | Selected month (1-12) |
| `platform` | string | Yes | Selected platform |
| `market` | string | Yes | Selected market |
| `locality` | string | No | Selected locality (empty string = all) |

**Success Response** (200 OK):
```json
[
  {"value": "Claims Processing", "display": "Claims Processing"},
  {"value": "Enrollment", "display": "Enrollment"},
  {"value": "Member Services", "display": "Member Services"},
  {"value": "Provider Services", "display": "Provider Services"}
]
```

**Error Response** (400 Bad Request):
```json
{
  "detail": "Missing required parameters: year, month, platform, market"
}
```

**Error Response** (404 Not Found):
```json
{
  "detail": "No worktypes found for given filters"
}
```

**Cache Key**:
- With locality: `cascade:worktypes:locality={locality}&market={market}&month={month}&platform={platform}&year={year}`
- Without locality: `cascade:worktypes:market={market}&month={month}&platform={platform}&year={year}`

**Example (with locality)**:
```bash
GET /forecast/worktypes?year=2025&month=1&platform=Amisys&market=Medicaid&locality=DOMESTIC
```

**Example (without locality - all localities)**:
```bash
GET /forecast/worktypes?year=2025&month=1&platform=Amisys&market=Medicaid
```

**Python Implementation Reference**:
```python
@cache_with_ttl(ttl=ForecastCacheConfig.CASCADE_TTL, key_prefix='cascade:worktypes')
def get_forecast_worktypes(
    self,
    year: int,
    month: int,
    platform: str,
    market: str,
    locality: Optional[str] = None
) -> List[Dict[str, str]]:
    return [
        {'value': 'Claims Processing', 'display': 'Claims Processing'},
        {'value': 'Enrollment', 'display': 'Enrollment'}
    ]
```

**Business Logic**:
- Query database for distinct worktypes filtered by all provided parameters
- If locality is None or empty string, return worktypes for all localities
- Return in alphabetical order
- Worktype values should match database values exactly (may contain spaces)

---

## Cascade Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Get Years                                           │
│ GET /forecast/filter-years                                  │
│ Returns: [{value: "2025", display: "2025"}, ...]            │
└────────────────────────┬────────────────────────────────────┘
                         │ User selects: year = 2025
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 2: Get Months                                          │
│ GET /forecast/months/2025                                   │
│ Returns: [{value: "1", display: "January"}, ...]            │
└────────────────────────┬────────────────────────────────────┘
                         │ User selects: month = 1
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Get Platforms                                       │
│ GET /forecast/platforms?year=2025&month=1                   │
│ Returns: [{value: "Amisys", display: "Amisys"}, ...]        │
└────────────────────────┬────────────────────────────────────┘
                         │ User selects: platform = "Amisys"
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 4: Get Markets                                         │
│ GET /forecast/markets?year=2025&month=1&platform=Amisys     │
│ Returns: [{value: "Medicaid", display: "Medicaid"}, ...]    │
└────────────────────────┬────────────────────────────────────┘
                         │ User selects: market = "Medicaid"
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 5: Get Localities (Optional)                           │
│ GET /forecast/localities?year=2025&month=1&                 │
│     platform=Amisys&market=Medicaid                         │
│ Returns: [{value: "", display: "-- All --"},                │
│           {value: "DOMESTIC", display: "Domestic"}, ...]    │
└────────────────────────┬────────────────────────────────────┘
                         │ User selects: locality = "DOMESTIC"
                         │ (or empty for all)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 6: Get Worktypes (Final)                               │
│ GET /forecast/worktypes?year=2025&month=1&                  │
│     platform=Amisys&market=Medicaid&locality=DOMESTIC       │
│ Returns: [{value: "Claims Processing", ...}, ...]           │
└─────────────────────────────────────────────────────────────┘
```

---

## Response Format Standard

All endpoints follow consistent response structure:

**Success Response Structure**:
```typescript
// Array response (months, platforms, markets, localities, worktypes)
Array<{
  value: string;      // Value to be submitted in forms
  display: string;    // Human-readable label for UI
}>

// Object response (years only)
{
  years: Array<{
    value: string;
    display: string;
  }>
}
```

**Error Response Structure**:
```typescript
{
  detail: string;     // Error message describing the issue
}
```

---

## Parameter Validation Rules

| Parameter | Type | Validation | Example Valid Values |
|-----------|------|------------|---------------------|
| `year` | integer | Must be 4-digit year, >= 2020 | 2025, 2024, 2023 |
| `month` | integer | Must be 1-12 | 1, 6, 12 |
| `platform` | string | Non-empty, max 50 chars | "Amisys", "Facets" |
| `market` | string | Non-empty, max 50 chars | "Medicaid", "Medicare" |
| `locality` | string | Optional, max 50 chars | "", "DOMESTIC", "OFFSHORE" |

**Invalid Request Examples**:

```bash
# Invalid year
GET /forecast/months/99        # 400: Invalid year format
GET /forecast/months/2050      # 404: Future year with no data

# Invalid month
GET /forecast/platforms?year=2025&month=13    # 400: Month must be 1-12
GET /forecast/platforms?year=2025&month=0     # 400: Month must be 1-12

# Missing required parameters
GET /forecast/markets?year=2025               # 400: Missing month and platform
GET /forecast/worktypes?year=2025&month=1     # 400: Missing platform and market
```

---

## Caching Strategy

### Cache Implementation

**Decorator Pattern**:
```python
from cache_utils import cache_with_ttl
from config import ForecastCacheConfig

@cache_with_ttl(ttl=ForecastCacheConfig.CASCADE_TTL, key_prefix='cascade:worktypes')
def get_forecast_worktypes(year, month, platform, market, locality=None):
    # Implementation
    pass
```

### Cache Key Generation

Cache keys are generated using sorted query parameters to ensure consistency:

```python
def getCacheKey(endpoint, params):
    sorted_params = '&'.join(
        f"{k}={v}" for k, v in sorted(params.items())
    )
    return f"{endpoint}?{sorted_params}"
```

**Examples**:
```
cascade:months:year=2025
cascade:platforms:month=1&year=2025
cascade:markets:month=1&platform=Amisys&year=2025
cascade:localities:market=Medicaid&month=1&platform=Amisys&year=2025
cascade:worktypes:locality=DOMESTIC&market=Medicaid&month=1&platform=Amisys&year=2025
```

### Cache Invalidation

Cache should be invalidated when:
1. New forecast data is uploaded for a year/month combination
2. Forecast data is deleted or modified
3. TTL expires (automatic)

**Manual Invalidation Pattern**:
```python
# Clear all cascade caches for specific year/month
def invalidate_cascade_cache(year: int, month: int):
    cache_prefixes = [
        f'cascade:months:year={year}',
        f'cascade:platforms:month={month}&year={year}',
        f'cascade:markets:month={month}&year={year}',
        f'cascade:localities:month={month}&year={year}',
        f'cascade:worktypes:month={month}&year={year}'
    ]
    for prefix in cache_prefixes:
        cache.delete_pattern(prefix)
```

---

## Database Query Patterns

### Recommended SQL Patterns

**Get Platforms**:
```sql
SELECT DISTINCT platform
FROM forecast_data
WHERE year = :year AND month = :month
  AND platform IS NOT NULL
ORDER BY platform;
```

**Get Markets**:
```sql
SELECT DISTINCT market
FROM forecast_data
WHERE year = :year AND month = :month AND platform = :platform
  AND market IS NOT NULL
ORDER BY market;
```

**Get Localities** (with All option):
```sql
SELECT DISTINCT locality
FROM forecast_data
WHERE year = :year AND month = :month
  AND platform = :platform AND market = :market
  AND locality IS NOT NULL
ORDER BY locality;
```

**Get Worktypes** (with optional locality):
```sql
SELECT DISTINCT worktype
FROM forecast_data
WHERE year = :year AND month = :month
  AND platform = :platform AND market = :market
  AND (:locality IS NULL OR locality = :locality)
  AND worktype IS NOT NULL
ORDER BY worktype;
```

---

## Integration with Frontend

### JavaScript/TypeScript Example

```typescript
// Frontend implementation example
class ForecastFilterAPI {
  private baseUrl = 'http://127.0.0.1:8888';

  async getYears(): Promise<{years: Array<{value: string, display: string}>}> {
    const response = await fetch(`${this.baseUrl}/forecast/filter-years`);
    return response.json();
  }

  async getMonths(year: number): Promise<Array<{value: string, display: string}>> {
    const response = await fetch(`${this.baseUrl}/forecast/months/${year}`);
    return response.json();
  }

  async getPlatforms(year: number, month: number): Promise<Array<{value: string, display: string}>> {
    const response = await fetch(
      `${this.baseUrl}/forecast/platforms?year=${year}&month=${month}`
    );
    return response.json();
  }

  async getMarkets(
    year: number,
    month: number,
    platform: string
  ): Promise<Array<{value: string, display: string}>> {
    const params = new URLSearchParams({
      year: year.toString(),
      month: month.toString(),
      platform: platform
    });
    const response = await fetch(`${this.baseUrl}/forecast/markets?${params}`);
    return response.json();
  }

  async getLocalities(
    year: number,
    month: number,
    platform: string,
    market: string
  ): Promise<Array<{value: string, display: string}>> {
    const params = new URLSearchParams({
      year: year.toString(),
      month: month.toString(),
      platform: platform,
      market: market
    });
    const response = await fetch(`${this.baseUrl}/forecast/localities?${params}`);
    return response.json();
  }

  async getWorktypes(
    year: number,
    month: number,
    platform: string,
    market: string,
    locality?: string
  ): Promise<Array<{value: string, display: string}>> {
    const params = new URLSearchParams({
      year: year.toString(),
      month: month.toString(),
      platform: platform,
      market: market
    });
    if (locality && locality !== '') {
      params.append('locality', locality);
    }
    const response = await fetch(`${this.baseUrl}/forecast/worktypes?${params}`);
    return response.json();
  }
}
```

---

## Testing Scenarios

### Happy Path Test Cases

```bash
# Test Case 1: Full cascade flow
GET /forecast/filter-years
→ 200 OK: {years: [{value: "2025", display: "2025"}]}

GET /forecast/months/2025
→ 200 OK: [{value: "1", display: "January"}, ...]

GET /forecast/platforms?year=2025&month=1
→ 200 OK: [{value: "Amisys", display: "Amisys"}, ...]

GET /forecast/markets?year=2025&month=1&platform=Amisys
→ 200 OK: [{value: "Medicaid", display: "Medicaid"}, ...]

GET /forecast/localities?year=2025&month=1&platform=Amisys&market=Medicaid
→ 200 OK: [{value: "", display: "-- All Localities --"}, ...]

GET /forecast/worktypes?year=2025&month=1&platform=Amisys&market=Medicaid&locality=DOMESTIC
→ 200 OK: [{value: "Claims Processing", display: "Claims Processing"}, ...]
```

### Error Test Cases

```bash
# Test Case 2: Invalid year
GET /forecast/months/abc
→ 400 Bad Request: {detail: "Invalid year format"}

# Test Case 3: Missing required parameters
GET /forecast/markets?year=2025
→ 400 Bad Request: {detail: "Missing required parameters: month, platform"}

# Test Case 4: No data found
GET /forecast/platforms?year=2025&month=99
→ 404 Not Found: {detail: "No platforms found for year=2025, month=99"}

# Test Case 5: Empty result set
GET /forecast/worktypes?year=2025&month=1&platform=InvalidPlatform&market=Medicaid
→ 404 Not Found: {detail: "No worktypes found for given filters"}
```

### Performance Test Cases

```bash
# Test Case 6: Verify caching
GET /forecast/platforms?year=2025&month=1
→ 200 OK (from database, ~200ms)

GET /forecast/platforms?year=2025&month=1
→ 200 OK (from cache, ~5ms)

# Test Case 7: Cache key uniqueness
GET /forecast/platforms?year=2025&month=1
GET /forecast/platforms?month=1&year=2025
→ Both should hit same cache (sorted params)
```

---

## Migration Checklist

When refactoring to this specification:

- [ ] Implement all 6 endpoints with exact URLs and parameters
- [ ] Ensure response format matches specification (value/display structure)
- [ ] Add parameter validation for all required fields
- [ ] Implement caching with configurable TTL
- [ ] Use sorted parameter keys for cache consistency
- [ ] Add proper error handling (400 for validation, 404 for no data)
- [ ] Include "All Localities" option in localities endpoint
- [ ] Support optional locality parameter in worktypes endpoint
- [ ] Test cascade flow with real data
- [ ] Implement cache invalidation on data updates
- [ ] Add logging for debugging cache hits/misses
- [ ] Document any database schema assumptions
- [ ] Add API tests covering happy path and error cases
- [ ] Monitor performance and cache hit rates
- [ ] Update frontend to use new endpoint structure

---

## Common Pitfalls to Avoid

1. **Cache Key Inconsistency**: Always sort parameters before generating cache keys
2. **Missing "All" Option**: Localities must include empty value option first
3. **Type Coercion**: Month should be numeric in API but string in response values
4. **Optional Parameters**: Locality is optional in worktypes - don't require it
5. **Empty vs Null**: Empty string `""` for locality means "all", not invalid
6. **Case Sensitivity**: Platform/Market/Locality values are case-sensitive
7. **Error Messages**: Use 404 for "no data", 400 for "invalid params"
8. **Response Arrays**: Most endpoints return arrays directly, only years returns object
9. **Cache Invalidation**: Remember to clear caches when data changes
10. **Frontend Compatibility**: Ensure value/display format works with HTML forms

---

**End of Cascading Filters API Specification**