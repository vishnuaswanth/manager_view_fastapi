"""
Unit tests for Target CPH configuration utilities.

Tests cover CRUD operations for Target CPH configurations including:
- Adding single configurations
- Bulk adding configurations
- Retrieving configurations with filters
- Getting all configurations as a lookup dict
- Updating configurations
- Deleting configurations

Run tests with:
    python -m pytest code/logics/test_target_cph.py -v
"""

import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from code.logics.target_cph_utils import (
    add_target_cph_configuration,
    bulk_add_target_cph_configurations,
    get_target_cph_configuration,
    get_all_target_cph_as_dict,
    get_specific_target_cph,
    update_target_cph_configuration,
    delete_target_cph_configuration,
    get_target_cph_count,
    get_distinct_main_lobs,
    get_distinct_case_types,
    _validate_target_cph_input,
    MIN_TARGET_CPH,
    MAX_TARGET_CPH,
    MAX_LOB_LENGTH,
    MAX_CASE_TYPE_LENGTH
)


class TestValidation:
    """Tests for input validation."""

    def test_valid_input(self):
        """Valid inputs should pass validation."""
        is_valid, error = _validate_target_cph_input(
            main_lob="Amisys Medicaid GLOBAL",
            case_type="FTC-Basic/Non MMP",
            target_cph=12.0
        )
        assert is_valid is True
        assert error == ""

    def test_empty_main_lob(self):
        """Empty MainLOB should fail validation."""
        is_valid, error = _validate_target_cph_input(
            main_lob="",
            case_type="FTC-Basic",
            target_cph=12.0
        )
        assert is_valid is False
        assert "MainLOB cannot be empty" in error

    def test_whitespace_main_lob(self):
        """Whitespace-only MainLOB should fail validation."""
        is_valid, error = _validate_target_cph_input(
            main_lob="   ",
            case_type="FTC-Basic",
            target_cph=12.0
        )
        assert is_valid is False
        assert "MainLOB cannot be empty" in error

    def test_empty_case_type(self):
        """Empty CaseType should fail validation."""
        is_valid, error = _validate_target_cph_input(
            main_lob="Amisys",
            case_type="",
            target_cph=12.0
        )
        assert is_valid is False
        assert "CaseType cannot be empty" in error

    def test_target_cph_below_minimum(self):
        """Target CPH below minimum should fail validation."""
        is_valid, error = _validate_target_cph_input(
            main_lob="Amisys",
            case_type="FTC-Basic",
            target_cph=0.05
        )
        assert is_valid is False
        assert f"at least {MIN_TARGET_CPH}" in error

    def test_target_cph_above_maximum(self):
        """Target CPH above maximum should fail validation."""
        is_valid, error = _validate_target_cph_input(
            main_lob="Amisys",
            case_type="FTC-Basic",
            target_cph=250.0
        )
        assert is_valid is False
        assert f"cannot exceed {MAX_TARGET_CPH}" in error

    def test_target_cph_negative(self):
        """Negative Target CPH should fail validation."""
        is_valid, error = _validate_target_cph_input(
            main_lob="Amisys",
            case_type="FTC-Basic",
            target_cph=-5.0
        )
        assert is_valid is False

    def test_target_cph_boundary_minimum(self):
        """Target CPH at minimum boundary should pass."""
        is_valid, error = _validate_target_cph_input(
            main_lob="Amisys",
            case_type="FTC-Basic",
            target_cph=MIN_TARGET_CPH
        )
        assert is_valid is True

    def test_target_cph_boundary_maximum(self):
        """Target CPH at maximum boundary should pass."""
        is_valid, error = _validate_target_cph_input(
            main_lob="Amisys",
            case_type="FTC-Basic",
            target_cph=MAX_TARGET_CPH
        )
        assert is_valid is True


