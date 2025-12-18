# Bench Allocator Refactoring Plan

## Overview

Refactor `code/logics/bench_allocation.py` to use a class-based approach similar to `ResourceAllocator` from `allocation.py`.

## Goals

1. **Class Structure**: Create `BenchAllocator` class similar to `ResourceAllocator`
2. **Initialization**: Reuse initialization pattern from `ResourceAllocator`
3. **Report Scope**: Only generate/update `roster_allotment` and `bucket_after_allocation` reports
4. **Data Retrieval**: Fetch base reports using `execution_id` parameter
5. **Data Normalization**: Normalize forecast data (pivot Month1-Month6 to individual rows)
6. **Bucket Creation**: Build buckets from filtered vendor df and normalized forecast data
7. **Allocation Methods**: Two separate methods for gap filling and surplus distribution
8. **Output Format**: Keep existing Excel export format

---

## Current Problems

### 1. Procedural Design
- Functions are scattered, making flow hard to follow
- No centralized state management
- Difficult to test individual components

### 2. Month Mapping Bug
- Uses hardcoded date math instead of `ForecastMonthsModel`
- Assumes Month1 = report_month (WRONG: Month1 = report_month + 1)

### 3. Data Loading Issues
- No clear separation between data loading and allocation logic
- Reports are fetched but not efficiently structured

### 4. Lack of Type Safety
- Returns complex nested dicts
- No IDE autocomplete or type checking

---

## Proposed Architecture

### Class Structure

