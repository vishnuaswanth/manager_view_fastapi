"""
Lightweight month-code utilities with no project-level imports.

These functions encode/decode the "Apr-2026" month-year format used throughout
the forecast pipeline, allowing year to be embedded directly in stored month codes
rather than recomputed separately from each consumer.
"""

from typing import Dict, Tuple


def get_month_abbreviation_map() -> Dict[str, str]:
    """Return mapping of 3-letter abbreviation → full month name."""
    return {
        "Jan": "January",  "Feb": "February", "Mar": "March",
        "Apr": "April",    "May": "May",       "Jun": "June",
        "Jul": "July",     "Aug": "August",    "Sep": "September",
        "Oct": "October",  "Nov": "November",  "Dec": "December",
    }


def parse_month_year_code(code: str) -> Tuple[str, int]:
    """Parse "Apr-2026" → ("April", 2026).  Handles 4-digit year.

    Raises ValueError on bad format.
    """
    parts = str(code).split('-')
    if len(parts) != 2 or len(parts[1]) != 4 or not parts[1].isdigit():
        raise ValueError(f"Expected 'MMM-YYYY' format, got: {code!r}")
    abbr, year_str = parts
    month_map = get_month_abbreviation_map()
    full_month = month_map.get(abbr.capitalize())
    if not full_month:
        raise ValueError(f"Unknown month abbreviation: {abbr!r} in {code!r}")
    return full_month, int(year_str)


def format_month_year_code(month_name: str, year: int) -> str:
    """Format ("April", 2026) → "Apr-2026"."""
    abbr = month_name.strip()[:3].capitalize()
    return f"{abbr}-{year}"


def is_month_year_code(value: str) -> bool:
    """Return True for "Apr-2026" format, False for plain "April"."""
    parts = str(value).split('-')
    return len(parts) == 2 and len(parts[1]) == 4 and parts[1].isdigit()