class TestAddTargetCPH:
    """Tests for add_target_cph_configuration function."""

    def test_add_valid_configuration(self):
        """Adding a valid configuration should succeed."""
        # Use unique values to avoid conflicts with existing data
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        success, message = add_target_cph_configuration(
            main_lob=f"Test LOB {unique_id}",
            case_type=f"Test Case {unique_id}",
            target_cph=10.0,
            created_by="test_user"
        )

        assert success is True
        assert "successfully" in message.lower() or "added" in message.lower()

        # Cleanup
        configs = get_target_cph_configuration(main_lob=f"Test LOB {unique_id}")
        if configs:
            delete_target_cph_configuration(configs[0]['id'])

    def test_add_duplicate_configuration(self):
        """Adding a duplicate configuration should fail."""
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        # Add first
        success1, _ = add_target_cph_configuration(
            main_lob=f"Dup LOB {unique_id}",
            case_type=f"Dup Case {unique_id}",
            target_cph=10.0,
            created_by="test_user"
        )
        assert success1 is True

        # Try to add duplicate
        success2, message = add_target_cph_configuration(
            main_lob=f"Dup LOB {unique_id}",
            case_type=f"Dup Case {unique_id}",
            target_cph=15.0,
            created_by="test_user"
        )
        assert success2 is False
        assert "already exists" in message.lower()

        # Cleanup
        configs = get_target_cph_configuration(main_lob=f"Dup LOB {unique_id}")
        if configs:
            delete_target_cph_configuration(configs[0]['id'])

    def test_add_with_invalid_target_cph(self):
        """Adding with invalid Target CPH should fail."""
        success, message = add_target_cph_configuration(
            main_lob="Invalid CPH Test",
            case_type="Test Case",
            target_cph=-5.0,
            created_by="test_user"
        )
        assert success is False


class TestBulkAddTargetCPH:
    """Tests for bulk_add_target_cph_configurations function."""

    def test_bulk_add_valid_configurations(self):
        """Bulk adding valid configurations should succeed."""
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        configs = [
            {
                'main_lob': f'Bulk LOB 1 {unique_id}',
                'case_type': f'Bulk Case 1 {unique_id}',
                'target_cph': 10.0,
                'created_by': 'test_user'
            },
            {
                'main_lob': f'Bulk LOB 2 {unique_id}',
                'case_type': f'Bulk Case 2 {unique_id}',
                'target_cph': 12.0,
                'created_by': 'test_user'
            }
        ]

        result = bulk_add_target_cph_configurations(configs)

        assert result['total'] == 2
        assert result['succeeded'] == 2
        assert result['failed'] == 0

        # Cleanup
        for config in configs:
            db_configs = get_target_cph_configuration(main_lob=config['main_lob'])
            if db_configs:
                delete_target_cph_configuration(db_configs[0]['id'])

    def test_bulk_add_with_duplicates(self):
        """Bulk adding with duplicates should skip duplicates."""
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        configs = [
            {
                'main_lob': f'Bulk Dup {unique_id}',
                'case_type': f'Bulk Dup Case {unique_id}',
                'target_cph': 10.0,
                'created_by': 'test_user'
            },
            {
                'main_lob': f'Bulk Dup {unique_id}',  # Duplicate
                'case_type': f'Bulk Dup Case {unique_id}',
                'target_cph': 12.0,
                'created_by': 'test_user'
            }
        ]

        result = bulk_add_target_cph_configurations(configs)

        assert result['total'] == 2
        assert result['succeeded'] == 1
        assert result['duplicates_skipped'] == 1

        # Cleanup
        db_configs = get_target_cph_configuration(main_lob=f'Bulk Dup {unique_id}')
        if db_configs:
            delete_target_cph_configuration(db_configs[0]['id'])

    def test_bulk_add_empty_list(self):
        """Bulk adding empty list should return zero results."""
        result = bulk_add_target_cph_configurations([])

        assert result['total'] == 0
        assert result['succeeded'] == 0