```python
class BenchAllocator:
    """
    Bench resource allocation system for allocating unallocated (bench) vendors.

    Features:
    - Initializes from existing allocation execution (via execution_id)
    - Uses normalized forecast data (pivoted from Month1-Month6)
    - Pre-computes vendor buckets with state compatibility
    - Two-phase allocation: gap filling → surplus distribution
    - Updates roster_allotment and bucket_after_allocation reports
    """

    def __init__(
        self,
        execution_id: str,
        month: str,
        year: int,
        core_utils: CoreUtils
    ):
        """
        Initialize BenchAllocator from existing allocation execution.

        Args:
            execution_id: UUID from AllocationExecutionModel
            month: Report month (e.g., "March")
            year: Report year (e.g., 2025)
            core_utils: CoreUtils instance for DB access
        """
        # Store core parameters
        self.execution_id = execution_id
        self.month = month
        self.year = year
        self.core_utils = core_utils

        # Initialize data structures
        self.vendors: List[VendorData] = []
        self.valid_states: set = set()
        self.forecast_df: pd.DataFrame = None
        self.worktype_vocab: List[str] = []
        self.buckets: Dict[BucketKey, BucketData] = {}

        # Allocation tracking
        self.allocation_history: List[AllocationData] = []

        # Load data and initialize
        self._load_unallocated_vendors()
        self._load_and_normalize_forecast_data()
        self._build_worktype_vocabulary()
        self._initialize_buckets()

        # Store initial state for reporting
        self.initial_state = self._snapshot_state()

        logger.info(f"Initialized BenchAllocator for {month} {year} (execution: {execution_id})")
        logger.info(f"  - Vendors: {len(self.vendors)}")
        logger.info(f"  - Buckets: {len(self.buckets)}")

    def _load_unallocated_vendors(self):
        """Load unallocated vendors from roster_allotment report."""
        self.vendors, self.valid_states = get_unallocated_vendors_with_states(
            self.execution_id,
            self.month,
            self.year,
            self.core_utils
        )
        logger.info(f"Loaded {len(self.vendors)} unallocated vendors")
        logger.info(f"Valid states: {sorted(self.valid_states)}")

    def _load_and_normalize_forecast_data(self):
        """Load ForecastModel and normalize Month1-Month6 to individual rows."""
        self.forecast_df = normalize_forecast_data(
            self.month,
            self.year,
            self.core_utils
        )
        logger.info(f"Loaded {len(self.forecast_df)} normalized forecast rows")

    def _build_worktype_vocabulary(self):
        """Extract unique worktypes from forecast, sorted longest-first."""
        self.worktype_vocab = build_worktype_vocabulary(self.forecast_df)
        logger.info(f"Built vocabulary with {len(self.worktype_vocab)} worktypes")
        logger.info(f"Sample: {self.worktype_vocab[:5]}")

    def _initialize_buckets(self):
        """
        Pre-compute vendor buckets grouped by (platform, location, month, skillset).

        Reuses logic from ResourceAllocator._initialize_buckets but for bench vendors.
        """
        self.buckets = group_into_buckets(
            self.vendors,
            self.forecast_df,
            self.worktype_vocab
        )
        logger.info(f"Initialized {len(self.buckets)} buckets")

    def _snapshot_state(self) -> dict:
        """Create deep copy of current bucket state for reporting."""
        import copy
        return copy.deepcopy(self.buckets)

    def allocate_gap_fill(self) -> int:
        """
        Phase 1: Fill gaps where FTE_Avail < FTE_Required.

        Allocates vendors one-by-one to forecast rows with shortages,
        respecting state compatibility.

        Returns:
            Number of vendors allocated during gap filling
        """
        total_allocated = 0

        for bucket_key, bucket_data in self.buckets.items():
            allocations = fill_gaps(bucket_data, bucket_key)

            # Update forecast rows with allocations
            for alloc in allocations:
                alloc.forecast_row.fte_avail += alloc.fte_allocated
                alloc.forecast_row.capacity += self._calculate_capacity_for_fte(
                    alloc.forecast_row,
                    alloc.fte_allocated
                )
                alloc.vendor.allocated = True

            self.allocation_history.extend(allocations)
            total_allocated += len(allocations)

        logger.info(f"Gap filling: allocated {total_allocated} vendors")
        return total_allocated

    def allocate_excess_distribution(self) -> int:
        """
        Phase 2: Distribute surplus vendors to forecast rows proportionally.

        Uses Largest Remainder Method to ensure whole FTEs only.

        Returns:
            Number of vendors allocated during surplus distribution
        """
        total_allocated = 0

        for bucket_key, bucket_data in self.buckets.items():
            allocations = distribute_excess(bucket_data, bucket_key)

            # Update forecast rows with allocations
            for alloc in allocations:
                alloc.forecast_row.fte_avail += alloc.fte_allocated
                alloc.forecast_row.capacity += self._calculate_capacity_for_fte(
                    alloc.forecast_row,
                    alloc.fte_allocated
                )
                alloc.vendor.allocated = True

            self.allocation_history.extend(allocations)
            total_allocated += len(allocations)

        logger.info(f"Excess distribution: allocated {total_allocated} vendors")
        return total_allocated

    def _calculate_capacity_for_fte(
        self,
        forecast_row: ForecastRowDict,
        fte_count: int
    ) -> int:
        """
        Calculate capacity for given FTE count using month configuration.

        Reuses Calculations.calculate_capacity_from_fte() from allocation.py
        """
        from code.logics.allocation import Calculations

        # Get month config for this row
        parsed = parse_main_lob(forecast_row.main_lob)
        locality = normalize_locality(parsed['locality'])

        config = get_specific_config(
            forecast_row.month_name,
            forecast_row.month_year,
            locality
        )

        return Calculations.calculate_capacity_from_fte(
            fte_count,
            config,
            forecast_row.target_cph
        )

    def update_reports(self):
        """
        Update roster_allotment and bucket_after_allocation reports in database.

        Fetches existing reports, applies allocation changes, and saves back.
        """
        # Update roster_allotment report
        self._update_roster_allotment_report()

        # Update bucket_after_allocation report
        self._update_bucket_after_allocation_report()

        logger.info("Updated reports in database")

    def _update_roster_allotment_report(self):
        """Update roster_allotment report with bench allocations."""
        import json

        # Fetch existing report
        db_manager = self.core_utils.get_db_manager(
            AllocationReportsModel,
            limit=None,
            skip=0
        )

        with db_manager.SessionLocal() as session:
            report = session.query(AllocationReportsModel).filter(
                AllocationReportsModel.execution_id == self.execution_id,
                AllocationReportsModel.ReportType == 'roster_allotment'
            ).first()

            if not report:
                raise ValueError(f"roster_allotment report not found for {self.execution_id}")

            # Parse existing report data
            report_data = json.loads(report.ReportData)
            report_df = pd.DataFrame(report_data)

            # Update vendor status based on allocations
            for alloc in self.allocation_history:
                vendor_cn = alloc.vendor.cn
                month_col = f"{alloc.forecast_row.month_name} {alloc.forecast_row.month_year}"

                # Find vendor row
                mask = report_df['CN'] == vendor_cn
                if mask.any():
                    # Update month column with allocation details
                    report_df.loc[mask, month_col] = (
                        f"{alloc.forecast_row.main_lob} | "
                        f"{alloc.forecast_row.state} | "
                        f"{alloc.forecast_row.case_type}"
                    )
                    # Update status
                    report_df.loc[mask, 'Status'] = 'Allocated (Bench)'

            # Save updated report back to database
            report.ReportData = report_df.to_json(orient='records')
            session.commit()

    def _update_bucket_after_allocation_report(self):
        """Update bucket_after_allocation report with bench allocations."""
        import json

        # Generate new bucket_after_allocation data
        bucket_df = self.generate_buckets_after_allocation()

        # Update in database
        db_manager = self.core_utils.get_db_manager(
            AllocationReportsModel,
            limit=None,
            skip=0
        )

        with db_manager.SessionLocal() as session:
            report = session.query(AllocationReportsModel).filter(
                AllocationReportsModel.execution_id == self.execution_id,
                AllocationReportsModel.ReportType == 'bucket_after_allocation'
            ).first()

            if not report:
                # Create new report if it doesn't exist
                report = AllocationReportsModel(
                    execution_id=self.execution_id,
                    ReportType='bucket_after_allocation',
                    ReportData=bucket_df.to_json(orient='records'),
                    GeneratedDateTime=datetime.now()
                )
                session.add(report)
            else:
                # Update existing report
                report.ReportData = bucket_df.to_json(orient='records')
                report.GeneratedDateTime = datetime.now()

            session.commit()

    def generate_buckets_after_allocation(self) -> pd.DataFrame:
        """
        Generate bucket allocation data (reuses ResourceAllocator logic).

        Returns:
            DataFrame showing allocated vs unallocated vendors per bucket
        """
        allocation_data = []

        for (platform, location, month, skillset), bucket_data in sorted(self.buckets.items()):
            skills_str = ' + '.join(sorted(skillset))

            # Count allocated vs unallocated
            allocated_count = sum(1 for v in bucket_data.vendors if v.allocated)
            unallocated_count = sum(1 for v in bucket_data.vendors if not v.allocated)

            # Get states
            allocated_states = set()
            unallocated_states = set()
            for v in bucket_data.vendors:
                if v.allocated:
                    allocated_states.update(v.state_list)
                else:
                    unallocated_states.update(v.state_list)

            allocation_data.append({
                'Platform': platform,
                'Location': location,
                'Month': month,
                'Skills': skills_str,
                'Skill_Count': len(skillset),
                'Total_Vendors': len(bucket_data.vendors),
                'Allocated': allocated_count,
                'Unallocated': unallocated_count,
                'Allocation_Rate': f"{allocated_count}/{len(bucket_data.vendors)}",
                'Allocated_States': ', '.join(sorted(allocated_states)) if allocated_states else '-',
                'Unallocated_States': ', '.join(sorted(unallocated_states)) if unallocated_states else '-'
            })

        return pd.DataFrame(allocation_data)

    def export_to_excel(self, output_path: str = None) -> str:
        """
        Export bench allocation results to Excel (4 sheets).

        Uses existing create_changes_workbook() from bench_allocation_export.py

        Returns:
            Path to created Excel file
        """
        from code.logics.bench_allocation_export import create_changes_workbook

        # Prepare data for export
        changes = self._prepare_changes_data()
        summary = self._prepare_summary_data()
        modified_forecast = self._prepare_modified_forecast_data()
        vendor_assignments = self._prepare_vendor_assignments_data()

        # Create Excel workbook
        if output_path is None:
            output_path = "/tmp"

        filepath = create_changes_workbook(
            changes=changes,
            summary=summary,
            modified_forecast_rows=modified_forecast,
            vendor_assignments=vendor_assignments,
            output_dir=output_path
        )

        logger.info(f"Exported bench allocation to: {filepath}")
        return filepath

    def _prepare_changes_data(self) -> List[Dict]:
        """Prepare changes data for Excel export."""
        changes = []

        # Group allocations by forecast row
        forecast_changes = {}
        for alloc in self.allocation_history:
            row_key = (
                alloc.forecast_row.forecast_id,
                alloc.forecast_row.month_index
            )
            if row_key not in forecast_changes:
                forecast_changes[row_key] = {
                    'forecast_row': alloc.forecast_row,
                    'gap_fill_count': 0,
                    'excess_count': 0,
                    'vendors': []
                }

            if alloc.allocation_type == 'gap_fill':
                forecast_changes[row_key]['gap_fill_count'] += 1
            else:
                forecast_changes[row_key]['excess_count'] += 1

            forecast_changes[row_key]['vendors'].append(alloc.vendor)

        # Create change records
        for row_key, data in forecast_changes.items():
            row = data['forecast_row']
            changes.append({
                'main_lob': row.main_lob,
                'state': row.state,
                'case_type': row.case_type,
                'month': f"{row.month_name} {row.month_year}",
                'fte_before': row.fte_avail_original,
                'fte_after': row.fte_avail,
                'fte_change': row.fte_avail - row.fte_avail_original,
                'capacity_before': row.capacity_original,
                'capacity_after': row.capacity,
                'capacity_change': row.capacity - row.capacity_original,
                'gap_fill_count': data['gap_fill_count'],
                'excess_count': data['excess_count'],
                'vendor_count': len(data['vendors'])
            })

        return changes

    def _prepare_summary_data(self) -> Dict:
        """Prepare summary data for Excel export."""
        gap_fill_count = sum(
            1 for a in self.allocation_history
            if a.allocation_type == 'gap_fill'
        )
        excess_count = sum(
            1 for a in self.allocation_history
            if a.allocation_type == 'excess_distribution'
        )

        return {
            'month': self.month,
            'year': self.year,
            'execution_id': self.execution_id,
            'total_bench_allocated': len(self.allocation_history),
            'gaps_filled': gap_fill_count,
            'excess_distributed': excess_count,
            'rows_modified': len(set(
                (a.forecast_row.forecast_id, a.forecast_row.month_index)
                for a in self.allocation_history
            )),
            'unallocated_vendors': sum(
                1 for v in self.vendors if not v.allocated
            )
        }

    def _prepare_modified_forecast_data(self) -> pd.DataFrame:
        """
        Prepare modified forecast data for Excel export.

        Returns forecast in download format (Month1-Month6 columns).
        """
        # Group by forecast_id
        forecast_updates = {}
        for alloc in self.allocation_history:
            fid = alloc.forecast_row.forecast_id
            month_idx = alloc.forecast_row.month_index

            if fid not in forecast_updates:
                forecast_updates[fid] = {}

            if month_idx not in forecast_updates[fid]:
                forecast_updates[fid][month_idx] = {
                    'fte_change': 0,
                    'capacity_change': 0
                }

            forecast_updates[fid][month_idx]['fte_change'] += alloc.fte_allocated
            forecast_updates[fid][month_idx]['capacity_change'] += (
                alloc.forecast_row.capacity - alloc.forecast_row.capacity_original
            )

        # Fetch original forecast records and apply changes
        db_manager = self.core_utils.get_db_manager(ForecastModel, limit=None, skip=0)

        with db_manager.SessionLocal() as session:
            forecast_records = session.query(ForecastModel).filter(
                ForecastModel.Month == self.month,
                ForecastModel.Year == self.year
            ).all()

            records_data = []
            for record in forecast_records:
                record_dict = {
                    'id': record.id,
                    'Main_LOB': record.Centene_Capacity_Plan_Main_LOB,
                    'State': record.Centene_Capacity_Plan_State,
                    'Case_Type': record.Centene_Capacity_Plan_Case_Type,
                    'Target_CPH': record.Centene_Capacity_Plan_Target_CPH
                }

                # Add Month1-Month6 columns with updates
                for month_idx in range(1, 7):
                    fte_orig = getattr(record, f'FTE_Avail_Month{month_idx}', 0) or 0
                    cap_orig = getattr(record, f'Capacity_Month{month_idx}', 0) or 0

                    # Apply changes if this forecast_id has updates
                    if record.id in forecast_updates and month_idx in forecast_updates[record.id]:
                        fte_change = forecast_updates[record.id][month_idx]['fte_change']
                        cap_change = forecast_updates[record.id][month_idx]['capacity_change']
                    else:
                        fte_change = 0
                        cap_change = 0

                    record_dict[f'FTE_Avail_Month{month_idx}'] = fte_orig + fte_change
                    record_dict[f'Capacity_Month{month_idx}'] = cap_orig + cap_change

                records_data.append(record_dict)

        return pd.DataFrame(records_data)

    def _prepare_vendor_assignments_data(self) -> List[Dict]:
        """Prepare vendor assignments data for Excel export."""
        assignments = []

        for alloc in self.allocation_history:
            assignments.append({
                'FirstName': alloc.vendor.first_name,
                'LastName': alloc.vendor.last_name,
                'CN': alloc.vendor.cn,
                'Platform': alloc.vendor.platform,
                'Location': alloc.vendor.location,
                'Skills': alloc.vendor.skills,
                'State': alloc.vendor.original_state,
                'Allocated_To_LOB': alloc.forecast_row.main_lob,
                'Allocated_To_State': alloc.forecast_row.state,
                'Allocated_To_CaseType': alloc.forecast_row.case_type,
                'Month': f"{alloc.forecast_row.month_name} {alloc.forecast_row.month_year}",
                'Allocation_Type': alloc.allocation_type,
                'FTE_Count': alloc.fte_allocated
            })

        return assignments
```

