"""
Manager View Helper Functions
Handles LOB parsing, hierarchical categorization, and metrics calculation for forecast data.
"""

import json
import os
import logging
from typing import Dict, List, Optional
from calendar import month_name

from code.logics.db import (
    DBManager,
    AllocationValidityModel
)

logger = logging.getLogger(__name__)

# Known platforms and localities (case-insensitive matching)
PLATFORMS = ["amisys", "facets", "xcelys"]
LOCALITIES = ["domestic", "global", "(domestic)", "(global)"]


def parse_main_lob(main_lob: str) -> Dict[str, Optional[str]]:
    """
    Parse main_lob into platform, market, and locality components.

    Format: <platform> <market> [<locality>]
    - Platform: Amisys, Facets, or Xcelys (first word if it matches known platforms)
    - Locality: Domestic or Global (last word if it matches known localities)
    - Market: Everything in between

    Args:
        main_lob: String like "Amisys Medicaid Domestic" or "Facets OIC Volumes"

    Returns:
        Dict with keys: platform, market, locality

    Examples:
        >>> parse_main_lob("Amisys Medicaid Domestic")
        {'platform': 'Amisys', 'market': 'Medicaid', 'locality': 'Domestic'}

        >>> parse_main_lob("Amisys OIC Volumes")
        {'platform': 'Amisys', 'market': 'OIC Volumes', 'locality': None}

        >>> parse_main_lob("Amisys")  # Single token
        {'platform': 'Amisys', 'market': None, 'locality': None}
    """
    # Guard: Handle None, empty, or non-string inputs
    if not main_lob or not isinstance(main_lob, str):
        logger.debug(f"[parse_main_lob] Invalid input type or empty: {type(main_lob)}")
        return {"platform": None, "market": None, "locality": None}

    # Guard: Handle whitespace-only strings
    main_lob_cleaned = main_lob.strip()
    if not main_lob_cleaned:
        logger.debug("[parse_main_lob] Empty string after stripping")
        return {"platform": None, "market": None, "locality": None}

    parts = main_lob_cleaned.split()

    # Guard: Handle single-token strings
    if len(parts) == 1:
        single_token = parts[0]
        # Check if it's a known platform
        if single_token.lower() in PLATFORMS:
            logger.debug(f"[parse_main_lob] Single token is platform: {single_token}")
            return {"platform": single_token, "market": None, "locality": None}
        # Check if it's a known locality
        elif single_token.lower() in LOCALITIES:
            logger.debug(f"[parse_main_lob] Single token is locality: {single_token}")
            return {"platform": None, "market": None, "locality": single_token}
        # Otherwise treat as market
        else:
            logger.debug(f"[parse_main_lob] Single token is market: {single_token}")
            return {"platform": None, "market": single_token, "locality": None}

    platform = None
    locality = None
    market_parts = []

    # Check first part for platform
    if parts[0].lower() in PLATFORMS:
        platform = parts[0]
        remaining_parts = parts[1:]
    else:
        remaining_parts = parts

    # Check last part for locality (only if we have remaining parts)
    if remaining_parts and remaining_parts[-1].lower() in LOCALITIES:
        locality = remaining_parts[-1]
        market_parts = remaining_parts[:-1]
    else:
        market_parts = remaining_parts

    # Everything else is market
    market = " ".join(market_parts) if market_parts else None

    result = {
        "platform": platform,
        "market": market,
        "locality": locality
    }

    logger.debug(f"[parse_main_lob] '{main_lob}' -> {result}")
    return result


