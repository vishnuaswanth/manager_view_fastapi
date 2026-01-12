"""
Unit tests for capacity_calculations module.

Tests the standardized FTE and Capacity calculation functions to ensure
correctness, validation, and edge case handling.
"""

import pytest
import math
from code.logics.capacity_calculations import (
    calculate_fte_required,
    calculate_capacity,
    validate_month_config
)


class TestCalculateFTERequired:
    """Test suite for calculate_fte_required function."""

    def test_basic_calculation(self):
        """Test basic FTE calculation with valid inputs."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        # forecast / (21 * 9 * 0.90 * 50) = 1000 / 8505 = 0.117... → ceil = 1
        result = calculate_fte_required(1000, config, 50.0)
        assert result == 1
        assert isinstance(result, int)

    def test_high_forecast_requires_multiple_fte(self):
        """Test that high forecast values result in multiple FTEs."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        # 50000 / 8505 = 5.88... → ceil = 6
        result = calculate_fte_required(50000, config, 50.0)
        assert result == 6

    def test_zero_forecast_returns_zero(self):
        """Test that zero forecast returns zero FTE."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        result = calculate_fte_required(0, config, 50.0)
        assert result == 0

    def test_ceiling_behavior(self):
        """Test that result is always ceiling (rounded up)."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        # Even tiny fractions should round up
        result = calculate_fte_required(1, config, 50.0)
        assert result == 1

    def test_negative_forecast_raises_error(self):
        """Test that negative forecast raises ValueError."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        with pytest.raises(ValueError, match="forecast cannot be negative"):
            calculate_fte_required(-100, config, 50.0)

    def test_zero_target_cph_raises_error(self):
        """Test that zero target_cph raises ValueError."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        with pytest.raises(ValueError, match="target_cph must be positive"):
            calculate_fte_required(1000, config, 0)

    def test_negative_target_cph_raises_error(self):
        """Test that negative target_cph raises ValueError."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        with pytest.raises(ValueError, match="target_cph must be positive"):
            calculate_fte_required(1000, config, -50.0)

    def test_missing_config_keys_raises_error(self):
        """Test that missing config keys raise ValueError."""
        incomplete_config = {'working_days': 21}

        with pytest.raises(ValueError, match="config missing required keys"):
            calculate_fte_required(1000, incomplete_config, 50.0)

    def test_zero_working_days_raises_error(self):
        """Test that zero working_days raises ValueError."""
        config = {
            'working_days': 0,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        with pytest.raises(ValueError, match="working_days must be positive"):
            calculate_fte_required(1000, config, 50.0)

    def test_invalid_shrinkage_raises_error(self):
        """Test that shrinkage outside 0-1 range raises ValueError."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 1.5,  # Invalid: > 1.0
            'occupancy': 0.95
        }

        with pytest.raises(ValueError, match="shrinkage must be between"):
            calculate_fte_required(1000, config, 50.0)

    def test_different_shrinkage_values(self):
        """Test calculation with different shrinkage values."""
        config_10 = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }
        config_20 = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.20,
            'occupancy': 0.95
        }

        result_10 = calculate_fte_required(10000, config_10, 50.0)
        result_20 = calculate_fte_required(10000, config_20, 50.0)

        # Higher shrinkage should require more FTEs
        assert result_20 > result_10


