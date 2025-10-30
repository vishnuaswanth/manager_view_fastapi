#!/usr/bin/env python3
"""
Standalone test script to verify ResourceAllocator debug logging.
Run this to see all the debug output and verify the allocation logic is working correctly.

Usage:
    python test_allocation_debug.py
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Now import from code.logics
from code.logics.allocation import test_allocation_debug

if __name__ == "__main__":
    print("\n" + "="*100)
    print("ALLOCATION DEBUG TEST - VERIFY STATE EXPANSION, PLATFORM NORMALIZATION, CASE-INSENSITIVE MATCHING")
    print("="*100)

    test_allocation_debug()

    print("\n\nExpected Debug Output:")
    print("-" * 100)
    print("✓ Valid states from demand: ['CA', 'MI', 'N/A', 'TX']")
    print("✓ State expansion: 3 → 5 records  (MI NE → MI, NE; ar CA → AR, CA; TX → TX)")
    print("✓ Unique platforms (normalized): ['AMISYS', 'FACETS']  (case-insensitive)")
    print("✓ Sample ParsedSkills showing matched worktypes")
    print("✓ ALLOCATE REQUEST showing platform/state/month normalization")
    print("✓ Allocation results showing FTEs allocated/shortage")
    print("-" * 100)
