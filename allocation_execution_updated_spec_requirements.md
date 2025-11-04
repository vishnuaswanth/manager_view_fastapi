## GET /api/allocation/executions/kpi

Description

Retrieve aggregated KPI metrics for allocation executions based on filters. Returns statistics including total executions, success rates, average duration, and
status breakdowns.

Query Parameters

| Parameter   | Type     | Required | Default | Description                            |
|-------------|----------|----------|---------|----------------------------------------|
| month       | string   | No       | -       | Filter by month name (e.g., "January") |
| year        | integer  | No       | -       | Filter by year (e.g., 2025)            |
| status      | string[] | No       | -       | Filter by status (can pass multiple)   |
| uploaded_by | string   | No       | -       | Filter by username                     |

Response Format

Status Code: 200 OK

{
"success": true,
"data": {
    "total_executions": 150,
    "success_rate": 0.85,
    "average_duration_seconds": 320.5,
    "failed_count": 12,
    "partial_success_count": 8,
    "in_progress_count": 2,
    "pending_count": 3,
    "success_count": 125,
    "total_records_processed": 187500,
    "total_records_failed": 9375
},
"timestamp": "2025-01-15T14:30:00Z"
}

Response Fields

| Field                    | Type    | Description                                               |
|--------------------------|---------|-----------------------------------------------------------|
| total_executions         | integer | Total number of executions matching filters               |
| success_rate             | float   | Success rate (0.0-1.0) = success_count / total_executions |
| average_duration_seconds | float   | Average duration of completed executions                  |
| failed_count             | integer | Number of FAILED executions                               |
| partial_success_count    | integer | Number of PARTIAL_SUCCESS executions                      |
| in_progress_count        | integer | Number of IN_PROGRESS executions                          |
| pending_count            | integer | Number of PENDING executions                              |
| success_count            | integer | Number of SUCCESS executions                              |
| total_records_processed  | integer | Sum of all records_processed                              |
| total_records_failed     | integer | Sum of all records_failed                                 |

Example Requests

# All KPIs (no filters)
GET /api/allocation/executions/kpi

# KPIs for specific month/year
GET /api/allocation/executions/kpi?month=January&year=2025

# KPIs for specific user
GET /api/allocation/executions/kpi?uploaded_by=john.doe

# KPIs for specific statuses
GET /api/allocation/executions/kpi?status=SUCCESS&status=FAILED