---

## Public API

### Main Entry Point

```python
def allocate_bench_for_month(
    execution_id: str,
    month: str,
    year: int,
    core_utils: CoreUtils = None,
    export_excel: bool = True,
    output_dir: str = "/tmp"
) -> AllocationResult:
    """
    Allocate bench (unallocated) vendors for a given month/year.

    Args:
        execution_id: UUID from AllocationExecutionModel
        month: Report month name (e.g., "March")
        year: Report year (e.g., 2025)
        core_utils: CoreUtils instance (creates if None)
        export_excel: Whether to export results to Excel
        output_dir: Directory for Excel export

    Returns:
        AllocationResult dataclass with:
        - success: bool
        - month: str
        - year: int
        - total_bench_allocated: int
        - gaps_filled: int
        - excess_distributed: int
        - rows_modified: int
        - allocations: List[AllocationRecord]
        - error: str (only if success=False)

    Example:
        >>> result = allocate_bench_for_month(
        ...     execution_id="550e8400-e29b-41d4-a716-446655440000",
        ...     month="March",
        ...     year=2025
        ... )
        >>> print(f"Allocated {result.total_bench_allocated} bench vendors")
        >>> print(f"Gaps filled: {result.gaps_filled}")
        >>> print(f"Excess distributed: {result.excess_distributed}")
    """
    try:
        # Initialize core_utils if not provided
        if core_utils is None:
            from code.settings import MODE, SQLITE_DATABASE_URL, MSSQL_DATABASE_URL
            if MODE.upper() == "DEBUG":
                database_url = SQLITE_DATABASE_URL
            else:
                database_url = MSSQL_DATABASE_URL
            core_utils = CoreUtils(database_url)

        # Create allocator
        allocator = BenchAllocator(
            execution_id=execution_id,
            month=month,
            year=year,
            core_utils=core_utils
        )

        # Phase 1: Fill gaps
        gaps_filled = allocator.allocate_gap_fill()

        # Phase 2: Distribute excess
        excess_distributed = allocator.allocate_excess_distribution()

        # Update database reports
        allocator.update_reports()

        # Export to Excel
        excel_path = None
        if export_excel:
            excel_path = allocator.export_to_excel(output_dir)

        # Prepare result
        allocations = _convert_history_to_allocation_records(
            allocator.allocation_history
        )

        result = AllocationResult(
            success=True,
            month=month,
            year=year,
            total_bench_allocated=len(allocator.allocation_history),
            gaps_filled=gaps_filled,
            excess_distributed=excess_distributed,
            rows_modified=len(set(
                (a.forecast_row.forecast_id, a.forecast_row.month_index)
                for a in allocator.allocation_history
            )),
            allocations=allocations,
            excel_path=excel_path
        )

        logger.info(f"Bench allocation completed: {result.total_bench_allocated} vendors allocated")
        return result

    except Exception as e:
        logger.error(f"Bench allocation failed: {e}", exc_info=True)
        return AllocationResult(
            success=False,
            month=month,
            year=year,
            total_bench_allocated=0,
            gaps_filled=0,
            excess_distributed=0,
            rows_modified=0,
            allocations=[],
            error=str(e)
        )
```

