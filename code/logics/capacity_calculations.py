"""
Capacity and FTE calculation utilities.

Provides standardized formulas for calculating FTE Required and Capacity
used across allocation and CPH update operations.
"""

import math
import logging
from typing import Dict

logger = logging.getLogger(__name__)


def calculate_fte_required(
    forecast: float,
    config: Dict,
    target_cph: float
) -> int:
    """
    Calculate FTE Required using standardized formula.

    Formula: fte_req = ceil(forecast / (working_days * work_hours * (1-shrinkage) * target_CPH))

    Args:
        forecast: Client forecast value (>= 0)
        config: Month configuration dict with keys:
            - working_days: int
            - work_hours: int
            - shrinkage: float (0.0-1.0)
            - occupancy: float (0.0-1.0)
        target_cph: Target Cases Per Hour (>= 0, if 0 returns 0)

    Returns:
        FTE Required (integer, always ceiling)
        Returns 0 if forecast is 0 or target_cph is 0

    Raises:
        ValueError: If parameters are invalid or result in zero denominator

    Examples:
        >>> config = {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10, 'occupancy': 0.95}
        >>> calculate_fte_required(1000, config, 50.0)
        2
        >>> calculate_fte_required(1000, config, 0)
        0
    """
    # Input validation
    if forecast < 0:
        raise ValueError(f"forecast cannot be negative: {forecast}")

    if target_cph < 0:
        raise ValueError(f"target_cph cannot be negative: {target_cph}")

    # Validate config
    required_keys = ['working_days', 'work_hours', 'shrinkage']
    missing_keys = [k for k in required_keys if k not in config]
    if missing_keys:
        raise ValueError(f"config missing required keys: {missing_keys}")

    working_days = config['working_days']
    work_hours = config['work_hours']
    shrinkage = config['shrinkage']

    # Validate config values
    if working_days <= 0:
        raise ValueError(f"working_days must be positive: {working_days}")

    if work_hours <= 0:
        raise ValueError(f"work_hours must be positive: {work_hours}")

    if not (0.0 <= shrinkage < 1.0):
        raise ValueError(f"shrinkage must be between 0.0 and 1.0: {shrinkage}")

    # Special case: zero forecast
    if forecast == 0:
        return 0

    # Special case: zero target_cph (no target set, FTE required is 0)
    if target_cph == 0:
        return 0

    # Calculate denominator
    denominator = (
        working_days *
        work_hours *
        (1 - shrinkage) *
        target_cph
    )

    if denominator <= 0:
        raise ValueError(
            f"Invalid calculation parameters result in non-positive denominator: {denominator}"
        )

    # Calculate FTE Required (always ceiling)
    try:
        fte_required = math.ceil(forecast / denominator)
        return fte_required
    except (OverflowError, ValueError) as e:
        logger.error(
            f"Error calculating FTE Required: forecast={forecast}, denominator={denominator}, error={e}",
            exc_info=True
        )
        raise ValueError(f"FTE Required calculation failed: {e}")


def calculate_capacity(
    fte_avail: int,
    config: Dict,
    target_cph: float
) -> float:
    """
    Calculate Capacity using standardized formula.

    Formula: capacity = fte_avail * working_days * work_hours * (1-shrinkage) * target_CPH

    Args:
        fte_avail: FTE Available (>= 0)
        config: Month configuration dict with keys:
            - working_days: int
            - work_hours: int
            - shrinkage: float (0.0-1.0)
            - occupancy: float (0.0-1.0)
        target_cph: Target Cases Per Hour (>= 0, if 0 returns 0.0)

    Returns:
        Capacity (float, floored to integer value - e.g., 1603.8 → 1603.0)
        Returns 0.0 if fte_avail is 0 or target_cph is 0

    Raises:
        ValueError: If parameters are invalid

    Examples:
        >>> config = {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10, 'occupancy': 0.95}
        >>> calculate_capacity(10, config, 50.0)
        8505.0
        >>> calculate_capacity(10, config, 0)
        0.0
    """
    # Input validation
    if fte_avail < 0:
        raise ValueError(f"fte_avail cannot be negative: {fte_avail}")

    if target_cph < 0:
        raise ValueError(f"target_cph cannot be negative: {target_cph}")

    # Validate config
    required_keys = ['working_days', 'work_hours', 'shrinkage']
    missing_keys = [k for k in required_keys if k not in config]
    if missing_keys:
        raise ValueError(f"config missing required keys: {missing_keys}")

    working_days = config['working_days']
    work_hours = config['work_hours']
    shrinkage = config['shrinkage']

    # Validate config values
    if working_days <= 0:
        raise ValueError(f"working_days must be positive: {working_days}")

    if work_hours <= 0:
        raise ValueError(f"work_hours must be positive: {work_hours}")

    if not (0.0 <= shrinkage < 1.0):
        raise ValueError(f"shrinkage must be between 0.0 and 1.0: {shrinkage}")

    # Special case: zero FTE available
    if fte_avail == 0:
        return 0.0

    # Special case: zero target_cph (no target set, capacity is 0)
    if target_cph == 0:
        return 0.0

    # Calculate capacity
    try:
        capacity = (
            fte_avail *
            working_days *
            work_hours *
            (1 - shrinkage) *
            target_cph
        )
        # Floor to integer (e.g., 1603.8 → 1603, 1603.996 → 1603)
        # This ensures capacity is always rounded DOWN, not to nearest
        return float(math.floor(capacity))
    except (OverflowError, ValueError) as e:
        logger.error(
            f"Error calculating Capacity: fte_avail={fte_avail}, config={config}, "
            f"target_cph={target_cph}, error={e}",
            exc_info=True
        )
        raise ValueError(f"Capacity calculation failed: {e}")


def validate_month_config(config: Dict) -> None:
    """
    Validate month configuration structure and values.

    Args:
        config: Month configuration dict to validate

    Raises:
        ValueError: If config is invalid

    Examples:
        >>> config = {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10, 'occupancy': 0.95}
        >>> validate_month_config(config)  # No exception raised
    """
    if not isinstance(config, dict):
        raise ValueError("config must be a dict")

    required_keys = ['working_days', 'work_hours', 'shrinkage', 'occupancy']
    missing_keys = [k for k in required_keys if k not in config]
    if missing_keys:
        raise ValueError(f"config missing required keys: {missing_keys}")

    # Validate types and ranges
    if not isinstance(config['working_days'], (int, float)) or config['working_days'] <= 0:
        raise ValueError(f"working_days must be positive number: {config['working_days']}")

    if not isinstance(config['work_hours'], (int, float)) or config['work_hours'] <= 0:
        raise ValueError(f"work_hours must be positive number: {config['work_hours']}")

    if not isinstance(config['shrinkage'], (int, float)) or not (0.0 <= config['shrinkage'] < 1.0):
        raise ValueError(f"shrinkage must be float between 0.0 and 1.0: {config['shrinkage']}")

    if not isinstance(config['occupancy'], (int, float)) or not (0.0 < config['occupancy'] <= 1.0):
        raise ValueError(f"occupancy must be float between 0.0 and 1.0: {config['occupancy']}")

    logger.debug(f"Month config validated successfully: {config}")