def validate_category_config(config: Dict) -> None:
    """
    Validate category configuration structure and rules.

    Args:
        config: Configuration dictionary to validate

    Raises:
        ValueError: If configuration is invalid
    """
    if not isinstance(config, dict):
        raise ValueError("Config must be a dictionary")

    if "categories" not in config:
        raise ValueError("Config must have 'categories' key")

    categories = config["categories"]
    if not isinstance(categories, list):
        raise ValueError("'categories' must be a list")

    seen_ids = set()

    def validate_category(cat: Dict, expected_level: int = 1):
        """Recursively validate a category and its children."""
        # Check required fields
        required_fields = ["id", "name", "level", "rules"]
        for field in required_fields:
            if field not in cat:
                raise ValueError(f"Category missing required field '{field}': {cat.get('name', 'unknown')}")

        # Validate id uniqueness
        cat_id = cat["id"]
        if cat_id in seen_ids:
            raise ValueError(f"Duplicate category ID found: {cat_id}")
        seen_ids.add(cat_id)

        # Validate level
        cat_level = cat["level"]
        if not isinstance(cat_level, int) or cat_level < 1 or cat_level > 7:
            raise ValueError(f"Category '{cat['name']}' has invalid level: {cat_level} (must be 1-7)")

        # Validate level matches hierarchy depth
        if cat_level != expected_level:
            raise ValueError(
                f"Category '{cat['name']}' has level {cat_level} but should be level {expected_level} "
                f"based on hierarchy depth (parent level + 1)"
            )

        # Validate rules structure
        rules = cat["rules"]
        if not isinstance(rules, dict):
            raise ValueError(f"Category '{cat['name']}' rules must be a dictionary")

        # Validate rule fields
        valid_rule_fields = ["platform", "market", "locality", "worktype", "worktype_id", "state"]
        for field, values in rules.items():
            if field not in valid_rule_fields:
                logger.warning(f"[ManagerView] Unknown rule field '{field}' in category '{cat['name']}'")
            if values and not isinstance(values, list):
                raise ValueError(f"Category '{cat['name']}' rule '{field}' must be a list of values")

        # Validate children
        children = cat.get("children", [])
        if not isinstance(children, list):
            raise ValueError(f"Category '{cat['name']}' children must be a list")

        for child in children:
            validate_category(child, expected_level + 1)

    # Validate all top-level categories
    for category in categories:
        validate_category(category)

    logger.info(f"[ManagerView] Config validation passed: {len(seen_ids)} categories found")


def load_category_config(config_path: Optional[str] = None) -> Dict:
    """
    Load hierarchical category configuration from JSON file.

    Args:
        config_path: Path to config file. If None, uses default location.

    Returns:
        Dict containing category hierarchy and rules

    Raises:
        ValueError: If configuration is invalid
        FileNotFoundError: If config file doesn't exist
    """
    if config_path is None:
        # Default config path
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(current_dir, "config", "forecast_grouping_rules.json")

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        logger.info(f"[ManagerView] Loaded category config from {config_path}")

        # Validate the loaded config
        validate_category_config(config)

        return config

    except FileNotFoundError:
        logger.error(f"[ManagerView] Config file not found: {config_path}")
        raise FileNotFoundError(f"Forecast grouping config file not found: {config_path}")
    except json.JSONDecodeError as e:
        logger.error(f"[ManagerView] Invalid JSON in config file: {e}")
        raise ValueError(f"Invalid JSON in forecast grouping config: {e}")


def match_category_rule(record: Dict, rule: Dict) -> bool:
    """
    Check if a forecast record matches a category rule.

    Rules work as filters:
    - If a field is specified in the rule → filter strictly on those values
    - If a field is NOT in the rule → include ALL values (no filtering)

    Matching strategies:
    - platform, market, locality, worktype, state: exact match (case-insensitive)
    - worktype_id: substring match - checks if Call_Type_ID contains the value (case-insensitive)

    Args:
        record: Dictionary containing forecast record data
        rule: Dictionary containing matching conditions
              Possible fields: platform, market, locality, worktype, worktype_id, state

    Returns:
        True if record matches all conditions in the rule
    """
    main_lob = record.get("Centene_Capacity_Plan_Main_LOB", "")
    lob_components = parse_main_lob(main_lob)

    # Check each condition in the rule
    for field, allowed_values in rule.items():
        if not allowed_values:  # Skip empty rule conditions
            continue

        # Make values case-insensitive for matching
        allowed_values_lower = [str(v).lower().strip() for v in allowed_values]

        # Handle LOB components (parsed from main_lob)
        if field == "platform":
            platform_val = lob_components.get("platform", "")
            if not platform_val or platform_val.lower().strip() not in allowed_values_lower:
                return False
        elif field == "market":
            market_val = lob_components.get("market", "")
            if not market_val or market_val.lower().strip() not in allowed_values_lower:
                return False
        elif field == "locality":
            locality_val = lob_components.get("locality", "")
            if not locality_val or locality_val.lower().strip() not in allowed_values_lower:
                return False
        # Handle direct database field matching
        elif field == "worktype":
            worktype = record.get("Centene_Capacity_Plan_Case_Type", "")
            if not worktype or worktype.lower().strip() not in allowed_values_lower:
                return False
        elif field == "worktype_id":
            # Substring matching: check if Call_Type_ID contains any allowed value
            call_type_id = record.get("Centene_Capacity_Plan_Call_Type_ID", "")
            if not call_type_id:
                return False
            call_type_id_lower = call_type_id.lower().strip()
            # Check if any of the allowed values is present in call_type_id
            if not any(value in call_type_id_lower for value in allowed_values_lower):
                return False
        elif field == "state":
            state = record.get("Centene_Capacity_Plan_State", "")
            if not state or state.lower().strip() not in allowed_values_lower:
                return False

    return True


