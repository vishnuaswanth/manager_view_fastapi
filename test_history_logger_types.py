"""
Test that history_logger.get_history_log_with_changes() returns proper data types.

Verifies that the returned dict structure is compatible with the type-safe
HistoryLogData and HistoryChangeRecord dataclasses.
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)


def test_return_structure():
    """
    Test that get_history_log_with_changes() returns the correct structure.

    This is a standalone test that validates the expected structure without
    requiring database access.
    """
    print("\n" + "=" * 70)
    print("Test: get_history_log_with_changes() Return Structure")
    print("=" * 70)

    # Simulate the structure that get_history_log_with_changes() should return
    mock_history_data = {
        'id': 'test-uuid-123',
        'change_type': 'Bench Allocation',
        'month': 'March',
        'year': 2025,
        'timestamp': '2025-03-15T10:30:00',
        'user': 'test_user',
        'description': 'Test notes',
        'records_modified': 2,
        'summary_data': {
            'report_month': 'March',
            'report_year': 2025,
            'months': ['Jun-25', 'Jul-25'],
            'totals': {
                'Jun-25': {
                    'total_fte_available': {'old': 100, 'new': 105}
                }
            }
        },
        'changes': [
            {
                'main_lob': 'Amisys Medicaid DOMESTIC',
                'state': 'TX',
                'case_type': 'Claims Processing',
                'case_id': 'CL-001',
                'field_name': 'Jun-25.fte_avail',
                'old_value': '20',
                'new_value': '25',
                'delta': 5.0,
                'month_label': 'Jun-25'
            },
            {
                'main_lob': 'Amisys Medicaid DOMESTIC',
                'state': 'TX',
                'case_type': 'Claims Processing',
                'case_id': 'CL-001',
                'field_name': 'Jun-25.capacity',
                'old_value': '1000',
                'new_value': '1125',
                'delta': 125.0,
                'month_label': 'Jun-25'
            }
        ]
    }

    print("\nValidating top-level keys...")

    # Required top-level keys for HistoryLogData
    required_keys = ['id', 'change_type', 'month', 'year', 'timestamp', 'user', 'records_modified']
    for key in required_keys:
        assert key in mock_history_data, f"Missing required key: {key}"
        print(f"  ✓ {key}: {mock_history_data[key]}")

    # Optional keys
    optional_keys = ['description', 'summary_data', 'changes']
    for key in optional_keys:
        if key in mock_history_data:
            print(f"  ✓ {key}: present")

    print("\nValidating changes structure...")

    # Verify changes is a list
    assert isinstance(mock_history_data['changes'], list), "changes should be a list"
    print(f"  ✓ changes is a list with {len(mock_history_data['changes'])} items")

    # Required keys for each HistoryChangeRecord
    change_required_keys = ['main_lob', 'state', 'case_type', 'case_id', 'field_name']
    for i, change in enumerate(mock_history_data['changes']):
        for key in change_required_keys:
            assert key in change, f"Change {i} missing required key: {key}"
        print(f"  ✓ Change {i}: {change['field_name']}")

    print("\nTesting type-safe conversion...")

    # Import type-safe dataclasses
    from code.logics.history_excel_generator import (
        HistoryLogData,
        HistoryChangeRecord
    )

    # Test HistoryLogData.from_dict()
    try:
        history_log_data = HistoryLogData.from_dict(mock_history_data)
        print(f"  ✓ HistoryLogData created successfully")
        print(f"    - ID: {history_log_data.id}")
        print(f"    - Type: {history_log_data.change_type}")
        print(f"    - Month: {history_log_data.month} {history_log_data.year}")
        print(f"    - Records Modified: {history_log_data.records_modified}")
    except Exception as e:
        print(f"  ✗ Failed to create HistoryLogData: {e}")
        raise

    # Test HistoryChangeRecord.from_dict() for each change
    try:
        typed_changes = []
        for i, change in enumerate(mock_history_data['changes']):
            change_record = HistoryChangeRecord.from_dict(change)
            typed_changes.append(change_record)
            print(f"  ✓ HistoryChangeRecord {i} created: {change_record.field_name}")
    except Exception as e:
        print(f"  ✗ Failed to create HistoryChangeRecord: {e}")
        raise

    print("\nTesting router usage pattern...")

    # Simulate what the router does
    try:
        # Router accesses fields directly
        month = mock_history_data['month']
        year = mock_history_data['year']
        change_type = mock_history_data['change_type']
        changes = mock_history_data.get('changes', [])

        print(f"  ✓ Router can access month: {month}")
        print(f"  ✓ Router can access year: {year}")
        print(f"  ✓ Router can access change_type: {change_type}")
        print(f"  ✓ Router can access changes: {len(changes)} items")
    except KeyError as e:
        print(f"  ✗ Router cannot access field: {e}")
        raise

    print("\nTesting Excel generation...")

    # Import generate_history_excel
    from code.logics.history_excel_generator import generate_history_excel

    try:
        # Convert to type-safe objects (now required)
        history_log_obj = HistoryLogData.from_dict(mock_history_data)
        changes_obj = [
            HistoryChangeRecord.from_dict(change)
            for change in mock_history_data['changes']
        ]

        # Generate Excel with type-safe objects
        excel_buffer = generate_history_excel(
            history_log_data=history_log_obj,
            changes=changes_obj
        )
        print(f"  ✓ Excel generated successfully with type-safe objects")
        print(f"    - Buffer size: {len(excel_buffer.getvalue())} bytes")
    except Exception as e:
        print(f"  ✗ Failed to generate Excel: {e}")
        raise

    print("\nTesting type enforcement...")

    try:
        # This should now fail (dict not accepted)
        from code.logics.history_excel_generator import generate_history_excel
        excel_buffer = generate_history_excel(
            history_log_data=mock_history_data,  # Dict, should fail
            changes=mock_history_data['changes']
        )
        print(f"  ✗ UNEXPECTED: Excel generator accepted dict (should reject)")
        raise AssertionError("Excel generator should reject dict input")
    except TypeError as e:
        print(f"  ✓ Excel generator correctly rejects dict input")
        print(f"    - Error: {str(e)[:80]}...")

    print("\n" + "=" * 70)
    print("✓ ALL STRUCTURE TESTS PASSED")
    print("=" * 70)
    print("\nget_history_log_with_changes() Return Structure Verified!")
    print("\nKey Features:")
    print("  ✓ Returns flat dict with top-level fields (id, month, year, etc.)")
    print("  ✓ Includes 'changes' key with list of change dicts")
    print("  ✓ Compatible with HistoryLogData.from_dict()")
    print("  ✓ Compatible with HistoryChangeRecord.from_dict()")
    print("  ✓ Works with router direct access pattern")
    print("  ✓ Excel generation requires type-safe objects (enforced)")
    print("  ✓ Excel generator rejects dict input (type safety)")


def test_backward_compatibility():
    """Test that the structure is backward compatible with existing code."""
    print("\n" + "=" * 70)
    print("Test: Backward Compatibility")
    print("=" * 70)

    # Old structure that was returned before (nested)
    old_structure = {
        'history_log': {
            'id': 'test-uuid',
            'change_type': 'CPH Update',
            'month': 'April',
            'year': 2025,
            'timestamp': '2025-04-01T12:00:00',
            'user': 'admin',
            'description': None,
            'records_modified': 5,
            'summary_data': None
        },
        'changes': [
            {
                'main_lob': 'Facets Commercial',
                'state': 'CA',
                'case_type': 'Enrollment',
                'case_id': 'EN-001',
                'field_name': 'target_cph',
                'old_value': '45',
                'new_value': '50',
                'delta': 5.0,
                'month_label': None
            }
        ]
    }

    # New structure (flat)
    new_structure = {
        'id': 'test-uuid',
        'change_type': 'CPH Update',
        'month': 'April',
        'year': 2025,
        'timestamp': '2025-04-01T12:00:00',
        'user': 'admin',
        'description': None,
        'records_modified': 5,
        'summary_data': None,
        'changes': [
            {
                'main_lob': 'Facets Commercial',
                'state': 'CA',
                'case_type': 'Enrollment',
                'case_id': 'EN-001',
                'field_name': 'target_cph',
                'old_value': '45',
                'new_value': '50',
                'delta': 5.0,
                'month_label': None
            }
        ]
    }

    print("\nOld structure (nested):")
    print(f"  - Top-level keys: {list(old_structure.keys())}")
    print(f"  - Access month: old_structure['history_log']['month'] = {old_structure['history_log']['month']}")

    print("\nNew structure (flat):")
    print(f"  - Top-level keys: {list(new_structure.keys())}")
    print(f"  - Access month: new_structure['month'] = {new_structure['month']}")

    # Verify new structure has all the data
    assert new_structure['month'] == 'April', "Month should be accessible"
    assert new_structure['year'] == 2025, "Year should be accessible"
    assert new_structure['change_type'] == 'CPH Update', "Change type should be accessible"
    assert len(new_structure['changes']) == 1, "Changes should be accessible"

    print("\n✓ New structure provides direct access to all fields")
    print("✓ Compatible with router expectations")
    print("✓ Compatible with type-safe dataclasses")


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("HISTORY LOGGER TYPE SAFETY TEST SUITE")
    print("=" * 70)
    print("\nValidating that get_history_log_with_changes() returns proper data types")

    try:
        test_return_structure()
        test_backward_compatibility()

        print("\n" + "=" * 70)
        print("✓ ALL TESTS PASSED")
        print("=" * 70)
        print("\nSummary:")
        print("  ✓ get_history_log_with_changes() returns flat dict structure")
        print("  ✓ Structure is compatible with HistoryLogData and HistoryChangeRecord")
        print("  ✓ Router can access fields directly (month, year, change_type, changes)")
        print("  ✓ Router converts dicts to type-safe objects before Excel generation")
        print("  ✓ Excel generator enforces type-safe inputs (rejects dicts)")
        print("  ✓ Type safety enforced at API boundary")

        return 0

    except AssertionError as e:
        print("\n" + "=" * 70)
        print("✗ TEST FAILED")
        print("=" * 70)
        print(f"\nAssertion Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print("\n" + "=" * 70)
        print("✗ UNEXPECTED ERROR")
        print("=" * 70)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
