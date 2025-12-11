# Manager View API — Specifications (Filters & Data)

**Base URL**: `/api/manager-view`
**Auth**: none (add later if required)
**Content-Type**: `application/json; charset=utf-8`
**KPI**: **Derived client-side / by your Django service from the Data endpoint** (no separate KPI API).
**Last Updated**: 2025-11-28

---

## 1) GET `/api/manager-view/filters`

### Purpose
Provide dropdown options for **Report Month** and **Category** /
(top-level).

### Request
- **Query params**: none

### Response — 200 OK
```json
{
  "success": true,
  "report_months": [
    { "value": "2025-02", "display": "February 2025" },
    { "value": "2025-03", "display": "March 2025" },
    { "value": "2025-04", "display": "April 2025" }
  ],
  "categories": [
    { "value": "", "display": "-- All Categories --" },
    { "value": "amisys-onshore", "display": "Amisys Onshore" },
    { "value": "facets", "display": "Facets" }
  ],
  "timestamp": "2025-10-19T11:20:12.345678Z"
}
````

### Errors

* **500** Internal error

```json
{
  "success": false,
  "error": "Internal server error",
  "status_code": 500,
  "timestamp": "2025-10-19T11:20:12.345678Z"
}
```

---

## 2) GET `/api/manager-view/data`

### Purpose

Return the **hierarchical dataset** for a selected month/category.

> **KPI values are computed from this payload** (no KPI endpoint).

### Query Parameters

| Name           | Type      | Required | Notes                                |
| -------------- | --------- | -------- | ------------------------------------ |
| `report_month` | `YYYY-MM` | **Yes**  | Example: `2025-03`                   |
| `category`     | `string`  | No       | Category id; empty/omitted = **All** |

### Response — 200 OK

> **Children replicate the same category structure recursively**, allowing multiple hierarchy levels.

```json
{
  "success": true,
  "report_month": "2025-02",
  "months": ["2025-02","2025-03","2025-04","2025-05","2025-06","2025-07"],
  "categories": [
    {
      "id": "amisys-onshore",
      "name": "Amisys Onshore",
      "level": 1,
      "has_children": true,
      "data": {
        "2025-02": { "cf": 4100, "hc": 41, "cap": 3895, "gap": -205 },
        "2025-03": { "cf": 4200, "hc": 42, "cap": 3990, "gap": -210 }
      },
      "children": [
        {
          "id": "amisys-onshore-commercial",
          "name": "Commercial",
          "level": 2,
          "has_children": true,
          "data": {
            "2025-02": { "cf": 2100, "hc": 21, "cap": 1995, "gap": -105 },
            "2025-03": { "cf": 2200, "hc": 22, "cap": 2090, "gap": -110 }
          },
          "children": [
            {
              "id": "amisys-onshore-commercial-claims",
              "name": "Claims Processing",
              "level": 3,
              "has_children": false,
              "data": {
                "2025-02": { "cf": 1100, "hc": 11, "cap": 1025, "gap": -75 },
                "2025-03": { "cf": 1150, "hc": 11, "cap": 1080, "gap": -70 }
              },
              "children": []
            }
          ]
        }
      ]
    }
  ],
  "category_name": "All Categories",
  "timestamp": "2025-10-19T11:20:12.345678Z"
}
```

### Errors

* **400** Validation (bad month format)

```json
{
  "success": false,
  "error": "Invalid report_month (expected YYYY-MM).",
  "status_code": 400,
  "timestamp": "2025-10-19T11:20:12.345678Z"
}
```

* **404** Unknown category id

```json
{
  "success": false,
  "error": "Unknown category id: facetsx",
  "status_code": 404,
  "timestamp": "2025-10-19T11:20:12.345678Z"
}
```

* **500** Internal error (unexpected)

```json
{
  "success": false,
  "error": "Internal server error",
  "status_code": 500,
  "timestamp": "2025-10-19T11:20:12.345678Z"
}
```

---

## 3) GET `/api/manager-view/debug/categorization`

### Purpose

**QA/DEBUG ENDPOINT** for categorization diagnostics.

Returns detailed diagnostics showing why a record matched or didn't match each category. Helps analysts quickly identify why records aren't classifying as expected.

### Query Parameters

| Name           | Type     | Required | Notes                           |
| -------------- | -------- | -------- | ------------------------------- |
| `report_month` | `YYYY-MM`| **Yes**  | Example: `2025-03`              |
| `main_lob`     | `string` | No       | Main LOB value to test          |
| `state`        | `string` | No       | State value to test             |
| `case_type`    | `string` | No       | Case type value to test         |

### Response — 200 OK

```json
{
  "success": true,
  "report_month": "2025-02",
  "test_record": {
    "main_lob": "Amisys Medicaid Domestic",
    "state": "TX",
    "case_type": "Claims Processing"
  },
  "diagnostics": [
    {
      "category_id": "amisys-onshore",
      "category_name": "Amisys Onshore",
      "category_path": "Amisys Onshore",
      "is_match": true,
      "matched_fields": [
        {
          "field": "main_lob",
          "pattern": ".*amisys.*domestic.*",
          "value": "Amisys Medicaid Domestic",
          "matched": true
        }
      ],
      "unmatched_fields": [],
      "total_rules": 1,
      "matched_rules": 1,
      "unmatched_rules": 0
    },
    {
      "category_id": "facets-onshore",
      "category_name": "Facets Onshore",
      "category_path": "Facets Onshore",
      "is_match": false,
      "matched_fields": [],
      "unmatched_fields": [
        {
          "field": "main_lob",
          "pattern": ".*facets.*",
          "value": "Amisys Medicaid Domestic",
          "matched": false
        }
      ],
      "total_rules": 1,
      "matched_rules": 0,
      "unmatched_rules": 1
    }
  ],
  "summary": {
    "total_categories": 10,
    "matched_categories": 2,
    "unmatched_categories": 8
  },
  "timestamp": "2025-10-19T11:20:12.345678Z"
}
```

### Use Cases

- Verify why a record is/isn't appearing in a category
- Troubleshoot categorization rules
- QA category configuration changes
- Debug missing or incorrectly categorized records

### Errors

* **400** Validation (bad month format)

```json
{
  "success": false,
  "error": "Invalid report_month (expected YYYY-MM).",
  "status_code": 400,
  "timestamp": "2025-10-19T11:20:12.345678Z"
}
```

* **500** Internal error (unexpected)

```json
{
  "success": false,
  "error": "Internal server error",
  "status_code": 500,
  "timestamp": "2025-10-19T11:20:12.345678Z"
}
```

---

## Data Contracts (Schema)

### Filter Option

```json
{ "value": "string", "display": "string" }
```

### Metrics (per month)

```json
{ "cf": int, "hc": int, "cap": int, "gap": int }
```

### Category Node (recursive)

```json
{
  "id": "string",
  "name": "string",
  "level": 1,
  "has_children": true,
  "data": { "YYYY-MM": { "cf": int, "hc": int, "cap": int, "gap": int }, ... },
  "children": [ /* Category Node */ ]
}
```

### Filters Response

```json
{
  "success": true,
  "report_months": [ /* Filter Option */ ],
  "categories": [ /* Filter Option */ ],
  "timestamp": "ISO-8601"
}
```

### Data Response

```json
{
  "success": true,
  "report_month": "YYYY-MM",
  "months": ["YYYY-MM", "..."],
  "categories": [ /* Category Node */ ],
  "category_name": "string",
  "timestamp": "ISO-8601"
}
```

---

## Validation Rules

* `report_month` must match `^\d{4}-(0[1-9]|1[0-2])$`.
* `category`:

  * empty/omitted = All Categories
  * if provided, must exist in the filters’ categories.
* `level` range: `1..5`.
* `data` keys: must be month values present in the `months` array.
* All metric fields (`cf`, `hc`, `cap`, `gap`) are integers (gap can be negative).

---

## Caching Policy (Server-Side, In-Process — no external services)

> **Goal**: multiple calls in short time should be fast without changing the API.

* **Filters**: cache **5 minutes** (configurable).
  Key: `"filters:v1"`.
* **Data**: cache **60 seconds** (configurable), keyed by parameters.
  Key: `"data:v1:{report_month}:{category-or-all}"`.

**Notes**

* Use an **in-memory TTL cache** per process/worker (no Redis).
* Cache eviction: LRU policy recommended; separate limits per endpoint (e.g., 8 entries for filters, 64 for data).
* Add **HTTP caching hints** (optional):

  * Response header: `Cache-Control: public, max-age=60` (data) / `max-age=300` (filters).
  * **No ETag** (intentionally removed, per requirement).
* When cache is cold or expired, recompute and refresh the entry.
* Optionally guard hot keys with a per-key lock to avoid duplicate recomputations under load.

---

## Performance / Behavior Notes

* **Months** are machine keys (`YYYY-MM`); the frontend uses these for lookups.
  (Pretty labels can be derived client-side if needed.)
* **Children** fully replicate the category schema, enabling N-level hierarchies.
* **KPI** is computed by the client/Django service from the same **Data** response; **no KPI API** required.

---

## Summary

The Manager View API provides three main endpoints:

1. **Filters** (`/api/manager-view/filters`) - Get dropdown options for report months and categories
2. **Data** (`/api/manager-view/data`) - Get hierarchical category tree with metrics for selected month/category
3. **Debug Categorization** (`/api/manager-view/debug/categorization`) - QA/Debug endpoint for troubleshooting categorization rules

All responses follow a consistent format with `success`, `timestamp`, and error handling.

### Implementation Details

- **Caching**: In-memory TTL cache per process/worker (no external services)
- **Hierarchical Structure**: Categories can have up to 5 levels of nesting
- **Metrics**: All metrics (cf, hc, cap, gap) are integers, with gap calculated as `cap - cf`
- **Month Format**: Months use YYYY-MM format for both input parameters and data keys
- **Bottom-Up Aggregation**: Parent category metrics are calculated by summing children's metrics