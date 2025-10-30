import sys
import os
import re
import copy
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from datetime import datetime
import numpy as np
from typing import List
import logging

from code .logics.core_utils import PreProcessing
from code.logics.export_utils import (
    get_latest_or_requested_dataframe,
    update_forecast_data,
    get_forecast_months_list,
    get_all_model_dataframes_dict,
    get_calculations_data
)

from code.logics.summary_utils import update_summary_data
import pandas as pd
from code.settings import BASE_DIR

logger = logging.getLogger(__name__)

pd.set_option('future.no_silent_downcasting', True)

# Set current path
curpth = os.path.join(BASE_DIR, 'logics')

# Input and output file paths
input_files = {
    'skilling': os.path.join(curpth, "data","Input", "Centene Modified Roster-2.xlsm"),
    'target': os.path.join(curpth, "data",'constants','calculations.xlsx'),
    'vendor_template': os.path.join(curpth, "data","Input", "NTT_Capacity Roster Template.xlsx"),
    # No longer needed with ResourceAllocator:
    # 'combinations': os.path.join(curpth, "data",'constants',"combinations_2.xlsx")
}
output_file = os.path.join(curpth, "result.xlsx")

# Legacy code - combinations no longer needed with ResourceAllocator
# try:
#     combinations_df = pd.read_excel(input_files['combinations'])
# except Exception as e:
#     logger.error(f"Failed to load input files: {e}")
#     sys.exit(1)

# Load variables and months
req_vars_df = pd.read_excel(input_files['target'], sheet_name="Sheet1")
# req_months_df = pd.read_excel(input_files['target'], sheet_name="Sheet2")
occupancy = req_vars_df['Occupancy'].iloc[0]
shrinkage = req_vars_df['Shrinkage'].iloc[0]
workhours = req_vars_df['Work hours'].iloc[0]
# month_headers = req_months_df['Months'].tolist()
month_with_days = dict(zip(req_vars_df['months'], req_vars_df['No.of days occupancy']))

# Legacy code - no longer needed with ResourceAllocator
# combination_list = [eval(x) for x in combinations_df['combination'] if 'nan' not in x]
# state_with_worktype_volume_dict = {}

# Helper functions
def get_value(row, month, filetype, df:pd.DataFrame=None, unnamed_count=None):
    if df is None or getattr(df, 'empty', True):
        return 0

    file_name = row[('Centene Capacity plan', 'Main LOB')]
    state = row[('Centene Capacity plan', 'State')]
    work_type = row[('Centene Capacity plan', 'Case type')]
    # file_paths = {
    #     'nonmmp': os.path.join(curpth, "data", 'constants',"medicare_medicaid_nonmmp", f"{file_name}.xlsx"),
    #     'mmp': os.path.join(curpth, "data", 'constants',"medicare_medicaid_mmp", f"{file_name}.xlsx"),
    #     'summary': os.path.join(curpth, "data", 'constants',"medicare_medicaid_summary", f"{file_name}-summary.xlsx")
    # }
    try:
        if filetype == 'medicare_medicaid_nonmmp':
            # df = pd.read_excel(file_paths['nonmmp'], header=[0, 1, 2])
            # df.columns = df.columns.map(lambda x: tuple(i if 'Unnamed' not in str(i) else '' for i in x))
            filtered_df = df[(df[('', '', 'State')] == state) & (df[('', '', 'Month')] == month)]
            if not filtered_df.empty:
                for col in filtered_df.columns:
                    if "WFM TO PROVIDE" in col[0].upper() and work_type in col:
                        return filtered_df[col].values[0]
            return 0
        elif filetype == 'medicare_medicaid_mmp':
            # df = pd.read_excel(file_paths['mmp'], header=[0, 1])
            filtered_df = df[(df[('State', 'State')] == state) & (df[('Month', 'Month')] == month)]
            if not filtered_df.empty:
                for col in filtered_df.columns:
                    if work_type == col[0]:
                        return filtered_df[col].values[0]
            return 0
        elif filetype == 'medicare_medicaid_summary':
            # df = pd.read_excel(file_paths['summary'], header=[0, 1, 2, 3])
            # df.columns = df.columns.map(lambda x: tuple(datetime.strptime(i, "%Y-%m-%d %H:%M:%S").strftime('%B') if ":" in i and "unnamed" not in i.lower() else i for i in x))
            filtered_df = df[df[(file_name, "Vendor Eligible Forecast (WFM)", "Work Type", "")] == work_type]
            if not filtered_df.empty:
                return filtered_df[(file_name, "Vendor Eligible Forecast (WFM)", month, "")].values[0]
            return 0
    except KeyError as e:
        logging.warning(f"Missing month column '{month}' in get_value for {file_name}, {filetype}, returning 0")
        return 0
    except Exception as e:
        logging.warning(f"Error in get_value for {file_name}, {filetype}, {month}: {e}")
        return 0

class Calculations():
    def __init__(self) -> None:
        self.target_cph: pd.DataFrame = pd.DataFrame()
        self.month_data: pd.DataFrame = pd.DataFrame()
        self.occupancy: float
        self.shrinkage: float
        self.workhours: int
        self.month_with_days:dict[str, int]

        calculations = get_calculations_data()
        self.month_data = calculations.get("month_data", pd.DataFrame)
        self.target_cph = calculations.get("target_cph", pd.DataFrame)

        self.occupancy = self.month_data['Occupancy'].iloc[0] if not self.month_data.empty else 0.0
        self.shrinkage = self.month_data['Shrinkage'].iloc[0] if not self.month_data.empty else 0.0
        self.workhours = self.month_data['Work hours'].iloc[0] if not self.month_data.empty else 0


        # occupancy = req_vars_df['Occupancy'].iloc[0]
        # shrinkage = req_vars_df['Shrinkage'].iloc[0]
        # workhours = req_vars_df['Work hours'].iloc[0]
        # # month_headers = req_months_df['Months'].tolist()
        # month_with_days = dict(zip(req_vars_df['months'], req_vars_df['No.of days occupancy']))
        if not self.month_data.empty and 'months' in self.month_data.columns and 'No.of days occupancy' in self.month_data.columns:
            self.month_with_days = dict(zip(self.month_data['months'], self.month_data['No.of days occupancy']))
        else:
            self.month_with_days = {}


    def get_target_cph(self, row):
        lob = row[('Centene Capacity plan', 'Main LOB')]
        worktype = row[('Centene Capacity plan', 'Case type')]
        logger.debug(f"~~ ENTER get_target_cph: lob={lob!r}, worktype={worktype!r}")
        target_df = self.target_cph
        # filtered_target_df = self.target_cph[(self.target_cph['Case type'].str.lower() == worktype.lower()) & (self.target_cph['Main LOB'].str.strip() == lob.strip())]
        filtered_target_df = target_df[
            (target_df['Main LOB'].str.strip().str.lower() == lob.strip().lower()) &
            (target_df['Case type'].str.strip().str.lower() == worktype.strip().lower())
        ]
        # logger.debug(f"filtered target df head - {filtered_target_df.head()}")
        return filtered_target_df['Target CPH'].iloc[0] if not filtered_target_df.empty else 0



