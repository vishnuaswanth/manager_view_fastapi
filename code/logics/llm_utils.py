"""
LLM Utility Functions
Provides helper functions for the LLM forecast data endpoint.
"""

import logging
from typing import Dict, List, Optional

from code.logics.manager_view import parse_main_lob

logger = logging.getLogger(__name__)

# Known localities for normalization
LOCALITY_NORMALIZATION = {
    "offshore": "Global",
    "onshore": "Domestic",
    "domestic": "Domestic",
    "global": "Global"
}


def determine_locality(main_lob: str, case_type: str) -> str:
    """
    Determine locality using combined Main_LOB and Case_Type logic.

    Logic:
    1. Parse Main_LOB for locality (last word if matches known localities)
    2. Special case: If Main_LOB contains "oic" AND "volumes", use Case_Type:
       - Case_Type contains "domestic" → "Domestic"
       - Otherwise → "Global"
    3. Normalize: "Offshore"/"OFFSHORE" → "Global", "Onshore"/"DOMESTIC" → "Domestic"

    Args:
        main_lob: Main LOB string (e.g., "Amisys Medicaid Domestic")
        case_type: Case type string (e.g., "Claims Processing Domestic")

    Returns:
        "Domestic" or "Global"

    Examples:
        >>> determine_locality("Amisys Medicaid Domestic", "Claims Processing")
        "Domestic"
        >>> determine_locality("Facets OIC Volumes", "Claims Processing Domestic")
        "Domestic"
        >>> determine_locality("Facets OIC Volumes", "Claims Processing")
        "Global"
    """
    # Guard: Handle None or empty inputs
    if not main_lob:
        logger.warning(f"[determine_locality] Empty main_lob, defaulting to Global")
        return "Global"

    main_lob_lower = main_lob.lower()

    # Special case: OIC Volumes - use Case_Type to determine locality
    if "oic" in main_lob_lower and "volumes" in main_lob_lower:
        if case_type and "domestic" in case_type.lower():
            logger.debug(f"[determine_locality] OIC Volumes with domestic case_type: {case_type}")
            return "Domestic"
        else:
            logger.debug(f"[determine_locality] OIC Volumes without domestic case_type: {case_type}")
            return "Global"

    # Parse Main_LOB for locality
    parsed = parse_main_lob(main_lob)
    locality = parsed.get("locality")

    # If locality found, normalize it
    if locality:
        locality_lower = locality.lower().strip("()")
        normalized = LOCALITY_NORMALIZATION.get(locality_lower)
        if normalized:
            logger.debug(f"[determine_locality] Normalized '{locality}' to '{normalized}'")
            return normalized

    # Default to Global if no locality found
    logger.debug(f"[determine_locality] No locality found for '{main_lob}', defaulting to Global")
    return "Global"


def apply_forecast_filters(records: List[Dict], filters: Dict) -> List[Dict]:
    """
    Apply all filter criteria to forecast records.

    Filters:
    - platform: Check parsed platform from Main_LOB
    - market: Check parsed market from Main_LOB
    - locality: Check determined locality (Main_LOB + Case_Type)
    - main_lob: Direct Main_LOB match (overrides platform/market/locality)
    - state: Match Centene_Capacity_Plan_State
    - case_type: Match Centene_Capacity_Plan_Case_Type
    - forecast_months: Only include specified months in output (applied later)

    Args:
        records: List of forecast record dictionaries
        filters: Dictionary of filter criteria
            {
                "platform": ["Amisys", "Facets"],
                "market": ["Medicaid"],
                "locality": ["Domestic"],
                "main_lob": ["Amisys Medicaid Domestic"],
                "state": ["CA", "TX"],
                "case_type": ["Claims Processing"],
                "forecast_months": ["Apr-25", "May-25"]  # Applied to output, not filtering
            }

    Returns:
        Filtered list of records

    Examples:
        >>> records = [{"Centene_Capacity_Plan_Main_LOB": "Amisys Medicaid Domestic", ...}]
        >>> filters = {"platform": ["Amisys"]}
        >>> apply_forecast_filters(records, filters)
        [...]  # Filtered records
    """
    if not records:
        return []

    # Extract filter values
    platform_filter = filters.get("platform", [])
    market_filter = filters.get("market", [])
    locality_filter = filters.get("locality", [])
    main_lob_filter = filters.get("main_lob", [])
    state_filter = filters.get("state", [])
    case_type_filter = filters.get("case_type", [])

    # Convert filters to lowercase for case-insensitive matching
    platform_filter_lower = [p.lower() for p in platform_filter] if platform_filter else []
    market_filter_lower = [m.lower() for m in market_filter] if market_filter else []
    locality_filter_lower = [l.lower() for l in locality_filter] if locality_filter else []
    main_lob_filter_lower = [lob.lower() for lob in main_lob_filter] if main_lob_filter else []
    state_filter_lower = [s.lower() for s in state_filter] if state_filter else []
    case_type_filter_lower = [ct.lower() for ct in case_type_filter] if case_type_filter else []

    filtered_records = []

    for record in records:
        # Extract fields from record
        main_lob = record.get("Centene_Capacity_Plan_Main_LOB", "")
        state = record.get("Centene_Capacity_Plan_State", "")
        case_type = record.get("Centene_Capacity_Plan_Case_Type", "")

        # Apply main_lob filter (overrides platform/market/locality)
        if main_lob_filter_lower:
            if main_lob.lower() not in main_lob_filter_lower:
                continue
        else:
            # Apply platform/market/locality filters only if main_lob filter not provided
            if platform_filter_lower or market_filter_lower or locality_filter_lower:
                parsed = parse_main_lob(main_lob)
                platform = parsed.get("platform", "")
                market = parsed.get("market", "")
                locality = determine_locality(main_lob, case_type)

                # Check platform filter
                if platform_filter_lower and platform.lower() not in platform_filter_lower:
                    continue

                # Check market filter
                if market_filter_lower and market.lower() not in market_filter_lower:
                    continue

                # Check locality filter
                if locality_filter_lower and locality.lower() not in locality_filter_lower:
                    continue

        # Apply state filter
        if state_filter_lower and state.lower() not in state_filter_lower:
            continue

        # Apply case_type filter
        if case_type_filter_lower and case_type.lower() not in case_type_filter_lower:
            continue

        # Record passed all filters
        filtered_records.append(record)

    logger.info(f"[apply_forecast_filters] Filtered {len(records)} records to {len(filtered_records)}")
    return filtered_records