---

## Implementation Steps

### Phase 1: Data Structures (Already Done)
- ✅ `VendorData` dataclass
- ✅ `ForecastRowDict` dataclass
- ✅ `AllocationData` dataclass
- ✅ `BucketData` dataclass
- ✅ `AllocationResult` dataclass
- ✅ `BucketKey` type alias

### Phase 2: Helper Functions (Partially Done)
- ✅ `get_unallocated_vendors_with_states()` - Already implemented
- ✅ `normalize_forecast_data()` - Already implemented
- ✅ `build_worktype_vocabulary()` - Already implemented
- ✅ `parse_vendor_skills()` - Already implemented
- ✅ `group_into_buckets()` - Already implemented
- ⚠️ `fill_gaps()` - Needs review/completion
- ⚠️ `distribute_excess()` - Needs implementation

### Phase 3: BenchAllocator Class
- ❌ Create class with `__init__`
- ❌ Implement `_load_unallocated_vendors()`
- ❌ Implement `_load_and_normalize_forecast_data()`
- ❌ Implement `_build_worktype_vocabulary()`
- ❌ Implement `_initialize_buckets()`
- ❌ Implement `allocate_gap_fill()`
- ❌ Implement `allocate_excess_distribution()`
- ❌ Implement `_calculate_capacity_for_fte()`
- ❌ Implement `update_reports()`
- ❌ Implement `_update_roster_allotment_report()`
- ❌ Implement `_update_bucket_after_allocation_report()`
- ❌ Implement `generate_buckets_after_allocation()`
- ❌ Implement `export_to_excel()`
- ❌ Implement helper methods for Excel export prep