def calculate_month_metrics(records: List[Dict], month_index: int) -> Dict[str, int]:
    """
    Calculate metrics (cf, hc, cap, gap) for a specific month.

    Args:
        records: List of forecast records
        month_index: Month number (1-6)

    Returns:
        Dict with cf, hc, cap, gap
    """
    cf_col = f"Client_Forecast_Month{month_index}"
    hc_col = f"FTE_Avail_Month{month_index}"
    cap_col = f"Capacity_Month{month_index}"

    cf = sum(record.get(cf_col, 0) or 0 for record in records)
    hc = sum(record.get(hc_col, 0) or 0 for record in records)
    cap = sum(record.get(cap_col, 0) or 0 for record in records)
    gap = cap - cf

    return {
        "cf": int(cf),
        "hc": int(hc),
        "cap": int(cap),
        "gap": int(gap)
    }


def build_category_node(
    category_def: Dict,
    all_records: List[Dict],
    forecast_months: List[str]
) -> Dict:
    """
    Build a single category node with its data and children.

    Uses bottom-up aggregation:
    - Leaf nodes (no children): metrics calculated from filtered records
    - Parent nodes (with children): metrics = sum of children's metrics
    - Always returns a node (with zeros if no matching records)

    Args:
        category_def: Category definition from config
        all_records: All forecast records
        forecast_months: List of forecast month strings (YYYY-MM format)

    Returns:
        Category node dict (never None, shows zeros if no data)
    """
    # Filter records matching this category
    matching_records = [
        record for record in all_records
        if match_category_rule(record, category_def.get("rules", {}))
    ]

    # Build node structure first
    node = {
        "id": category_def["id"],
        "name": category_def["name"],
        "level": category_def.get("level", 1),
        "has_children": False,
        "data": {},
        "children": []
    }

    # Check if this category has children defined in config
    has_children_in_config = "children" in category_def and len(category_def["children"]) > 0

    # Process children recursively FIRST (bottom-up)
    if has_children_in_config:
        for child_def in category_def["children"]:
            # ALWAYS add child (even if it has zero metrics)
            child_node = build_category_node(child_def, matching_records, forecast_months)
            node["children"].append(child_node)

        node["has_children"] = True

    # Calculate metrics based on whether node has children
    if node["has_children"]:
        # PARENT NODE: Sum children's metrics (bottom-up aggregation)
        data = {}
        for idx, month_str in enumerate(forecast_months, start=1):
            if idx <= 6:  # Only 6 forecast months
                # Initialize with zeros
                total_cf = 0
                total_hc = 0
                total_cap = 0

                # Sum all children's metrics for this month
                for child in node["children"]:
                    child_month_data = child["data"].get(month_str, {})
                    total_cf += child_month_data.get("cf", 0)
                    total_hc += child_month_data.get("hc", 0)
                    total_cap += child_month_data.get("cap", 0)

                # Calculate gap as difference (not sum of children's gaps)
                total_gap = total_cap - total_cf

                data[month_str] = {
                    "cf": total_cf,
                    "hc": total_hc,
                    "cap": total_cap,
                    "gap": total_gap
                }

        node["data"] = data
        logger.debug(f"[Category] {node['id']} (parent): metrics aggregated from {len(node['children'])} children")
    else:
        # LEAF NODE: Calculate metrics from filtered records (or zeros if no records)
        data = {}
        for idx, month_str in enumerate(forecast_months, start=1):
            if idx <= 6:  # Only 6 forecast months
                if matching_records:
                    metrics = calculate_month_metrics(matching_records, idx)
                else:
                    # No matching records - return zeros
                    metrics = {"cf": 0, "hc": 0, "cap": 0, "gap": 0}
                data[month_str] = metrics

        node["data"] = data
        logger.debug(f"[Category] {node['id']} (leaf): metrics calculated from {len(matching_records)} records")

    return node


