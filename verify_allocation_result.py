"""
Verify AllocationResult dataclass structure.

This script confirms that AllocationResult uses 'error' not 'error_message'.
"""

from code.logics.bench_allocation import AllocationResult

# Test creating AllocationResult with error
result = AllocationResult(
    success=False,
    month="April",
    year=2025,
    total_bench_allocated=0,
    gaps_filled=0,
    excess_distributed=0,
    rows_modified=0,
    allocations=[],
    error="Test error message",
    recommendation="Test recommendation",
    context={"test": "context"}
)

print("=" * 70)
print("AllocationResult Verification")
print("=" * 70)

# Check attributes
print(f"\n✓ AllocationResult created successfully")
print(f"  - success: {result.success}")
print(f"  - error: {result.error}")
print(f"  - recommendation: {result.recommendation}")
print(f"  - context: {result.context}")

# Verify error attribute exists
assert hasattr(result, 'error'), "AllocationResult should have 'error' attribute"
print(f"\n✓ AllocationResult has 'error' attribute")

# Verify error_message does NOT exist
assert not hasattr(result, 'error_message'), "AllocationResult should NOT have 'error_message' attribute"
print(f"✓ AllocationResult does NOT have 'error_message' attribute")

# Test to_dict method
error_dict = result.to_dict()
print(f"\n✓ to_dict() method works")
print(f"  Error dict: {error_dict}")

# Verify dict structure
assert "error" in error_dict, "Error dict should have 'error' key"
assert "recommendation" in error_dict, "Error dict should have 'recommendation' key"
assert "context" in error_dict, "Error dict should have 'context' key"

print(f"\n✓ All checks passed!")
print("\n" + "=" * 70)
print("VERIFICATION COMPLETE")
print("=" * 70)
print("\nThe AllocationResult dataclass is correctly defined.")
print("If you're still getting 'error_message' errors, please:")
print("  1. Restart the uvicorn server")
print("  2. Clear browser cache")
print("  3. Check for any running Python processes with old code")