### Phase 4: Public API
- ❌ Update `allocate_bench_for_month()` to use `BenchAllocator` class
- ❌ Ensure backward compatibility with existing callers

### Phase 5: Testing
- ❌ Update `test_bench_allocation_comprehensive.py` to use new API
- ❌ Test gap filling logic
- ❌ Test excess distribution logic
- ❌ Test report updates
- ❌ Test Excel export

---

## Benefits of This Design

### 1. **Clear Separation of Concerns**
- Data loading: `__init__` and `_load_*` methods
- Bucket creation: `_initialize_buckets()`
- Allocation: `allocate_gap_fill()`, `allocate_excess_distribution()`
- Reporting: `update_reports()`, `export_to_excel()`

### 2. **Type Safety**
- Dataclasses provide IDE autocomplete
- Type hints catch errors at development time
- No more complex nested dicts

### 3. **Testability**
- Each method can be tested independently
- Easy to mock data loading
- Clear state management

### 4. **Reusability**
- Bucket logic reused from `ResourceAllocator`
- Vocabulary building reused
- Skill parsing reused

### 5. **Maintainability**
- Similar structure to `ResourceAllocator` (easier to understand)
- Clear data flow: load → bucket → allocate → report
- Centralized state in class instance

### 6. **Future-Proofing**
- Uses `ForecastMonthsModel` for month mappings (no hardcoded logic)
- Easy to extend with new allocation strategies
- Clear extension points for additional reports

