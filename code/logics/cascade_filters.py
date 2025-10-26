"""
Cascade Filter Helper Functions for Forecast Data

Handles hierarchical dropdown filtering:
Year → Month → Platform → Market → Locality → Worktype

All functions preserve original case for compatibility with get_records filtering.
"""

import logging
from typing import Dict, List, Optional
from calendar import month_name

logger = logging.getLogger(__name__)

# Known platforms and localities for Main_LOB parsing (case-insensitive matching)
CASCADE_PLATFORMS = ["amisys", "facets", "xcelys"]
CASCADE_LOCALITIES = ["domestic", "global", "(domestic)", "(global)"]


def parse_main_lob_preserve_case(main_lob: str) -> Dict[str, Optional[str]]:
    """
    Parse Main_LOB into platform, market, locality components while preserving original case.

    Format: "<platform> <market> [<locality>]"
    - Platform: Amisys, Facets, or Xcelys (first word if it matches known platforms)
    - Locality: Domestic or Global (last word if it matches known localities)
    - Market: Everything in between

    Args:
        main_lob: Space-separated string like "Amisys Medicaid Domestic" or "Facets OIC Volumes"

    Returns:
        Dict with keys: platform, market, locality (original case preserved)

    Examples:
        >>> parse_main_lob_preserve_case("Amisys Medicaid Domestic")
        {'platform': 'Amisys', 'market': 'Medicaid', 'locality': 'Domestic'}

        >>> parse_main_lob_preserve_case("Amisys OIC Volumes")
        {'platform': 'Amisys', 'market': 'OIC Volumes', 'locality': None}

        >>> parse_main_lob_preserve_case("Facets Medicare Global")
        {'platform': 'Facets', 'market': 'Medicare', 'locality': 'Global'}
    """
    # Guard: Handle None, empty, or non-string inputs
    if not main_lob or not isinstance(main_lob, str):
        return {"platform": None, "market": None, "locality": None}

    main_lob_cleaned = main_lob.strip()
    if not main_lob_cleaned:
        return {"platform": None, "market": None, "locality": None}

    parts = main_lob_cleaned.split()

    # Guard: Handle single-token strings
    if len(parts) == 1:
        single_token = parts[0]
        # Check if it's a known platform (case-insensitive)
        if single_token.lower() in CASCADE_PLATFORMS:
            return {"platform": single_token, "market": None, "locality": None}
        # Check if it's a known locality
        elif single_token.lower() in CASCADE_LOCALITIES:
            return {"platform": None, "market": None, "locality": single_token}
        # Otherwise treat as market
        else:
            return {"platform": None, "market": single_token, "locality": None}

    platform = None
    locality = None
    market_parts = []

    # Check first part for platform (case-insensitive match, preserve original case)
    if parts[0].lower() in CASCADE_PLATFORMS:
        platform = parts[0]  # Preserve original case
        remaining_parts = parts[1:]
    else:
        remaining_parts = parts

    # Check last part for locality (case-insensitive match, preserve original case)
    if remaining_parts and remaining_parts[-1].lower() in CASCADE_LOCALITIES:
        locality = remaining_parts[-1]  # Preserve original case
        market_parts = remaining_parts[:-1]
    else:
        market_parts = remaining_parts

    # Everything else is market (preserve original case)
    market = " ".join(market_parts) if market_parts else None

    result = {
        "platform": platform,
        "market": market,
        "locality": locality
    }

    logger.debug(f"[CascadeFilters] Parsed '{main_lob}' -> {result}")
    return result


def generate_cascade_cache_key(prefix: str, **params) -> str:
    """
    Generate cache key with sorted parameters for consistency.

    Args:
        prefix: Cache key prefix (e.g., 'cascade:platforms')
        **params: Query parameters to include in cache key

    Returns:
        Cache key string with sorted params

    Examples:
        >>> generate_cascade_cache_key("cascade:platforms", year=2025, month=2)
        'cascade:platforms:month=2&year=2025'

        >>> generate_cascade_cache_key("cascade:years")
        'cascade:years:ALL'
    """
    sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
    if sorted_params:
        return f"{prefix}:{sorted_params}"
    return f"{prefix}:ALL"


def extract_platforms_from_main_lobs(main_lob_values: List[str]) -> List[str]:
    """
    Extract unique platforms from list of Main_LOB strings.

    Args:
        main_lob_values: List of Main_LOB strings from database (distinct values)

    Returns:
        Sorted list of unique platforms (original case preserved)

    Example:
        >>> main_lobs = ["Amisys Medicaid Domestic", "Amisys Medicare", "Facets Commercial"]
        >>> extract_platforms_from_main_lobs(main_lobs)
        ['Amisys', 'Facets']
    """
    platforms = set()

    for main_lob in main_lob_values:
        parsed = parse_main_lob_preserve_case(main_lob)
        if parsed.get("platform"):
            platforms.add(parsed["platform"])

    return sorted(list(platforms))