def get_forecast_months_from_db(db_manager:DBManager, month: str, year: int) -> List[str]:
    """
    Get forecast months list from ForecastMonthsModel.

    Args:
        db_manager: DBManager instance for ForecastMonthsModel
        month: Report month name (e.g., "February")
        year: Report year

    Returns:
        List of 6 month strings in YYYY-MM format
    """
    try:
        months_list = db_manager.get_forecast_months_list(month, year)

        if not months_list or len(months_list) < 6:
            logger.warning(f"[ManagerView] No forecast months found for {month} {year}")
            return []

        # Convert month names to YYYY-MM format
        result = []
        current_year = year

        for month_name_str in months_list:
            if not month_name_str:
                continue

            # Get month number from name
            try:
                month_num = list(month_name).index(month_name_str.strip())
                # Handle year rollover
                if month_num < list(month_name).index(month):
                    current_year = year + 1
                result.append(f"{current_year}-{month_num:02d}")
            except ValueError:
                logger.warning(f"[ManagerView] Invalid month name: {month_name_str}")
                continue

        return result
    except Exception as e:
        logger.error(f"[ManagerView] Error getting forecast months: {e}")
        return []


def convert_month_to_yyyy_mm(month: str, year: int) -> str:
    """
    Convert month name and year to YYYY-MM format.

    Args:
        month: Month name (e.g., "February")
        year: Year as integer

    Returns:
        String in YYYY-MM format
    """
    try:
        month_num = list(month_name).index(month.strip().capitalize())
        return f"{year}-{month_num:02d}"
    except ValueError:
        logger.error(f"[ManagerView] Invalid month name: {month}")
        return f"{year}-01"


def get_available_report_months(core_utils) -> List[Dict[str, str]]:
    """
    Get list of available report months from AllocationValidityModel.

    Only returns months where allocations are still valid (is_valid=True).

    Args:
        core_utils: CoreUtils instance for database access

    Returns:
        List of dicts with 'value' (YYYY-MM) and 'display' (Month YYYY)

    Example Output:
        [
            {"value": "2025-01", "display": "January 2025"},
            {"value": "2025-02", "display": "February 2025"},
            {"value": "2025-03", "display": "March 2025"}
        ]
    """
    try:
        db_manager = core_utils.get_db_manager(
            AllocationValidityModel,
            limit=1000,
            skip=0,
            select_columns=None
        )

        with db_manager.SessionLocal() as session:
            # Query all valid allocation records
            validity_records = session.query(AllocationValidityModel).filter(
                AllocationValidityModel.is_valid == True
            ).all()

            if not validity_records:
                logger.warning("[ManagerView] No valid allocation records found")
                return []

            # Create unique month-year combinations
            month_year_set = set()
            for record in validity_records:
                if record.month and record.year:
                    month_year_set.add((record.month, record.year))

            # Sort by year and month
            sorted_months = sorted(
                month_year_set,
                key=lambda x: (x[1], list(month_name).index(x[0]) if x[0] in month_name else 0)
            )

            # Format as required
            result = []
            for month, year in sorted_months:
                yyyy_mm = convert_month_to_yyyy_mm(month, year)
                display = f"{month} {year}"
                result.append({
                    "value": yyyy_mm,
                    "display": display
                })

            logger.info(f"[ManagerView] Found {len(result)} valid report months")
            return result

    except Exception as e:
        logger.error(f"[ManagerView] Error getting available months: {e}", exc_info=True)
        return []


def build_category_tree(
    records: List[Dict],
    forecast_months: List[str],
    category_filter: Optional[str] = None,
    config: Optional[Dict] = None
) -> List[Dict]:
    """
    Build hierarchical category tree with metrics.

    Args:
        records: List of forecast records
        forecast_months: List of forecast month strings
        category_filter: Optional category ID to filter
        config: Category configuration (loads default if None)

    Returns:
        List of category nodes
    """
    if config is None:
        config = load_category_config()

    categories = config.get("categories", [])

    if not categories:
        logger.warning("[ManagerView] No categories defined in config")
        return []

    # If category filter is provided, find and build only that category
    if category_filter:
        for cat_def in categories:
            if cat_def["id"] == category_filter:
                node = build_category_node(cat_def, records, forecast_months)
                return [node]

        logger.warning(f"[ManagerView] Category not found: {category_filter}")
        return []

    # Build all top-level categories (always returns nodes, even with zero metrics)
    result = []
    for cat_def in categories:
        node = build_category_node(cat_def, records, forecast_months)
        result.append(node)

    return result