def calculate_totals(records: List[Dict], month_labels: List[str]) -> Dict:
    """
    Calculate aggregated totals across all records for each month.

    Args:
        records: List of transformed forecast records (after filtering)
        month_labels: List of month labels (e.g., ["Apr-25", "May-25", ...])

    Returns:
        Dictionary of totals by month:
        {
            "Apr-25": {
                "forecast_total": 1000.0,
                "fte_available_total": 50,
                "fte_required_total": 45,
                "capacity_total": 9500.0,
                "gap_total": 8500.0  # capacity - forecast
            },
            ...
        }

    Examples:
        >>> records = [{"months": {"Apr-25": {"forecast": 100, "fte_available": 5, ...}}}]
        >>> month_labels = ["Apr-25"]
        >>> calculate_totals(records, month_labels)
        {"Apr-25": {"forecast_total": 100, ...}}
    """
    totals = {}

    for month_label in month_labels:
        forecast_sum = 0.0
        fte_available_sum = 0
        fte_required_sum = 0
        capacity_sum = 0.0

        for record in records:
            month_data = record.get("months", {}).get(month_label, {})
            forecast_sum += month_data.get("forecast", 0.0)
            fte_available_sum += month_data.get("fte_available", 0)
            fte_required_sum += month_data.get("fte_required", 0)
            capacity_sum += month_data.get("capacity", 0.0)

        gap_sum = capacity_sum - forecast_sum

        totals[month_label] = {
            "forecast_total": round(forecast_sum, 2),
            "fte_available_total": fte_available_sum,
            "fte_required_total": fte_required_sum,
            "capacity_total": round(capacity_sum, 2),
            "gap_total": round(gap_sum, 2)
        }

    logger.debug(f"[calculate_totals] Calculated totals for {len(month_labels)} months")
    return totals


def generate_business_insights(totals: Dict, month_labels: List[str]) -> Dict:
    """
    Generate business insights for LLM understanding.

    Args:
        totals: Dictionary of totals by month (from calculate_totals)
        month_labels: List of month labels in order (e.g., ["Apr-25", "May-25", ...])

    Returns:
        Dictionary with staffing status, trend analysis, and risk indicators:
        {
            "staffing_status": {
                "Apr-25": {
                    "status": "understaffed",  # understaffed | overstaffed | balanced
                    "gap_percentage": -15.5,  # (capacity - forecast) / forecast * 100
                    "description": "Capacity is 15.5% below forecast demand"
                },
                ...
            },
            "trend_analysis": {
                "forecast_trend": "increasing",  # increasing | decreasing | stable
                "capacity_trend": "stable",
                "description": "Forecast demand increasing while capacity remains stable"
            },
            "risk_indicators": [
                {
                    "month": "Apr-25",
                    "severity": "high",  # high | medium | low
                    "message": "Significant capacity shortage (15.5% below demand)"
                }
            ]
        }

    Examples:
        >>> totals = {"Apr-25": {"forecast_total": 1000, "capacity_total": 850, "gap_total": -150}}
        >>> month_labels = ["Apr-25"]
        >>> generate_business_insights(totals, month_labels)
        {...}  # Business insights
    """
    staffing_status = {}
    risk_indicators = []

    # Calculate staffing status for each month
    for month_label in month_labels:
        month_totals = totals.get(month_label, {})
        forecast_total = month_totals.get("forecast_total", 0.0)
        capacity_total = month_totals.get("capacity_total", 0.0)
        gap_total = month_totals.get("gap_total", 0.0)

        # Calculate gap percentage
        if forecast_total > 0:
            gap_percentage = (gap_total / forecast_total) * 100
        else:
            gap_percentage = 0.0

        # Determine status
        if gap_percentage > 5:
            status = "overstaffed"
            description = f"Capacity is {gap_percentage:.1f}% above forecast demand"
        elif gap_percentage < -5:
            status = "understaffed"
            description = f"Capacity is {abs(gap_percentage):.1f}% below forecast demand"
        else:
            status = "balanced"
            description = f"Capacity is balanced with forecast demand (gap: {gap_percentage:.1f}%)"

        staffing_status[month_label] = {
            "status": status,
            "gap_percentage": round(gap_percentage, 2),
            "description": description
        }

        # Add risk indicators
        if abs(gap_percentage) > 10:
            severity = "high"
            if gap_percentage < 0:
                message = f"Significant capacity shortage ({abs(gap_percentage):.1f}% below demand)"
            else:
                message = f"Significant capacity surplus ({gap_percentage:.1f}% above demand)"

            risk_indicators.append({
                "month": month_label,
                "severity": severity,
                "message": message
            })
        elif abs(gap_percentage) > 5:
            severity = "medium"
            if gap_percentage < 0:
                message = f"Moderate capacity shortage ({abs(gap_percentage):.1f}% below demand)"
            else:
                message = f"Moderate capacity surplus ({gap_percentage:.1f}% above demand)"

            risk_indicators.append({
                "month": month_label,
                "severity": severity,
                "message": message
            })

    # Trend analysis
    trend_analysis = _analyze_trends(totals, month_labels)

    insights = {
        "staffing_status": staffing_status,
        "trend_analysis": trend_analysis,
        "risk_indicators": risk_indicators
    }

    logger.debug(f"[generate_business_insights] Generated insights for {len(month_labels)} months")
    return insights