def extract_markets_from_main_lobs(
    main_lob_values: List[str],
    platform_filter: str
) -> List[str]:
    """
    Extract unique markets from Main_LOB strings, filtered by platform.

    Args:
        main_lob_values: List of Main_LOB strings from database
        platform_filter: Platform to filter by (case-insensitive comparison)

    Returns:
        Sorted list of unique markets (original case preserved)

    Example:
        >>> main_lobs = ["Amisys Medicaid Domestic", "Amisys Medicare", "Facets Commercial"]
        >>> extract_markets_from_main_lobs(main_lobs, "Amisys")
        ['Medicaid', 'Medicare']
    """
    markets = set()

    for main_lob in main_lob_values:
        parsed = parse_main_lob_preserve_case(main_lob)

        # Filter by platform (case-insensitive comparison)
        if parsed.get("platform", "").lower() == platform_filter.lower():
            if parsed.get("market"):
                markets.add(parsed["market"])

    return sorted(list(markets))


def extract_localities_from_main_lobs(
    main_lob_values: List[str],
    platform_filter: str,
    market_filter: str
) -> List[str]:
    """
    Extract unique localities from Main_LOB strings, filtered by platform and market.

    Args:
        main_lob_values: List of Main_LOB strings from database
        platform_filter: Platform to filter by (case-insensitive)
        market_filter: Market to filter by (case-insensitive)

    Returns:
        Sorted list of unique localities (original case preserved)

    Example:
        >>> main_lobs = ["Amisys Medicaid Domestic", "Amisys Medicaid Global", "Amisys Medicare"]
        >>> extract_localities_from_main_lobs(main_lobs, "Amisys", "Medicaid")
        ['Domestic', 'Global']
    """
    localities = set()

    for main_lob in main_lob_values:
        parsed = parse_main_lob_preserve_case(main_lob)

        # Filter by platform and market (case-insensitive)
        if (parsed.get("platform", "").lower() == platform_filter.lower() and
            parsed.get("market", "").lower() == market_filter.lower()):
            if parsed.get("locality"):
                localities.add(parsed["locality"])

    return sorted(list(localities))


def filter_main_lobs_by_criteria(
    main_lob_values: List[str],
    platform_filter: str,
    market_filter: str,
    locality_filter: Optional[str] = None
) -> List[str]:
    """
    Filter Main_LOB strings that match platform/market/locality criteria.
    Used for worktype endpoint to find which Main_LOBs match before querying Case_Type.

    Args:
        main_lob_values: List of Main_LOB strings from database
        platform_filter: Required platform to match
        market_filter: Required market to match
        locality_filter: Optional locality to match (None = all localities)

    Returns:
        List of Main_LOB strings that match all criteria

    Example:
        >>> main_lobs = ["Amisys Medicaid Domestic", "Amisys Medicaid Global", "Amisys Medicare"]
        >>> filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Domestic")
        ['Amisys Medicaid Domestic']

        >>> filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", None)
        ['Amisys Medicaid Domestic', 'Amisys Medicaid Global']
    """
    matching_lobs = []

    for main_lob in main_lob_values:
        parsed = parse_main_lob_preserve_case(main_lob)

        # Check platform match (case-insensitive)
        if parsed.get("platform", "").lower() != platform_filter.lower():
            continue

        # Check market match (case-insensitive)
        if parsed.get("market", "").lower() != market_filter.lower():
            continue

        # Check locality match if specified (case-insensitive)
        if locality_filter:
            if parsed.get("locality", "").lower() != locality_filter.lower():
                continue

        # This Main_LOB matches all criteria
        matching_lobs.append(main_lob)

    logger.debug(f"[CascadeFilters] Filtered {len(main_lob_values)} Main_LOBs -> {len(matching_lobs)} matches")
    return matching_lobs


def get_month_name_from_number(month_num: int) -> str:
    """
    Convert month number (1-12) to full month name.

    Args:
        month_num: Month number (1-12)

    Returns:
        Full month name (e.g., "January", "February")

    Example:
        >>> get_month_name_from_number(1)
        'January'
        >>> get_month_name_from_number(12)
        'December'
    """
    return list(month_name)[month_num]


def get_month_number_from_name(month_str: str) -> int:
    """
    Convert month name to number (1-12).

    Args:
        month_str: Full month name (e.g., "January", "February")

    Returns:
        Month number (1-12)

    Raises:
        ValueError: If month name is invalid

    Example:
        >>> get_month_number_from_name("January")
        1
        >>> get_month_number_from_name("December")
        12
    """
    return list(month_name).index(month_str)