def get_category_list(config: Optional[Dict] = None) -> List[Dict[str, str]]:
    """
    Get list of all categories for filter dropdown.

    Args:
        config: Category configuration (loads default if None)

    Returns:
        List of dicts with 'value' (id) and 'display' (name)
    """
    if config is None:
        config = load_category_config()

    categories = config.get("categories", [])

    result = [{"value": "", "display": "-- All Categories --"}]

    for cat in categories:
        result.append({
            "value": cat["id"],
            "display": cat["name"]
        })

    return result


def diagnose_record_categorization(record: Dict, config: Optional[Dict] = None) -> List[Dict]:
    """
    Diagnostic function to show why a record matched or didn't match each category.

    Returns detailed matching information for QA purposes.

    Args:
        record: Forecast record to diagnose
        config: Category configuration (loads default if None)

    Returns:
        List of dicts with category_id, matched_fields, unmatched_fields, is_match
    """
    if config is None:
        config = load_category_config()

    categories = config.get("categories", [])
    diagnostics = []

    # Parse LOB once
    main_lob = record.get("Centene_Capacity_Plan_Main_LOB", "")
    lob_components = parse_main_lob(main_lob)

    def diagnose_category(cat_def: Dict, parent_path: str = ""):
        """Recursively diagnose a category."""
        category_id = cat_def["id"]
        category_path = f"{parent_path}/{category_id}" if parent_path else category_id
        rules = cat_def.get("rules", {})

        matched_fields = {}
        unmatched_fields = {}

        # Check each rule field
        for field, allowed_values in rules.items():
            if not allowed_values:  # Skip empty rules
                continue

            allowed_values_lower = [str(v).lower().strip() for v in allowed_values]

            # Get actual value from record
            if field == "platform":
                actual_value = lob_components.get("platform", None)
            elif field == "market":
                actual_value = lob_components.get("market", None)
            elif field == "locality":
                actual_value = lob_components.get("locality", None)
            elif field == "worktype":
                actual_value = record.get("Centene_Capacity_Plan_Case_Type", None)
            elif field == "worktype_id":
                actual_value = record.get("Centene_Capacity_Plan_Call_Type_ID", None)
            elif field == "state":
                actual_value = record.get("Centene_Capacity_Plan_State", None)
            else:
                actual_value = None

            # Check if matches (different logic for worktype_id - substring matching)
            if field == "worktype_id":
                # Substring matching for worktype_id
                if actual_value:
                    actual_value_lower = actual_value.lower().strip()
                    if any(value in actual_value_lower for value in allowed_values_lower):
                        matched_fields[field] = {
                            "actual": actual_value,
                            "expected": allowed_values,
                            "match": True,
                            "match_type": "substring"
                        }
                    else:
                        unmatched_fields[field] = {
                            "actual": actual_value,
                            "expected": allowed_values,
                            "match": False,
                            "match_type": "substring"
                        }
                else:
                    unmatched_fields[field] = {
                        "actual": actual_value,
                        "expected": allowed_values,
                        "match": False,
                        "match_type": "substring"
                    }
            else:
                # Exact matching for other fields
                if actual_value and actual_value.lower().strip() in allowed_values_lower:
                    matched_fields[field] = {
                        "actual": actual_value,
                        "expected": allowed_values,
                        "match": True,
                        "match_type": "exact"
                    }
                else:
                    unmatched_fields[field] = {
                        "actual": actual_value,
                        "expected": allowed_values,
                        "match": False,
                        "match_type": "exact"
                    }

        is_match = len(unmatched_fields) == 0 and len(matched_fields) > 0

        diagnostics.append({
            "category_id": category_id,
            "category_name": cat_def["name"],
            "category_path": category_path,
            "level": cat_def.get("level", 1),
            "is_match": is_match,
            "matched_fields": matched_fields,
            "unmatched_fields": unmatched_fields,
            "total_rules": len(rules),
            "matched_rules": len(matched_fields),
            "unmatched_rules": len(unmatched_fields)
        })

        # Recursively diagnose children
        for child_def in cat_def.get("children", []):
            diagnose_category(child_def, category_path)

    # Diagnose all top-level categories
    for category in categories:
        diagnose_category(category)

    return diagnostics