class TestGetTargetCPH:
    """Tests for get_target_cph_configuration function."""

    def test_get_all_configurations(self):
        """Getting all configurations should return a list."""
        configs = get_target_cph_configuration()
        assert isinstance(configs, list)

    def test_get_with_main_lob_filter(self):
        """Filtering by Main LOB should work."""
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        # Add test data
        add_target_cph_configuration(
            main_lob=f'Filter Test LOB {unique_id}',
            case_type=f'Filter Test Case {unique_id}',
            target_cph=10.0,
            created_by='test_user'
        )

        configs = get_target_cph_configuration(main_lob=f'Filter Test LOB {unique_id}')

        assert len(configs) >= 1
        assert all(unique_id in c['main_lob'] for c in configs)

        # Cleanup
        for config in configs:
            delete_target_cph_configuration(config['id'])

    def test_get_with_case_type_filter(self):
        """Filtering by Case Type should work."""
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        # Add test data
        add_target_cph_configuration(
            main_lob=f'Case Filter LOB {unique_id}',
            case_type=f'Unique Case {unique_id}',
            target_cph=10.0,
            created_by='test_user'
        )

        configs = get_target_cph_configuration(case_type=f'Unique Case {unique_id}')

        assert len(configs) >= 1
        assert all(unique_id in c['case_type'] for c in configs)

        # Cleanup
        for config in configs:
            delete_target_cph_configuration(config['id'])


class TestGetAllTargetCPHAsDict:
    """Tests for get_all_target_cph_as_dict function."""

    def test_returns_dict(self):
        """Should return a dictionary."""
        result = get_all_target_cph_as_dict()
        assert isinstance(result, dict)

    def test_dict_keys_are_tuples(self):
        """Dictionary keys should be (main_lob, case_type) tuples."""
        result = get_all_target_cph_as_dict()

        for key in result.keys():
            assert isinstance(key, tuple)
            assert len(key) == 2

    def test_dict_values_are_floats(self):
        """Dictionary values should be floats."""
        result = get_all_target_cph_as_dict()

        for value in result.values():
            assert isinstance(value, float)

    def test_keys_are_lowercased(self):
        """Dictionary keys should be lowercased for case-insensitive matching."""
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        # Add with mixed case
        add_target_cph_configuration(
            main_lob=f'UPPER Case LOB {unique_id}',
            case_type=f'MiXeD Case Type {unique_id}',
            target_cph=10.0,
            created_by='test_user'
        )

        result = get_all_target_cph_as_dict()

        # Key should be lowercased
        expected_key = (f'upper case lob {unique_id}', f'mixed case type {unique_id}')
        assert expected_key in result

        # Cleanup
        configs = get_target_cph_configuration(main_lob=f'UPPER Case LOB {unique_id}')
        if configs:
            delete_target_cph_configuration(configs[0]['id'])


class TestUpdateTargetCPH:
    """Tests for update_target_cph_configuration function."""

    def test_update_target_cph_value(self):
        """Updating Target CPH value should succeed."""
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        # Add test data
        add_target_cph_configuration(
            main_lob=f'Update Test {unique_id}',
            case_type=f'Update Case {unique_id}',
            target_cph=10.0,
            created_by='test_user'
        )

        configs = get_target_cph_configuration(main_lob=f'Update Test {unique_id}')
        config_id = configs[0]['id']

        success, message = update_target_cph_configuration(
            config_id=config_id,
            target_cph=15.0,
            updated_by='test_user'
        )

        assert success is True

        # Verify update
        updated_configs = get_target_cph_configuration(config_id=config_id)
        assert updated_configs[0]['target_cph'] == 15.0

        # Cleanup
        delete_target_cph_configuration(config_id)

    def test_update_nonexistent_config(self):
        """Updating nonexistent config should fail."""
        success, message = update_target_cph_configuration(
            config_id=999999,
            target_cph=15.0,
            updated_by='test_user'
        )

        assert success is False
        assert "not found" in message.lower()

    def test_update_with_invalid_value(self):
        """Updating with invalid value should fail."""
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        # Add test data
        add_target_cph_configuration(
            main_lob=f'Invalid Update {unique_id}',
            case_type=f'Invalid Update Case {unique_id}',
            target_cph=10.0,
            created_by='test_user'
        )

        configs = get_target_cph_configuration(main_lob=f'Invalid Update {unique_id}')
        config_id = configs[0]['id']

        success, message = update_target_cph_configuration(
            config_id=config_id,
            target_cph=-5.0,
            updated_by='test_user'
        )

        assert success is False

        # Cleanup
        delete_target_cph_configuration(config_id)