---

## Critical Fix: Year Calculation & Month Config Validation

### Year Calculation Logic (FIXED)

**ForecastMonthsModel** only contains month names (Month1-Month6), not years. We must calculate the year based on the report month:

**Rule**: If `report_month_num > forecast_month_num` → `year = report_year + 1`, else `year = report_year`

**Examples**:

**Example 1: March 2025 Report**
- Report: March 2025 (month_num = 3)
- Month1 = April (month_num = 4): 3 > 4? No → 2025
- Month2 = May (month_num = 5): 3 > 5? No → 2025
- Month3 = June (month_num = 6): 3 > 6? No → 2025
- ...all months are 2025 (no wrapping)

**Example 2: October 2024 Report**
- Report: October 2024 (month_num = 10)
- Month1 = November (month_num = 11): 10 > 11? No → 2024
- Month2 = December (month_num = 12): 10 > 12? No → 2024
- Month3 = January (month_num = 1): 10 > 1? **Yes** → **2025** ✓
- Month4 = February (month_num = 2): 10 > 2? **Yes** → **2025** ✓
- Month5 = March (month_num = 3): 10 > 3? **Yes** → **2025** ✓
- Month6 = April (month_num = 4): 10 > 4? **Yes** → **2025** ✓

### Updated Function

```python
def get_month_mappings_from_db(
    core_utils: CoreUtils,
    uploaded_file: str,
    report_month: str,
    report_year: int
) -> Dict[int, MonthData]:
    """
    Get month mappings from ForecastMonthsModel with correct year calculation.

    Args:
        core_utils: CoreUtils instance for database access
        uploaded_file: The UploadedFile name from ForecastModel
        report_month: Report month name (e.g., "March")
        report_year: Report year (e.g., 2025)

    Returns:
        Dict mapping month_index (1-6) to MonthData(month=name, year=year)

    Raises:
        ValueError: If no month mappings found or month config missing
    """
    from code.logics.db import ForecastMonthsModel
    from code.logics.month_config_utils import get_specific_config

    db_manager = core_utils.get_db_manager(ForecastMonthsModel, limit=1, skip=0)

    with db_manager.SessionLocal() as session:
        months_record = session.query(ForecastMonthsModel).filter(
            ForecastMonthsModel.UploadedFile == uploaded_file
        ).first()

        if not months_record:
            raise ValueError(f"No month mappings found for file: {uploaded_file}")

    # Create mapping from month name to month number (1-12)
    month_names = list(cal_month_name)[1:]  # ['January', 'February', ..., 'December']
    month_to_num = {month: idx for idx, month in enumerate(month_names, start=1)}

    # Get report month number
    report_month_num = month_to_num.get(report_month)
    if report_month_num is None:
        raise ValueError(f"Invalid report month: {report_month}")

    # Build mappings from DB data with year calculation
    mappings = {}
    missing_configs = []

    for i in range(1, 7):
        month_name = getattr(months_record, f'Month{i}')

        if month_name not in month_to_num:
            raise ValueError(f"Invalid month name in ForecastMonthsModel.Month{i}: {month_name}")

        forecast_month_num = month_to_num[month_name]

        # CRITICAL: Year wrapping logic
        # If report_month_num > forecast_month_num → wrapped to next year
        if report_month_num > forecast_month_num:
            year = report_year + 1
        else:
            year = report_year

        mappings[i] = MonthData(month=month_name, year=year)

        logger.debug(f"Month{i} → {month_name} {year} (report: {report_month} {report_year}, month_nums: {report_month_num} vs {forecast_month_num})")

        # CRITICAL: Validate month config exists for both Domestic and Global
        # If config missing, collect error but continue to check all months
        try:
            for locality in ['Domestic', 'Global']:
                config = get_specific_config(month_name, year, locality)
                if not config:
                    missing_configs.append(f"{month_name} {year} ({locality})")
        except Exception as e:
            missing_configs.append(f"{month_name} {year}: {e}")

    # If any month configs are missing, STOP the entire process
    if missing_configs:
        error_msg = (
            f"Month configuration missing for forecast months. "
            f"Cannot proceed with bench allocation.\n"
            f"Missing configs: {', '.join(missing_configs)}"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    logger.info(f"✓ All month configurations validated for {report_month} {report_year}")
    return mappings
```