# def get_target_cph(row):
#     lob = row[('Centene Capacity plan', 'Main LOB')]
#     worktype = row[('Centene Capacity plan', 'Case type')]
#     logger.debug(f"~~ ENTER get_target_cph: lob={lob!r}, worktype={worktype!r}")
#     filtered_target_df = target_df[(target_df['Case type'].str.lower() == worktype.lower()) & (target_df['Main LOB'].str.strip() == lob.strip())]
#     return filtered_target_df['Target CPH'].iloc[0] if not filtered_target_df.empty else 0

def get_fte_required(row, month, calculations: Calculations):
    try:
        target_cph = row[('Centene Capacity plan', 'Target CPH')]
        month_value = row[('Client Forecast', month)]
        no_of_days = calculations.month_with_days.get(month, 0)

        if target_cph == 0 or no_of_days == 0:
            return 0

        return month_value / (target_cph * calculations.workhours * calculations.occupancy * (1 - calculations.shrinkage) * no_of_days)
    except (KeyError, TypeError, ValueError):
        logging.warning(f"Missing month data for {month} in get_fte_required, returning 0")
        return 0

def get_temp_casetype(casetype):
    casetype = str(casetype)
    if not casetype or casetype == 'nan':
        return ''
    ct = casetype.split("-")[0].lower()
    return {'app': 'appeal', 'omn': 'omni'}.get(ct, ct)

# def get_skills_split_count(row, month, df):
#     global state_with_worktype_volume_dict
#     worktype = row[('Centene Capacity plan', 'Case type')]
#     state = row[('Centene Capacity plan', 'State')]
#     fte_required = row[('FTE Required', month)]
#     volume = {}
#     if f"{state}_{month}" not in state_with_worktype_volume_dict:
#         try:
#             df['State'] = df['State'].fillna('')
#             filtered_df = df if state == 'N/A' else df[df['State'].str.contains(state)]
#             work_types = sorted(filtered_df['NewWorkType'].tolist(), key=len, reverse=True)
#             for wt in work_types:
#                 for comb in combination_list:
#                     if len(list(comb)) > 1:
#                         if sorted(" ".join(list(comb))) == sorted(wt.strip()):
#                             volume[comb] = volume.get(comb, 0) + 1
#                     elif comb == (wt,):
#                         volume[comb] = volume.get(comb, 0) + 1
#             if volume:
#                 state_with_worktype_volume_dict[f"{state}_{month}"] = volume
#         except Exception as e:
#             logging.warning(f"Error in get_skills_split_count for {state}_{month}: {e}")
#     try:
#         current_bucket = state_with_worktype_volume_dict[f"{state}_{month}"]
#         available_fte = 0
#         if (worktype,) in current_bucket:
#             if current_bucket[(worktype,)] >= fte_required:
#                 state_with_worktype_volume_dict[f"{state}_{month}"][(worktype,)] -= fte_required
#                 return fte_required
#             else:
#                 available_fte = current_bucket[(worktype,)]
#                 state_with_worktype_volume_dict[f"{state}_{month}"][(worktype,)] = 0
#                 remaining_fte = fte_required - available_fte
#                 for k, v in current_bucket.items():
#                     if remaining_fte == 0:
#                         return fte_required
#                     if len(k) > 1 and worktype in k:
#                         if v > remaining_fte:
#                             available_fte += remaining_fte
#                             state_with_worktype_volume_dict[f"{state}_{month}"][k] -= remaining_fte
#                             remaining_fte = 0
#                         else:
#                             available_fte += v
#                             state_with_worktype_volume_dict[f"{state}_{month}"][k] = 0
#                             remaining_fte -= v
#                 return available_fte
#         else:
#             remaining_fte = fte_required
#             for k, v in current_bucket.items():
#                 if remaining_fte == 0:
#                     return fte_required
#                 if len(k) > 1 and worktype in k:
#                     if v > remaining_fte:
#                         available_fte += remaining_fte
#                         state_with_worktype_volume_dict[f"{state}_{month}"][k] -= remaining_fte
#                         remaining_fte = 0
#                     else:
#                         available_fte += v
#                         state_with_worktype_volume_dict[f"{state}_{month}"][k] = 0
#                         remaining_fte -= v
#             return available_fte
#     except KeyError:
#         return 0

# Legacy allocation function - replaced by ResourceAllocator class
# def get_skills_split_count(row, month, df):
#     global state_with_worktype_volume_dict
#     try:
#         platform = row[('Centene Capacity plan', 'Main LOB')]
#         platform= str(platform).split(" ")[0]
#         worktype = row[('Centene Capacity plan', 'Case type')]
#         state = row[('Centene Capacity plan', 'State')]
#         fte_required = row[('FTE Required', month)]
#     except KeyError as e:
#         logging.warning(f"Missing month column '{month}' in get_skills_split_count, returning 0")
#         return 0
#
#     # ... rest of legacy implementation
#     # Now handled by ResourceAllocator.allocate()
#     return 0