def _analyze_trends(totals: Dict, month_labels: List[str]) -> Dict:
    """
    Analyze month-over-month trends in forecast and capacity.

    Args:
        totals: Dictionary of totals by month
        month_labels: List of month labels in chronological order

    Returns:
        Trend analysis dictionary with forecast_trend, capacity_trend, and description
    """
    if len(month_labels) < 2:
        return {
            "forecast_trend": "insufficient_data",
            "capacity_trend": "insufficient_data",
            "description": "Insufficient data for trend analysis (need at least 2 months)"
        }

    # Calculate average change percentages
    forecast_changes = []
    capacity_changes = []

    for i in range(1, len(month_labels)):
        prev_month = month_labels[i - 1]
        curr_month = month_labels[i]

        prev_totals = totals.get(prev_month, {})
        curr_totals = totals.get(curr_month, {})

        prev_forecast = prev_totals.get("forecast_total", 0.0)
        curr_forecast = curr_totals.get("forecast_total", 0.0)
        prev_capacity = prev_totals.get("capacity_total", 0.0)
        curr_capacity = curr_totals.get("capacity_total", 0.0)

        # Calculate percentage changes
        if prev_forecast > 0:
            forecast_change = ((curr_forecast - prev_forecast) / prev_forecast) * 100
            forecast_changes.append(forecast_change)

        if prev_capacity > 0:
            capacity_change = ((curr_capacity - prev_capacity) / prev_capacity) * 100
            capacity_changes.append(capacity_change)

    # Determine trends
    avg_forecast_change = sum(forecast_changes) / len(forecast_changes) if forecast_changes else 0
    avg_capacity_change = sum(capacity_changes) / len(capacity_changes) if capacity_changes else 0

    # Classify trends (> 5% = increasing/decreasing, otherwise stable)
    if avg_forecast_change > 5:
        forecast_trend = "increasing"
    elif avg_forecast_change < -5:
        forecast_trend = "decreasing"
    else:
        forecast_trend = "stable"

    if avg_capacity_change > 5:
        capacity_trend = "increasing"
    elif avg_capacity_change < -5:
        capacity_trend = "decreasing"
    else:
        capacity_trend = "stable"

    # Generate description
    if forecast_trend == capacity_trend == "stable":
        description = "Both forecast demand and capacity remain stable"
    elif forecast_trend == "increasing" and capacity_trend == "stable":
        description = "Forecast demand increasing while capacity remains stable - potential future shortage"
    elif forecast_trend == "increasing" and capacity_trend == "increasing":
        description = "Both forecast demand and capacity are increasing"
    elif forecast_trend == "decreasing" and capacity_trend == "stable":
        description = "Forecast demand decreasing while capacity remains stable - potential future surplus"
    elif forecast_trend == "stable" and capacity_trend == "increasing":
        description = "Capacity increasing while forecast demand remains stable - building capacity"
    elif forecast_trend == "stable" and capacity_trend == "decreasing":
        description = "Capacity decreasing while forecast demand remains stable - potential future shortage"
    else:
        description = f"Forecast trend: {forecast_trend}, Capacity trend: {capacity_trend}"

    return {
        "forecast_trend": forecast_trend,
        "capacity_trend": capacity_trend,
        "average_forecast_change_percentage": round(avg_forecast_change, 2),
        "average_capacity_change_percentage": round(avg_capacity_change, 2),
        "description": description
    }