### Month Config Validation

**CRITICAL**: Before any allocation begins, we must validate that month configurations exist for ALL months in the forecast.

**Validation Points**:
1. After calculating month+year mappings in `get_month_mappings_from_db()`
2. Check both Domestic and Global configs exist
3. If ANY config is missing → **STOP entire process with clear error message**

**Error Message Format**:
```
Month configuration missing for forecast months. Cannot proceed with bench allocation.
Missing configs: January 2025 (Domestic), February 2025 (Global), March 2025 (Domestic)
```

## Potential Issues & Deficiencies

### 1. **Excel Export Format**
**Current**: Uses `create_changes_workbook()` from `bench_allocation_export.py`
**Concern**: Need to verify this matches expected format
**Action**: Review existing export logic and ensure compatibility

### 2. **Capacity Calculation**
**Current**: Uses `Calculations.calculate_capacity_from_fte()` from `allocation.py`
**Concern**: Month config must exist for capacity calculation
**Action**: ✅ FIXED - Validation added in `get_month_mappings_from_db()`

### 3. **Report Update Strategy**
**Current**: Updates entire `roster_allotment` report JSON
**Concern**: Potential race conditions if multiple processes update simultaneously
**Action**: Consider adding database-level locking or versioning

### 4. **State Matching Logic**
**Current**: Reuses `parse_vendor_state_list()` from existing code
**Concern**: Need to ensure StateList always includes 'N/A'
**Action**: Add unit tests for state parsing edge cases