class ResourceAllocator:
    """
    Fast resource allocation system using vocabulary-driven exact matching.

    Features:
    - Pre-computes all resource buckets upfront (O(n) initialization)
    - Uses vocabulary from demand to parse vendor skills
    - Greedy longest-match-first algorithm prevents substring issues
    - Handles multi-skilled vendors with priority: single-skill → multi-skill
    - Tracks allocation history for comprehensive reporting
    """

    def __init__(self, vendor_df: pd.DataFrame, output_df: pd.DataFrame, month_headers: List[str]):
        """
        Initialize allocator with pre-computed buckets.

        Args:
            vendor_df: DataFrame with vendor resources (must have PrimaryPlatform, State, NewWorkType)
            output_df: DataFrame with demand (must have worktype column)
            month_headers: List of month names for allocation
        """
        self.month_headers = month_headers
        self.allocation_history = []

        # Build vocabulary from demand (sorted longest-first)
        self.worktype_vocab = self._build_vocabulary(output_df)
        logger.info(f"Built vocabulary with {len(self.worktype_vocab)} unique worktypes")

        # Pre-compile regex for performance
        self.whitespace_pattern = re.compile(r'\s+')

        # Parse vendors and build buckets
        self.buckets = self._initialize_buckets(vendor_df)

        # Store initial state for reporting
        self.initial_state = self._snapshot_state()
        logger.info(f"Initialized allocator with {sum(sum(b.values()) for b in self.buckets.values())} total resources across {len(self.buckets)} location-month combinations")

    def _build_vocabulary(self, output_df: pd.DataFrame) -> List[str]:
        """
        Extract unique worktypes from demand DataFrame, sorted by length (longest first).

        Critical: Longest strings MUST be checked first to avoid substring matching issues.
        Example: "FTC-Basic/Non MMP" must be checked before "FTC" or "FTC Basic"
        """
        worktypes = output_df[('Centene Capacity plan', 'Case type')].unique()

        # Clean and filter vocabulary
        vocab = {
            str(wt).strip().lower()
            for wt in worktypes
            if wt and str(wt).lower() not in {'nan', 'none', ''}
        }

        # Sort by length DESC (longest first), then alphabetically for deterministic behavior
        return sorted(vocab, key=lambda x: (-len(x), x))

    def _normalize_text(self, text: str) -> str:
        """
        Normalize whitespace: collapse multiple spaces/tabs to single space, strip.

        Example: "FTC  ADJ" → "FTC ADJ"
        """
        if not text or str(text).lower() == 'nan':
            return ''
        # Replace multiple whitespace characters with single space, then strip
        return self.whitespace_pattern.sub(' ', str(text).strip())

    def _parse_vendor_skills(self, newworktype_str: str) -> frozenset:
        """
        Parse vendor NewWorkType by matching against vocabulary using greedy longest-match-first.

        Algorithm:
        1. Normalize whitespace and lowercase
        2. Find longest vocabulary term in remaining text
        3. Add to matched_skills, remove from text, re-normalize
        4. Repeat until no matches found

        Example:
            Input: "FTC-Basic/Non MMP  ADJ-COB NON MMP" (note double space)
            Vocab: ["ftc-basic/non mmp", "adj-cob non mmp", "ftc", "adj", ...]
            Output: frozenset({'ftc-basic/non mmp', 'adj-cob non mmp'})
        """
        if not newworktype_str:
            return frozenset()

        # Step 1: Normalize and lowercase
        text = self._normalize_text(newworktype_str).lower()

        # Step 2: Greedy matching
        matched_skills = []

        while text:
            matched_any = False

            # Check each vocab term (already sorted longest-first)
            for vocab_term in self.worktype_vocab:
                if vocab_term in text:
                    matched_skills.append(vocab_term)
                    # Remove matched term and re-normalize
                    text = text.replace(vocab_term, ' ', 1)
                    text = self._normalize_text(text)
                    matched_any = True
                    break  # Start over from beginning of vocab (longest-first)

            if not matched_any:
                # No more vocabulary matches, stop
                # (remaining text contains only unknown/non-demand skills)
                break

        return frozenset(matched_skills)

    def _initialize_buckets(self, vendor_df: pd.DataFrame) -> dict:
        """
        Pre-compute all resource buckets grouped by (platform, state, month, skillset).

        Returns:
            dict: {(platform, state, month): {frozenset(skills): count}}
        """
        # Parse vendor skills
        vendor_df = vendor_df.copy()
        vendor_df['ParsedSkills'] = vendor_df['NewWorkType'].apply(self._parse_vendor_skills)

        # Filter out vendors with no recognized skills
        vendor_df = vendor_df[vendor_df['ParsedSkills'].apply(len) > 0]

        # Group by platform, state, and parsed skills
        grouped = vendor_df.groupby(['PrimaryPlatform', 'State', 'ParsedSkills']).size()

        # Convert to nested dict structure by month
        buckets = {}
        for (platform, state, skillset), count in grouped.items():
            # Create bucket for each month
            for month in self.month_headers:
                key = (platform, state, month)
                if key not in buckets:
                    buckets[key] = {}
                buckets[key][skillset] = count

        return buckets

    def _snapshot_state(self) -> dict:
        """Create deep copy of current bucket state for reporting."""
        import copy
        return copy.deepcopy(self.buckets)

    def allocate(self, platform: str, state: str, month: str, worktype: str, fte_required: float) -> tuple:
        """
        Allocate resources for a demand request.

        Special case: If state == "N/A", searches across ALL states for the platform/month.

        Priority:
        1. Single-skill exact match (e.g., only "FTC-Basic/Non MMP")
        2. Multi-skill containing the worktype (e.g., "FTC-Basic/Non MMP" + "ADJ")

        Args:
            platform: Platform name (e.g., "Amisys")
            state: State code (e.g., "MI") or "N/A" for any state
            month: Month name (e.g., "March")
            worktype: Exact worktype from demand (e.g., "FTC-Basic/Non MMP")
            fte_required: Number of FTEs needed

        Returns:
            tuple: (allocated_amount, shortage_amount)
        """
        worktype_normalized = self._normalize_text(worktype).lower()
        allocated = 0
        remaining = fte_required

        # Determine which buckets to search
        if state.upper() == "N/A":
            # Search ALL states for this platform and month
            bucket_keys = [
                (plat, st, mon)
                for (plat, st, mon) in self.buckets.keys()
                if plat == platform and mon == month
            ]
        else:
            # Exact state match
            bucket_keys = [(platform, state, month)]

        if not bucket_keys:
            # No resources for this platform-month combination
            self.allocation_history.append({
                'platform': platform,
                'state': state,
                'month': month,
                'worktype': worktype,
                'requested': fte_required,
                'allocated': 0,
                'shortage': fte_required
            })
            return 0, fte_required

        # Priority 1: Single-skill exact match across all relevant buckets
        single_skillset = frozenset({worktype_normalized})
        for key in bucket_keys:
            if remaining <= 0:
                break
            if key in self.buckets:
                bucket = self.buckets[key]
                if single_skillset in bucket and bucket[single_skillset] > 0:
                    take = min(bucket[single_skillset], remaining)
                    bucket[single_skillset] -= take
                    allocated += take
                    remaining -= take

        # Priority 2: Multi-skill containing this worktype
        if remaining > 0:
            for key in bucket_keys:
                if remaining <= 0:
                    break
                if key in self.buckets:
                    bucket = self.buckets[key]
                    for skillset, count in list(bucket.items()):
                        if remaining <= 0:
                            break
                        if len(skillset) > 1 and worktype_normalized in skillset and count > 0:
                            take = min(count, remaining)
                            bucket[skillset] -= take
                            allocated += take
                            remaining -= take

        # Track history
        self.allocation_history.append({
            'platform': platform,
            'state': state,
            'month': month,
            'worktype': worktype,  # Original from demand
            'requested': fte_required,
            'allocated': allocated,
            'shortage': remaining
        })

        return allocated, remaining

    def get_summary_report(self) -> dict:
        """
        Generate summary report with initial/allocated/unutilized FTE counts.

        Returns:
            dict with keys: summary, by_category
        """
        # Calculate totals
        total_initial = sum(sum(skillset_counts.values()) for skillset_counts in self.initial_state.values())
        total_current = sum(sum(skillset_counts.values()) for skillset_counts in self.buckets.values())
        total_allocated = total_initial - total_current

        # Calculate by category
        single_skill_initial = sum(
            count for bucket in self.initial_state.values()
            for skillset, count in bucket.items() if len(skillset) == 1
        )
        single_skill_current = sum(
            count for bucket in self.buckets.values()
            for skillset, count in bucket.items() if len(skillset) == 1
        )
        multi_skill_initial = sum(
            count for bucket in self.initial_state.values()
            for skillset, count in bucket.items() if len(skillset) > 1
        )
        multi_skill_current = sum(
            count for bucket in self.buckets.values()
            for skillset, count in bucket.items() if len(skillset) > 1
        )

        return {
            'summary': {
                'total_initial_fte': total_initial,
                'total_allocated_fte': total_allocated,
                'total_unutilized_fte': total_current,
                'allocation_success_rate': total_allocated / sum(h['requested'] for h in self.allocation_history) if self.allocation_history else 0
            },
            'by_category': {
                'single_skill': {
                    'initial': single_skill_initial,
                    'allocated': single_skill_initial - single_skill_current,
                    'remaining': single_skill_current
                },
                'multi_skill': {
                    'initial': multi_skill_initial,
                    'allocated': multi_skill_initial - multi_skill_current,
                    'remaining': multi_skill_current
                }
            }
        }

    def get_unmet_demand_report(self) -> pd.DataFrame:
        """
        Generate report of all allocation requests with shortages.

        Returns:
            DataFrame with columns: Platform, State, Month, Worktype, Requested, Allocated, Shortage
        """
        # Filter history to only show entries with shortages
        shortages = [h for h in self.allocation_history if h['shortage'] > 0]

        if not shortages:
            return pd.DataFrame(columns=['Platform', 'State', 'Month', 'Worktype', 'Requested', 'Allocated', 'Shortage'])

        return pd.DataFrame(shortages).rename(columns={
            'platform': 'Platform',
            'state': 'State',
            'month': 'Month',
            'worktype': 'Worktype',
            'requested': 'Requested',
            'allocated': 'Allocated',
            'shortage': 'Shortage'
        })

    def get_unutilized_report(self, output_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate report of unutilized vendor resources.

        IMPORTANT: Only shows unutilized resources for worktypes that appeared in demand.

        Args:
            output_df: The demand DataFrame to filter relevant worktypes

        Returns:
            DataFrame with columns: Platform, State, Month, Skills, Count
        """
        # Get set of demanded worktypes (normalized)
        demanded_worktypes = {
            self._normalize_text(wt).lower()
            for wt in output_df[('Centene Capacity plan', 'Case type')].unique()
            if wt and str(wt).lower() not in {'nan', 'none', ''}
        }

        unutilized = []
        for (platform, state, month), skillsets in self.buckets.items():
            for skillset, count in skillsets.items():
                if count > 0:
                    # Check if ANY skill in this skillset was demanded
                    if skillset & demanded_worktypes:  # Set intersection
                        skills_str = ' + '.join(sorted(skillset))
                        unutilized.append({
                            'Platform': platform,
                            'State': state,
                            'Month': month,
                            'Skills': skills_str,
                            'Count': count
                        })

        if not unutilized:
            return pd.DataFrame(columns=['Platform', 'State', 'Month', 'Skills', 'Count'])

        return pd.DataFrame(unutilized).sort_values(['Platform', 'State', 'Month', 'Skills'])


def get_capacity(row, month):
    target_cph = row[('Centene Capacity plan', 'Target CPH')]
    fte_available = row[('FTE Avail', month)]  # Corrected key
    no_of_days = month_with_days.get(month, 0)
    try:
        logging.debug(f"FTE Avail for {month}: {fte_available}")
        return target_cph * fte_available * (1 - shrinkage) * no_of_days * workhours
    except Exception as e:
        logging.error(f"Error in get_capacity for {month}: {e}")
        return 0

# Legacy per-file vendor filtering - no longer needed with ResourceAllocator
# (ResourceAllocator handles platform/state matching internally)
# def filter_vendor_df(file_name, vendor_df):
#     platform = file_name.split(" ")[0]
#     location = 'Domestic' if 'domestic' in file_name.lower() else 'Global'
#     filtered_df = vendor_df[
#         (vendor_df['PartofProduction'].isin(['Production', 'Ramp'])) &
#         (vendor_df['Location'].str.lower() == location.lower()) &
#         (vendor_df['BeelineTitle'] == 'Claims Analyst') &
#         (vendor_df['PrimaryPlatform'].str.lower() == platform.lower())
#     ]
#     return filtered_df

def initialize_output_excel(month_headers:List[str]):
    wb = Workbook()
    ws = wb.active
    logger.debug(f"input month headers: {month_headers}")
    ws.title = "Capacity plan"
    capacity_plan_headers = ["Main LOB", "State", "Case type", "Call Type ID", "Target CPH"]
    columns = capacity_plan_headers + month_headers * 4
    ws.merge_cells("A1:E1")
    ws.merge_cells("F1:K1")
    ws.merge_cells("L1:Q1")
    ws.merge_cells("R1:W1")
    ws.merge_cells("X1:AC1")
    ws["A1"] = "Centene Capacity plan"
    ws["F1"] = "Client Forecast"
    ws["L1"] = "FTE Required"
    ws["R1"] = "FTE Avail"
    ws["X1"] = "Capacity"
    header_font = Font(bold=True)
    header_alignment = Alignment(horizontal="center", vertical="center")
    for col in range(1, 32):
        ws.cell(row=1, column=col).font = header_font
        ws.cell(row=1, column=col).alignment = header_alignment
    for col, header in enumerate(columns, start=1):
        ws.cell(row=2, column=col, value=header).font = header_font
        ws.cell(row=2, column=col).alignment = header_alignment
    ws.auto_filter.ref = f"A2:{ws.cell(row=2, column=len(columns)).coordinate}"
    wb.save(output_file)

def get_columns_between_column_names(
    df: pd.DataFrame,
    col_level: int = 0,
    start_col_name: str = None,
    end_col_name: str = None
) -> List[str]:
    """
    Returns a list of column names (from the specified row of columns) between start_col_name and the first end_col_name, without duplicates.
    Edge cases:
      - If both start_col_name and end_col_name are missing, returns all columns.
      - If only start_col_name is present, returns columns from that name to the end.
      - If only end_col_name is present, returns columns from start up to (not including) that name.
      - If both are present, returns columns between them.
    """
    if df is None or df.empty or not hasattr(df, "columns"):
        return []

    first_row = df.columns.get_level_values(col_level)
    first_row_str = [str(col).strip() for col in first_row]
    first_row_lower = [col.lower() for col in first_row_str]

    start_idx = None
    end_idx = None

    if start_col_name:
        start_col_name_lower = str(start_col_name).strip().lower()
        if start_col_name_lower in first_row_lower:
            start_idx = first_row_lower.index(start_col_name_lower)
    if end_col_name:
        end_col_name_lower = str(end_col_name).strip().lower()
        # Find first occurrence of end_col_name after start_idx
        search_start = (start_idx + 1) if start_idx is not None else 0
        try:
            end_idx = first_row_lower.index(end_col_name_lower, search_start)
        except ValueError:
            end_idx = None

    # Logic for edge cases
    if start_idx is not None and end_idx is not None and end_idx > start_idx:
        cols = first_row_str[start_idx + 1:end_idx]
    elif start_idx is not None:
        cols = first_row_str[start_idx + 1:]
    elif end_idx is not None:
        cols = first_row_str[:end_idx]
    else:
        cols = first_row_str

    # Remove duplicates while preserving order
    seen = set()
    unique_cols = [x for x in cols if x and not (x in seen or seen.add(x))]
    return unique_cols

def get_nonmmp_columns(df:pd.DataFrame) -> List[str]:
    """
    Returns a list of unique third-level column names
    from a multi-indexed DataFrame, where:
    - First-level column contains 'Forecast - Volume'
    - Third-level column does not contain 'Total'
    """
    # Ensure we are working with MultiIndex columns
    if not isinstance(df.columns, pd.MultiIndex):
        raise ValueError("DataFrame must have MultiIndex columns (3 levels).")

    # Filter columns where first level contains 'Forecast - Volume'
    filtered = [col for col in df.columns if "Forecast - Volume" in str(col[0])]

    # Extract the third-level names
    third_level_names = [col[2] for col in filtered if "Total" not in str(col[2])]

    # Return unique names as a list
    return sorted(set(third_level_names))


def process_files(data_month: str, data_year: int, forecast_file_uploaded_by: str, forecast_filename: str):
    """
    Simulates logic after forecast file upload and updates the processed forecast data.
    """
    start_time = datetime.now()
    logging.info("Starting file processing")

    # Load and filter vendor data upfront
    vendor_df_raw = get_latest_or_requested_dataframe('prod_team_roster', data_month, data_year)

    # Filter to eligible vendors only (Production/Ramp, Claims Analyst)
    logging.info(f"Raw vendor data: {vendor_df_raw.shape}")
    vendor_df = vendor_df_raw[
        (vendor_df_raw['PartofProduction'].isin(['Production', 'Ramp'])) &
        (vendor_df_raw['BeelineTitle'] == 'Claims Analyst')
    ].copy()
    logging.info(f"Filtered vendor data: {vendor_df.shape} (eligible vendors only)")

    # Clean column names
    vendor_df.columns = vendor_df.columns.str.replace("\n", "").str.strip()

    # Verify required columns exist
    required_cols = ['PrimaryPlatform', 'State', 'NewWorkType']
    missing_cols = [col for col in required_cols if col not in vendor_df.columns]
    if missing_cols:
        logging.error(f"Missing required columns in vendor_df: {missing_cols}")
        logging.error(f"Available columns: {list(vendor_df.columns)}")
        raise ValueError(f"Vendor DataFrame missing required columns: {missing_cols}")

    logging.info(f"Vendor data sample - Platform: {vendor_df['PrimaryPlatform'].unique()[:5]}")
    logging.info(f"Vendor data sample - States: {vendor_df['State'].unique()[:10]}")
    logging.info(f"Vendor data sample - NewWorkType (first 5): {vendor_df['NewWorkType'].head().tolist()}")

    month_headers = get_forecast_months_list(data_month, data_year, forecast_filename)
    calculations = Calculations()
    initialize_output_excel(month_headers)
    output_dfs = []
    file_types = get_all_model_dataframes_dict(data_month, data_year)

    for file_type, directory in file_types.items():
        for file_name, df in directory.items():
            logger.info(f"Processing {file_type} file: {file_name}")
            client_names, states, work_types = [], [], []
            # logger.debug(f"Column values: ")
            # for col in df.columns:
            #     logger.debug(f"column value ---- {col}")
            if file_type == 'medicare_medicaid_mmp':
                try:
                    # work_types = [str(wt).strip() for wt in df.columns.get_level_values(0)[6:15] if str(wt).strip()]
                    work_types = get_columns_between_column_names(df,0,'Mo St', 'Year')
                    logging.info(f"Extracted work_types: {work_types}, length: {len(work_types)}, top 5 worktypes: {work_types[:5]}")
                    states = list(set(s for s in df[('State', 'State')].dropna() if s != 0 and isinstance(s, str)))
                    logging.info(f"Extracted states: {states}, length: {len(states)}")
                    if not work_types or not states:
                        logging.warning(f"No valid work types or states for {file_name}. Skipping.")
                        continue
                    total_rows = len(states) * len(work_types)
                    states_expanded = [s for s in states for _ in work_types]
                    work_types_expanded = work_types * len(states)
                    client_names = [file_name] * total_rows
                    logging.info(f"Expected rows: {total_rows}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}, client_names: {len(client_names)}")
                    print("!!!!!!!!!!!!")
                    print(work_types)
                    print(states_expanded)
                    print(len(states))
                    print("!!!!!!!!!!!!")
                    print(total_rows)
                    print(states_expanded)
                    print(work_types_expanded)
                except Exception as e:
                    logging.error(f"Error reading MMP file {file_name}: {e}")
                    continue

            elif file_type == 'medicare_medicaid_nonmmp':
                try:
                    df.columns = df.columns.map(lambda x: tuple(i if 'Unnamed' not in str(i) else '' for i in x))
                    # third_level_headers = [col[2] for col in df.columns]
                    # work_types = []
                    # index = 5
                    # while index < len(third_level_headers):
                    #     work_types.extend([str(third_level_headers[index]).strip(), str(third_level_headers[index + 1]).strip()] if index + 1 < len(third_level_headers) else [str(third_level_headers[index]).strip()])
                    #     index += 11

                    work_types = get_nonmmp_columns(df)
                    logging.info(f"Extracted work_types: {work_types}, length: {len(work_types)}")
                    states = list(set(df[('', '', 'State')].dropna()))
                    logging.info(f"Extracted states: {states}, length: {len(states)}")
                    total_rows = len(states) * len(work_types)
                    states_expanded = [s for s in states for _ in work_types]
                    work_types_expanded = work_types * len(states)
                    client_names = [file_name] * total_rows
                    logging.info(f"Expected rows: {total_rows}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}, client_names: {len(client_names)}")
                except Exception as e:
                    logging.error(f"Error reading non-MMP file {file_name}: {e}")
                    continue

            elif file_type == 'medicare_medicaid_summary' and 'mmp' not in file_name.lower():
                try:
                    if df.empty:
                        logging.warning(f"Empty DataFrame for {file_name}. Skipping.")
                        continue
                    logging.info(f"DataFrame shape for {file_name}: {df.shape}")
                    df.columns = df.columns.map(lambda x: tuple(i if 'Unnamed' not in str(i) else '' for i in x))
                    # df.columns = df.columns.sort_values()
                    first_col = file_name.split("-summary")[0]
                    logging.info(f"Summary file columns: {df.columns.tolist()}")
                    work_type_col = None
                    for col in df.columns:
                        if col[2].lower() in ['work type', 'worktype', 'case type']:
                            work_type_col = col
                            break
                    if work_type_col:
                        try:
                            work_type_values = list(df[work_type_col].dropna())
                            logging.info(f"Work Type column values: {work_type_values}")
                        except Exception as e:
                            logging.warning(f"Failed to log Work Type values for {file_name}: {e}")
                            work_type_values = []
                        work_types = [str(wkt) for wkt in df[work_type_col].fillna('') if str(wkt).lower() != "total" and str(wkt).strip()]
                    else:
                        logging.warning(f"No 'Work Type' column found in {file_name}. Available columns: {df.columns.tolist()}")
                        continue
                    logging.info(f"Extracted work_types: {work_types}, length: {len(work_types)}")
                    states = ["N/A"] * len(work_types)
                    client_names = [first_col] * len(work_types)
                    total_rows = len(work_types)
                    states_expanded = states
                    work_types_expanded = work_types
                    logging.info(f"Expected rows: {total_rows}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}, client_names: {len(client_names)}")
                except Exception as e:
                    logging.error(f"Error reading summary file {file_name}: {e}")
                    continue

            if not work_types_expanded:
                logging.warning(f"No valid work types found for {file_name}. Skipping.")
                continue

            # Initialize output_df with correct number of rows
            column_template = pd.read_excel(output_file, header=[0, 1]).columns
            output_df = pd.DataFrame(index=range(total_rows), columns=column_template)
            try:
                output_df[('Centene Capacity plan', 'Main LOB')] = client_names
                output_df[('Centene Capacity plan', 'State')] = states_expanded
                output_df[('Centene Capacity plan', 'Case type')] = work_types_expanded
                output_df[('Centene Capacity plan', 'temp_Case type')] = output_df[('Centene Capacity plan', 'Case type')].apply(get_temp_casetype)
                output_df[('Centene Capacity plan', 'Call Type ID')] = output_df[('Centene Capacity plan', 'Main LOB')].astype(str)+ " " + output_df[('Centene Capacity plan', 'temp_Case type')].astype(str)
                output_df.drop(columns=[('Centene Capacity plan', 'temp_Case type')], inplace=True)
            except ValueError as e:
                logging.error(f"Length mismatch in {file_name}: {e}")
                logging.info(f"client_names: {len(client_names)}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}")
                continue
            for month in month_headers:
                if file_type == 'medicare_medicaid_mmp':
                    output_df[('Client Forecast', month)] = output_df.apply(lambda row: get_value(row, month, 'medicare_medicaid_mmp', df), axis=1)
                elif file_type == 'medicare_medicaid_nonmmp':
                    output_df[('Client Forecast', month)] = output_df.apply(lambda row: get_value(row, month, 'medicare_medicaid_nonmmp', df), axis=1)
                elif file_type == 'medicare_medicaid_summary':
                    output_df[('Client Forecast', month)] = output_df.apply(lambda row: get_value(row, month, 'medicare_medicaid_summary', df, 3 + month_headers.index(month)), axis=1)

            output_df[('Centene Capacity plan', 'Target CPH')] = output_df.apply(calculations.get_target_cph, axis=1)
            for month in month_headers:
                output_df[('FTE Required', month)] = output_df.apply(lambda row: get_fte_required(row, month, calculations), axis=1)
                output_df[('FTE Required', month)] = output_df[('FTE Required', month)].apply(lambda x: 0.5 if 0 < x < 0.5 else x)
            output_df = output_df.fillna(0).infer_objects(copy=False)
            output_df[output_df.select_dtypes(include=['number']).columns] = output_df.select_dtypes(include=['number']).round().astype(int)

            # Initialize FTE Avail columns (will be populated after consolidation)
            for month in month_headers:
                output_df[('FTE Avail', month)] = 0

            output_dfs.append(output_df)


    # for file_type, directory in directories.items():
    #     for file_name in [f.split(".xlsx")[0] for f in os.listdir(directory) if f.endswith(".xlsx")]:
    #         logging.info(f"Processing {file_type} file: {file_name}")
    #         vendor_filtered_df = filter_vendor_df(file_name, vendor_df)
    #         client_names, states, work_types = [], [], []

    #         if file_type == 'mmp' and 'summary' not in file_name.lower():
    #             try:
    #                 df = pd.read_excel(os.path.join(directory, f"{file_name}.xlsx"), header=[0, 1])
    #                 work_types = [str(wt).strip() for wt in df.columns.get_level_values(0)[6:15] if str(wt).strip()]
    #                 logging.info(f"Extracted work_types: {work_types}, length: {len(work_types)}")
    #                 states = list(set(s for s in df[('State', 'State')].dropna() if s != 0 and isinstance(s, str)))
    #                 logging.info(f"Extracted states: {states}, length: {len(states)}")
    #                 if not work_types or not states:
    #                     logging.warning(f"No valid work types or states for {file_name}. Skipping.")
    #                     continue
    #                 total_rows = len(states) * len(work_types)
    #                 states_expanded = [s for s in states for _ in work_types]
    #                 work_types_expanded = work_types * len(states)
    #                 client_names = [file_name] * total_rows
    #                 logging.info(f"Expected rows: {total_rows}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}, client_names: {len(client_names)}")
    #                 print("!!!!!!!!!!!!")
    #                 print(work_types)
    #                 print(states_expanded)
    #                 print(len(states))
    #                 print("!!!!!!!!!!!!")
    #                 print(total_rows)
    #                 print(states_expanded)
    #                 print(work_types_expanded)
    #             except Exception as e:
    #                 logging.error(f"Error reading MMP file {file_name}: {e}")
    #                 continue

    #         elif file_type == 'nonmmp' and 'summary' not in file_name.lower():
    #             try:
    #                 df = pd.read_excel(os.path.join(directory, f"{file_name}.xlsx"), header=[0, 1, 2])
    #                 df.columns = df.columns.map(lambda x: tuple(i if 'Unnamed' not in str(i) else '' for i in x))
    #                 third_level_headers = [col[2] for col in df.columns]
    #                 work_types = []
    #                 index = 5
    #                 while index < len(third_level_headers):
    #                     work_types.extend([str(third_level_headers[index]).strip(), str(third_level_headers[index + 1]).strip()] if index + 1 < len(third_level_headers) else [str(third_level_headers[index]).strip()])
    #                     index += 11
    #                 logging.info(f"Extracted work_types: {work_types}, length: {len(work_types)}")
    #                 states = list(set(df[('', '', 'State')].dropna()))
    #                 logging.info(f"Extracted states: {states}, length: {len(states)}")
    #                 total_rows = len(states) * len(work_types)
    #                 states_expanded = [s for s in states for _ in work_types]
    #                 work_types_expanded = work_types * len(states)
    #                 client_names = [file_name] * total_rows
    #                 logging.info(f"Expected rows: {total_rows}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}, client_names: {len(client_names)}")
    #             except Exception as e:
    #                 logging.error(f"Error reading non-MMP file {file_name}: {e}")
    #                 continue

    #         elif file_type == 'summary' and 'mmp' not in file_name.lower():
    #             try:
    #                 df = pd.read_excel(os.path.join(directory, f"{file_name}.xlsx"), header=[0, 1, 2, 3])
    #                 if df.empty:
    #                     logging.warning(f"Empty DataFrame for {file_name}. Skipping.")
    #                     continue
    #                 logging.info(f"DataFrame shape for {file_name}: {df.shape}")
    #                 df.columns = df.columns.map(lambda x: tuple(i if 'Unnamed' not in str(i) else '' for i in x))
    #                 df.columns = df.columns.sort_values()
    #                 first_col = file_name.split("-summary")[0]
    #                 logging.info(f"Summary file columns: {df.columns.tolist()}")
    #                 work_type_col = None
    #                 for col in df.columns:
    #                     if col[2].lower() in ['work type', 'worktype', 'case type']:
    #                         work_type_col = col
    #                         break
    #                 if work_type_col:
    #                     try:
    #                         work_type_values = list(df[work_type_col].dropna())
    #                         logging.info(f"Work Type column values: {work_type_values}")
    #                     except Exception as e:
    #                         logging.warning(f"Failed to log Work Type values for {file_name}: {e}")
    #                         work_type_values = []
    #                     work_types = [str(wkt) for wkt in df[work_type_col].fillna('') if str(wkt).lower() != "total" and str(wkt).strip()]
    #                 else:
    #                     logging.warning(f"No 'Work Type' column found in {file_name}. Available columns: {df.columns.tolist()}")
    #                     continue
    #                 logging.info(f"Extracted work_types: {work_types}, length: {len(work_types)}")
    #                 states = ["N/A"] * len(work_types)
    #                 client_names = [first_col] * len(work_types)
    #                 total_rows = len(work_types)
    #                 states_expanded = states
    #                 work_types_expanded = work_types
    #                 logging.info(f"Expected rows: {total_rows}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}, client_names: {len(client_names)}")
    #             except Exception as e:
    #                 logging.error(f"Error reading summary file {file_name}: {e}")
    #                 continue

    #         if not work_types_expanded:
    #             logging.warning(f"No valid work types found for {file_name}. Skipping.")
    #             continue

    #         # Initialize output_df with correct number of rows
    #         column_template = pd.read_excel(output_file, header=[0, 1]).columns
    #         output_df = pd.DataFrame(index=range(total_rows), columns=column_template)
    #         try:
    #             output_df[('Centene Capacity plan', 'Main LOB')] = client_names
    #             output_df[('Centene Capacity plan', 'State')] = states_expanded
    #             output_df[('Centene Capacity plan', 'Case type')] = work_types_expanded
    #             output_df[('Centene Capacity plan', 'temp_Case type')] = output_df[('Centene Capacity plan', 'Case type')].apply(get_temp_casetype)
    #             output_df[('Centene Capacity plan', 'Call Type ID')] = output_df[('Centene Capacity plan', 'Main LOB')].astype(str) + output_df[('Centene Capacity plan', 'temp_Case type')].astype(str)
    #             output_df.drop(columns=[('Centene Capacity plan', 'temp_Case type')], inplace=True)
    #         except ValueError as e:
    #             logging.error(f"Length mismatch in {file_name}: {e}")
    #             logging.info(f"client_names: {len(client_names)}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}")
    #             continue
    #         for month in month_headers:
    #             if file_type == 'mmp':
    #                 output_df[('Client Forecast', month)] = output_df.apply(lambda row: get_value(row, month, 'mmp'), axis=1)
    #             elif file_type == 'nonmmp':
    #                 output_df[('Client Forecast', month)] = output_df.apply(lambda row: get_value(row, month, 'nonmmp'), axis=1)
    #             elif file_type == 'summary':
    #                 output_df[('Client Forecast', month)] = output_df.apply(lambda row: get_value(row, month, 'summary', 3 + month_headers.index(month)), axis=1)

    #         output_df[('Centene Capacity plan', 'Target CPH')] = output_df.apply(get_target_cph, axis=1)
    #         for month in month_headers:
    #             output_df[('FTE Required', month)] = output_df.apply(lambda row: get_fte_required(row, month), axis=1)
    #             output_df[('FTE Required', month)] = output_df[('FTE Required', month)].apply(lambda x: 0.5 if 0 < x < 0.5 else x)
    #         output_df = output_df.fillna(0).infer_objects(copy=False)
    #         output_df[output_df.select_dtypes(include=['number']).columns] = output_df.select_dtypes(include=['number']).round().astype(int)

    #         output_df = output_df.apply(lambda row: process_row_level(row, vendor_filtered_df), axis=1)
    #         for month in month_headers:
    #             output_df[('Capacity', month)] = output_df.apply(lambda row: get_capacity(row, month), axis=1)
    #         output_df = output_df.fillna(0).infer_objects(copy=False)
    #         output_df[output_df.select_dtypes(include=['number']).columns] = output_df.select_dtypes(include=['number']).round().astype(int)

    #         output_dfs.append(output_df)

    if output_dfs:
        logging.info(f"Collected {len(output_dfs)} file outputs, consolidating...")
        consolidated_df = pd.concat(output_dfs, ignore_index=True)
        logging.info(f"Consolidated DataFrame shape: {consolidated_df.shape}")

        # Initialize ResourceAllocator with complete demand data
        logging.info("Initializing ResourceAllocator...")
        allocator = ResourceAllocator(vendor_df, consolidated_df, month_headers)

        # Apply allocation row by row
        logging.info("Starting resource allocation...")
        allocation_start = datetime.now()
        for idx, row in consolidated_df.iterrows():
            platform = row[('Centene Capacity plan', 'Main LOB')]
            state = row[('Centene Capacity plan', 'State')]
            worktype = row[('Centene Capacity plan', 'Case type')]

            for month in month_headers:
                fte_required = row[('FTE Required', month)]
                allocated, _ = allocator.allocate(platform, state, month, worktype, fte_required)
                consolidated_df.at[idx, ('FTE Avail', month)] = allocated

        allocation_end = datetime.now()
        logging.info(f"Allocation completed in {allocation_end - allocation_start}")

        # Calculate capacity
        for month in month_headers:
            consolidated_df[('Capacity', month)] = consolidated_df.apply(lambda row: get_capacity(row, month), axis=1)

        # Final cleanup
        consolidated_df = consolidated_df.fillna(0).infer_objects(copy=False)
        consolidated_df[consolidated_df.select_dtypes(include=['number']).columns] = consolidated_df.select_dtypes(include=['number']).round().astype(int)

        # Generate reports
        logging.info("Generating allocation reports...")
        summary_report = allocator.get_summary_report()
        logging.info(f"=== ALLOCATION SUMMARY ===")
        logging.info(f"Total Initial FTE: {summary_report['summary']['total_initial_fte']}")
        logging.info(f"Total Allocated FTE: {summary_report['summary']['total_allocated_fte']}")
        logging.info(f"Total Unutilized FTE: {summary_report['summary']['total_unutilized_fte']}")
        logging.info(f"Allocation Success Rate: {summary_report['summary']['allocation_success_rate']:.2%}")

        unmet_demand_df = allocator.get_unmet_demand_report()
        if not unmet_demand_df.empty:
            logging.warning(f"Found {len(unmet_demand_df)} allocation shortages")
            unmet_output_path = os.path.join(curpth, "unmet_demand_report.xlsx")
            unmet_demand_df.to_excel(unmet_output_path, index=False)
            logging.info(f"Saved unmet demand report to {unmet_output_path}")
        else:
            logging.info("No allocation shortages - all demand met!")

        unutilized_df = allocator.get_unutilized_report(consolidated_df)
        if not unutilized_df.empty:
            logging.info(f"Found {len(unutilized_df)} unutilized resource groups")
            unutilized_output_path = os.path.join(curpth, "unutilized_resources_report.xlsx")
            unutilized_df.to_excel(unutilized_output_path, index=False)
            logging.info(f"Saved unutilized resources report to {unutilized_output_path}")
        else:
            logging.info("All vendor resources utilized!")

        # Save processed data
        preprocessor = PreProcessing("forecast")
        mod_consolitated_df = preprocessor.preprocess_forecast_df(consolidated_df.copy())
        update_forecast_data(mod_consolitated_df, data_month, data_year, forecast_file_uploaded_by, forecast_filename)
        logging.info("Forecast data updated successfully.")
        update_summary_data(data_month, data_year)
        consolidated_df.to_excel(output_file)
        logging.info(f"Saved consolidated output to {output_file}")
    else:
        logging.error("No valid DataFrames generated. Check input files.")

    end_time = datetime.now()
    logging.info(f"Processing completed. Total time: {end_time - start_time}")

# Legacy function - no longer used with ResourceAllocator
# def process_row_level(row, month_headers, vendor_df):
#     for month in month_headers:
#         row[('FTE Avail', month)] = get_skills_split_count(row, month, vendor_df)
#         logging.debug(f"FTE Avail for {month}: {row[('FTE Avail', month)]}")
#     return row

if __name__ == "__main__":
    # pass
    process_files('March', 2025, 'Makzoom Shah', 'NTT Forecast - v4_Capacity and HC_March_2025.xlsx')