class TestCalculateCapacity:
    """Test suite for calculate_capacity function."""

    def test_basic_calculation(self):
        """Test basic capacity calculation with valid inputs."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        # 10 * 21 * 9 * 0.90 * 50 = 85050
        result = calculate_capacity(10, config, 50.0)
        assert result == 85050.0
        assert isinstance(result, float)

    def test_zero_fte_returns_zero(self):
        """Test that zero FTE available returns zero capacity."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        result = calculate_capacity(0, config, 50.0)
        assert result == 0.0

    def test_rounding_to_two_decimals(self):
        """Test that result is rounded to 2 decimal places."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        result = calculate_capacity(3, config, 45.7)
        # Should be rounded to 2 decimals
        assert len(str(result).split('.')[-1]) <= 2

    def test_negative_fte_raises_error(self):
        """Test that negative fte_avail raises ValueError."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        with pytest.raises(ValueError, match="fte_avail cannot be negative"):
            calculate_capacity(-5, config, 50.0)

    def test_zero_target_cph_raises_error(self):
        """Test that zero target_cph raises ValueError."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        with pytest.raises(ValueError, match="target_cph must be positive"):
            calculate_capacity(10, config, 0)

    def test_missing_config_keys_raises_error(self):
        """Test that missing config keys raise ValueError."""
        incomplete_config = {'working_days': 21, 'work_hours': 9}

        with pytest.raises(ValueError, match="config missing required keys"):
            calculate_capacity(10, incomplete_config, 50.0)

    def test_proportional_to_fte(self):
        """Test that capacity is proportional to FTE available."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        result_5 = calculate_capacity(5, config, 50.0)
        result_10 = calculate_capacity(10, config, 50.0)

        # 10 FTE should give exactly double the capacity of 5 FTE
        assert result_10 == result_5 * 2

    def test_proportional_to_cph(self):
        """Test that capacity is proportional to target CPH."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        result_30 = calculate_capacity(10, config, 30.0)
        result_60 = calculate_capacity(10, config, 60.0)

        # 60 CPH should give exactly double the capacity of 30 CPH
        assert result_60 == result_30 * 2


class TestValidateMonthConfig:
    """Test suite for validate_month_config function."""

    def test_valid_config_passes(self):
        """Test that valid config passes validation."""
        valid_config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        # Should not raise any exception
        validate_month_config(valid_config)

    def test_non_dict_raises_error(self):
        """Test that non-dict config raises ValueError."""
        with pytest.raises(ValueError, match="config must be a dict"):
            validate_month_config("not a dict")

    def test_missing_keys_raises_error(self):
        """Test that missing required keys raise ValueError."""
        incomplete_config = {'working_days': 21, 'work_hours': 9}

        with pytest.raises(ValueError, match="config missing required keys"):
            validate_month_config(incomplete_config)

    def test_invalid_working_days_raises_error(self):
        """Test that invalid working_days raise ValueError."""
        invalid_configs = [
            {'working_days': 0, 'work_hours': 9, 'shrinkage': 0.10, 'occupancy': 0.95},
            {'working_days': -5, 'work_hours': 9, 'shrinkage': 0.10, 'occupancy': 0.95},
            {'working_days': 'twenty', 'work_hours': 9, 'shrinkage': 0.10, 'occupancy': 0.95},
        ]

        for config in invalid_configs:
            with pytest.raises(ValueError, match="working_days must be positive"):
                validate_month_config(config)

    def test_invalid_shrinkage_raises_error(self):
        """Test that invalid shrinkage values raise ValueError."""
        invalid_configs = [
            {'working_days': 21, 'work_hours': 9, 'shrinkage': -0.1, 'occupancy': 0.95},
            {'working_days': 21, 'work_hours': 9, 'shrinkage': 1.5, 'occupancy': 0.95},
            {'working_days': 21, 'work_hours': 9, 'shrinkage': 'high', 'occupancy': 0.95},
        ]

        for config in invalid_configs:
            with pytest.raises(ValueError, match="shrinkage must be float between"):
                validate_month_config(config)

    def test_invalid_occupancy_raises_error(self):
        """Test that invalid occupancy values raise ValueError."""
        invalid_configs = [
            {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10, 'occupancy': 0},
            {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10, 'occupancy': 1.5},
            {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10, 'occupancy': -0.5},
        ]

        for config in invalid_configs:
            with pytest.raises(ValueError, match="occupancy must be float between"):
                validate_month_config(config)

    def test_boundary_values(self):
        """Test config validation with boundary values."""
        # Valid boundary cases
        valid_boundaries = [
            {'working_days': 1, 'work_hours': 1, 'shrinkage': 0.0, 'occupancy': 0.01},
            {'working_days': 31, 'work_hours': 24, 'shrinkage': 0.99, 'occupancy': 1.0},
        ]

        for config in valid_boundaries:
            # Should not raise
            validate_month_config(config)


class TestIntegration:
    """Integration tests for capacity calculations workflow."""

    def test_fte_and_capacity_relationship(self):
        """Test relationship between FTE Required and Capacity calculations."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        forecast = 10000
        target_cph = 50.0

        # Calculate FTE required for forecast
        fte_required = calculate_fte_required(forecast, config, target_cph)

        # Calculate capacity for that FTE
        capacity = calculate_capacity(fte_required, config, target_cph)

        # Capacity should be >= forecast (since we ceil FTE)
        assert capacity >= forecast

    def test_different_config_scenarios(self):
        """Test calculations with various realistic config scenarios."""
        scenarios = [
            # Domestic config
            {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10, 'occupancy': 0.95},
            # Global config (higher shrinkage)
            {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.15, 'occupancy': 0.90},
            # Peak season (more working days)
            {'working_days': 23, 'work_hours': 9, 'shrinkage': 0.10, 'occupancy': 0.95},
        ]

        forecast = 5000
        target_cph = 45.0

        for config in scenarios:
            fte = calculate_fte_required(forecast, config, target_cph)
            capacity = calculate_capacity(fte, config, target_cph)

            # All should be valid positive values
            assert fte > 0
            assert capacity > 0
            assert capacity >= forecast

    def test_realistic_workforce_scenario(self):
        """Test a realistic workforce planning scenario."""
        config = {
            'working_days': 21,
            'work_hours': 9,
            'shrinkage': 0.10,
            'occupancy': 0.95
        }

        # Team of 25 FTEs with target CPH of 50
        fte_available = 25
        target_cph = 50.0

        # Calculate what they can handle
        capacity = calculate_capacity(fte_available, config, target_cph)

        # Now calculate FTE needed for that capacity
        fte_needed = calculate_fte_required(capacity, config, target_cph)

        # Should need exactly the same (or very close due to ceiling)
        assert fte_needed == fte_available or fte_needed == fte_available + 1