### 5. **Vendor Deduplication**
**Current**: Uses `vendor.cn` as unique identifier
**Concern**: What if same vendor appears multiple times in roster?
**Action**: Add deduplication logic in `_load_unallocated_vendors()`

### 6. **Error Handling**
**Current**: Try/except in `allocate_bench_for_month()`
**Concern**: Need specific error types for different failure modes
**Action**: Define custom exceptions (e.g., `NoUnallocatedVendorsError`, `ReportNotFoundError`)

---

## Suggested Improvements

### 1. **Add Validation Layer**
```python
def _validate_initialization(self):
    """Validate that all required data is loaded."""
    if not self.vendors:
        logger.warning("No unallocated vendors found - nothing to allocate")

    if self.forecast_df.empty:
        raise ValueError("No forecast data found")

    if not self.worktype_vocab:
        raise ValueError("No worktype vocabulary found")

    if not self.buckets:
        logger.warning("No buckets created - no matching vendors/forecasts")
```

### 2. **Add Progress Callbacks**
```python
def allocate_gap_fill(self, progress_callback=None) -> int:
    """
    Phase 1: Fill gaps with optional progress reporting.

    Args:
        progress_callback: Optional callable(current, total) for progress updates
    """
    total_buckets = len(self.buckets)

    for idx, (bucket_key, bucket_data) in enumerate(self.buckets.items()):
        allocations = fill_gaps(bucket_data, bucket_key)
        # ... allocation logic ...

        if progress_callback:
            progress_callback(idx + 1, total_buckets)
```

### 3. **Add Dry-Run Mode**
```python
def __init__(
    self,
    execution_id: str,
    month: str,
    year: int,
    core_utils: CoreUtils,
    dry_run: bool = False  # NEW
):
    """
    Args:
        dry_run: If True, don't update database reports
    """
    self.dry_run = dry_run
    # ...

def update_reports(self):
    """Update reports (skip if dry_run=True)."""
    if self.dry_run:
        logger.info("DRY RUN: Skipping report updates")
        return

    # ... normal update logic ...
```

### 4. **Add Allocation Statistics**
```python
def get_allocation_statistics(self) -> Dict:
    """
    Get detailed allocation statistics.

    Returns:
        Dict with statistics by allocation_type, bucket, state, etc.
    """
    stats = {
        'by_type': {},
        'by_bucket': {},
        'by_state': {},
        'by_month': {}
    }

    for alloc in self.allocation_history:
        # Aggregate statistics...
        pass

    return stats
```

---

## Next Steps

1. **Review & Approve**: Get feedback on this design
2. **Implement Phase 3**: Create `BenchAllocator` class
3. **Update Tests**: Modify `test_bench_allocation_comprehensive.py`
4. **Validate Excel Export**: Ensure output format matches expectations
5. **Integration Testing**: Test with real execution_id from database
6. **Documentation**: Update CLAUDE.md with new class structure