class TestDeleteTargetCPH:
    """Tests for delete_target_cph_configuration function."""

    def test_delete_existing_config(self):
        """Deleting existing config should succeed."""
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        # Add test data
        add_target_cph_configuration(
            main_lob=f'Delete Test {unique_id}',
            case_type=f'Delete Case {unique_id}',
            target_cph=10.0,
            created_by='test_user'
        )

        configs = get_target_cph_configuration(main_lob=f'Delete Test {unique_id}')
        config_id = configs[0]['id']

        success, message = delete_target_cph_configuration(config_id)

        assert success is True
        assert "deleted" in message.lower() or "successfully" in message.lower()

        # Verify deletion
        deleted_configs = get_target_cph_configuration(config_id=config_id)
        assert len(deleted_configs) == 0

    def test_delete_nonexistent_config(self):
        """Deleting nonexistent config should fail."""
        success, message = delete_target_cph_configuration(999999)

        assert success is False
        assert "not found" in message.lower()


class TestSpecificTargetCPH:
    """Tests for get_specific_target_cph function."""

    def test_get_existing_specific_cph(self):
        """Getting existing specific CPH should return value."""
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        # Add test data
        add_target_cph_configuration(
            main_lob=f'Specific Test {unique_id}',
            case_type=f'Specific Case {unique_id}',
            target_cph=12.5,
            created_by='test_user'
        )

        result = get_specific_target_cph(
            main_lob=f'Specific Test {unique_id}',
            case_type=f'Specific Case {unique_id}'
        )

        assert result == 12.5

        # Cleanup
        configs = get_target_cph_configuration(main_lob=f'Specific Test {unique_id}')
        if configs:
            delete_target_cph_configuration(configs[0]['id'])

    def test_get_nonexistent_specific_cph(self):
        """Getting nonexistent specific CPH should return None."""
        result = get_specific_target_cph(
            main_lob='Nonexistent LOB',
            case_type='Nonexistent Case'
        )

        assert result is None

    def test_case_insensitive_lookup(self):
        """Lookup should be case-insensitive."""
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        # Add with specific case
        add_target_cph_configuration(
            main_lob=f'Case Sensitive Test {unique_id}',
            case_type=f'Case Sensitive Type {unique_id}',
            target_cph=8.0,
            created_by='test_user'
        )

        # Lookup with different case
        result = get_specific_target_cph(
            main_lob=f'CASE SENSITIVE TEST {unique_id}',
            case_type=f'case sensitive type {unique_id}'
        )

        assert result == 8.0

        # Cleanup
        configs = get_target_cph_configuration(main_lob=f'Case Sensitive Test {unique_id}')
        if configs:
            delete_target_cph_configuration(configs[0]['id'])


class TestDistinctValues:
    """Tests for distinct value retrieval functions."""

    def test_get_distinct_main_lobs(self):
        """Getting distinct Main LOBs should return list."""
        result = get_distinct_main_lobs()
        assert isinstance(result, list)

    def test_get_distinct_case_types(self):
        """Getting distinct Case Types should return list."""
        result = get_distinct_case_types()
        assert isinstance(result, list)

    def test_get_distinct_case_types_with_filter(self):
        """Getting distinct Case Types with filter should work."""
        import uuid
        unique_id = str(uuid.uuid4())[:8]

        # Add test data with specific LOB
        add_target_cph_configuration(
            main_lob=f'Distinct Filter LOB {unique_id}',
            case_type=f'Distinct Case A {unique_id}',
            target_cph=10.0,
            created_by='test_user'
        )
        add_target_cph_configuration(
            main_lob=f'Distinct Filter LOB {unique_id}',
            case_type=f'Distinct Case B {unique_id}',
            target_cph=12.0,
            created_by='test_user'
        )

        result = get_distinct_case_types(main_lob=f'Distinct Filter LOB {unique_id}')

        assert len(result) >= 2

        # Cleanup
        configs = get_target_cph_configuration(main_lob=f'Distinct Filter LOB {unique_id}')
        for config in configs:
            delete_target_cph_configuration(config['id'])


class TestCount:
    """Tests for count function."""

    def test_get_count(self):
        """Getting count should return non-negative integer."""
        count = get_target_cph_count()
        assert isinstance(count, int)
        assert count >= 0


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
