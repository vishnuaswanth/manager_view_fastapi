#!/usr/bin/env python3
"""
Roster Sanitizer: Excel in -> Excel out (sanitized_roster.xlsx)

- Speed first, memory second: pandas + (optional) pyarrow dtypes, vectorized filters,
  minimal copies, xlsxwriter conditional formatting (no per-cell loops).
- DRY/SOLID design: small focused components, explicit configs, single writer context.

Features
--------
1) Reads a single-sheet Excel roster.
2) Adds boolean 'allocated':
   - IN-SCOPE rows are evaluated True/False using a greedy, longest-phrase match over NewWorkType.
   - OUT-OF-SCOPE rows keep 'allocated' BLANK.
3) Highlights (on main sheet):
   - allocated == FALSE  -> orange
   - allocated is BLANK  -> light grey
   - duplicate CN#       -> magenta
4) Issues sheet: unknown worktype fragments + duplicate CN# listing.
5) Summary sheet: counts for scope/allocated states + issues.
6) Readme sheet: filter rules + header normalization map.
7) Optional Review sheet: sorted (duplicates first, then False, True, Blank).
8) Optional --demo flag to generate a synthetic input and run end-to-end.

Usage
-----
  python roster_sanitizer.py --in input.xlsx --out sanitized_roster.xlsx [--sheet SHEETNAME] [--no-review] [--verbose]
  python roster_sanitizer.py --demo [--out sanitized_roster.xlsx] [--no-review] [--verbose]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Tuple, Iterable, Optional, Any, Set

import pandas as pd

# Optional acceleration (pandas will use numexpr in query/eval if present)
try:
    import numexpr  # noqa: F401
except Exception:
    pass

# ---------- Config & Constants ----------

@dataclass(frozen=True)
class FiltersConfig:
    part_of_production: Tuple[str, ...] = ("Production", "Ramp")
    location: Tuple[str, ...] = ("Global", "Domestic")
    beeline_title: str = "Claims Analyst"
    primary_platform: Tuple[str, ...] = ("Amisys", "Facets", "Xcelys")


@dataclass(frozen=True)
class OutputConfig:
    main_sheet_name: str = "Roster"
    review_sheet_name: str = "Review"
    issues_sheet_name: str = "Issues"
    summary_sheet_name: str = "Summary"
    readme_sheet_name: str = "Readme"
    allocated_col_name: str = "allocated"


@dataclass(frozen=True)
class HighlightColors:
    false_fill: str = "#FFC000"       # Orange
    blank_fill: str = "#EDEDED"       # Light grey
    duplicate_fill: str = "#FF66FF"   # Magenta


# Authoritative, case-sensitive allow list EXACTLY as supplied.
ALLOW_WORKTYPES: Tuple[str, ...] = (
    "ADJ",
    "ADJ COB",
    "ADJ MCAID",
    "ADJ MCARE",
    "ADJ/COR/APP",
    "ADJ-Basic/NON MMP",
    "ADJ-COB NON MMP",
    "APP",
    "APP MCAID",
    "APP MCARE",
    "APP-BASIC/NON MMP",
    "APP-COB NON MMP",
    "Auth Report/Spreadsheet",
    "BOT ADJ",
    "BOT FTC",
    "COR",
    "COR MCAID",
    "COR MCARE",
    "COR-Basic/NON MMP",
    "COR-COB NON MMP",
    "Corr",
    "Corrected Claims - CenPas",
    "Domestic",
    "FTC",
    "FTC Basic",
    "FTC COB",
    "FTC MCAID",
    "FTC MCARE",
    "FTC Non COB",
    "FTC-Basic/Non MMP",
    "FTC-COB NON MMP",
    "Global",
    "LOB",
    "Marketplace",
    "Medicaid",
    "Medicare",
    "OMN",
    "OMN MCAID",
    "OMN MCARE",
    "OMN-Basic/NON MMP",
    "OMN-COB NON MMP",
    "Prepay",
    "Projects",
    "SALESFORCE",
    "Total Excluding BOT",
    "XC Claims",
)


# ---------- Utilities ----------

SPACE_RE: re.Pattern = re.compile(r"[ \t\u00A0]+")   # collapse ASCII/nbsp spaces
BRACKETS_RE: re.Pattern = re.compile(r"\[[^\]]*]")   # remove [ ... ] segments


def normalize_header_for_matching(col: str) -> str:
    """
    Create a canonical matching key from a header:
    - Remove surrounding quotes, newlines, bracket hints [...], apostrophes,
    - Collapse whitespace, remove non-alnum except #,
    - Lowercase.
    Example: "PrimaryPlatform [ABS,Amisys]" -> "primaryplatform"
    """
    if col is None:
        return ""
    s = str(col)
    s = s.replace("\r", " ").replace("\n", " ")
    s = s.strip().strip('"').strip("'")
    s = BRACKETS_RE.sub("", s)
    s = SPACE_RE.sub(" ", s).strip()
    s = s.replace("’", "").replace("'", "")
    s = re.sub(r"[^0-9A-Za-z#]+", "", s)
    return s.lower()


def standardize_cell_str_for_matching(x: Any) -> str:
    """
    Standardize cell strings for matching WITHOUT changing case or punctuation.
    - Convert None/NaNs/'NULL'/'N/A'/'-' to empty string
    - Replace NBSP and tabs with spaces
    - Trim and collapse multiple spaces to a single space
    NOTE: Case and punctuation preserved to respect case-sensitive, punctuation-strict matching.
    """
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    s = str(x)
    if s.strip().upper() in {"NULL", "N/A"} or s.strip() == "-":
        return ""
    s = s.replace("\u00A0", " ").replace("\t", " ")
    s = SPACE_RE.sub(" ", s).strip()
    return s


def excel_colname(idx: int) -> str:
    """0-based index -> Excel column letters, e.g., 0->A, 25->Z, 26->AA."""
    name = []
    i = idx
    while True:
        i, r = divmod(i, 26)
        name.append(chr(r + ord('A')))
        if i == 0:
            break
        i -= 1
    return "".join(reversed(name))


# ---------- Header Resolution ----------

@dataclass
class ColumnRefs:
    cn: str
    part_of_production: str
    location: str
    beeline_title: str
    primary_platform: str
    new_worktype: str
    all_columns: List[str]
    header_map: Dict[str, str]  # normalized_key -> original name


def resolve_columns(df_columns: Iterable[str]) -> ColumnRefs:
    """
    Map canonical keys to actual column names found in the Excel.
    We don't rename in the main sheet; we just resolve references robustly.
    """
    cols = list(df_columns)
    norm_map: Dict[str, str] = {normalize_header_for_matching(c): c for c in cols}

    # Helper to fetch with good error message.
    def need(key_variants: List[str], label: str) -> str:
        for k in key_variants:
            if k in norm_map:
                return norm_map[k]
        raise KeyError(f"Required column '{label}' not found. Looked for any of: {key_variants}. "
                       f"Available (normalized): {sorted(norm_map.keys())}")

    cn_col = need(["cn#", "cn"], "CN#")
    pop_col = need(["partofproduction", "partofprod", "partofprodstatus"], "PartofProduction")
    loc_col = need(["location"], "Location")
    blt_col = need(["beelinetitle", "beelinejobtitle", "title"], "BeelineTitle")
    plat_col = need(["primaryplatform", "platform"], "PrimaryPlatform")
    nwt_col = need(["newworktype", "newworktypes"], "NewWorkType")

    return ColumnRefs(
        cn=cn_col,
        part_of_production=pop_col,
        location=loc_col,
        beeline_title=blt_col,
        primary_platform=plat_col,
        new_worktype=nwt_col,
        all_columns=cols,
        header_map={k: v for k, v in norm_map.items()},
    )


# ---------- Worktype Matcher (Greedy, Longest-Phrase) ----------

class WorktypeMatcher:
    """
    Token-based trie with CASE-SENSITIVE matching and exact punctuation.
    Splits phrases by single spaces; uses greedy longest-phrase segmentation.
    """

    class Node(dict):
        __slots__ = ("end",)
        def __init__(self):
            super().__init__()
            self.end: bool = False  # phrase ends here

    def __init__(self, phrases: Iterable[str]):
        self.root = self.Node()
        for p in phrases:
            tokens = p.split(" ")
            self._insert(tokens)

    def _insert(self, tokens: List[str]) -> None:
        node = self.root
        for t in tokens:
            if t not in node:
                node[t] = self.Node()
            node = node[t]
        node.end = True

    def segment(self, text: str) -> Tuple[bool, List[str]]:
        """
        Return (ok, unknown_chunks).
        - text is pre-standardized (spaces collapsed), case/punctuation intact.
        - Multiple worktypes separated by single spaces.
        - Uses greedy longest match; if any portion can't be covered -> ok=False.
        - unknown_chunks: list of unmatched fragments (space-joined tokens).
        """
        if not text:
            return False, ["<EMPTY>"]

        tokens = text.split(" ")
        i = 0
        unknown_chunks: List[str] = []
        any_unknown = False

        while i < len(tokens):
            node = self.root
            j = i
            best_end: Optional[int] = None
            # Walk forward while tokens match trie
            while j < len(tokens) and tokens[j] in node:
                node = node[tokens[j]]
                j += 1
                if node.end:
                    best_end = j
            if best_end is not None:
                # Accept longest phrase
                i = best_end
            else:
                # Unknown token; collect as a chunk (single token)
                any_unknown = True
                unknown_chunks.append(tokens[i])
                i += 1

        return (not any_unknown), unknown_chunks


# ---------- Processing Pipeline ----------

@dataclass
class ProcessingResult:
    df_out: pd.DataFrame
    duplicates_mask: pd.Series
    unknown_phrases_map: Dict[str, Set[Any]]  # fragment -> CN# set
    counts: Dict[str, int]


class RosterProcessor:
    def __init__(self, filters: FiltersConfig, output_cfg: OutputConfig, allow_phrases: Tuple[str, ...]):
        self.filters = filters
        self.output_cfg = output_cfg
        self.matcher = WorktypeMatcher(allow_phrases)

    def process(self, df: pd.DataFrame, refs: ColumnRefs, verbose: bool = False) -> ProcessingResult:
        # Standardized helpers for filtering (original df values remain unchanged)
        pop = df[refs.part_of_production].map(standardize_cell_str_for_matching)
        loc = df[refs.location].map(standardize_cell_str_for_matching)
        blt = df[refs.beeline_title].map(standardize_cell_str_for_matching)
        plat = df[refs.primary_platform].map(standardize_cell_str_for_matching)

        # Vectorized filter mask
        in_scope = (
            pop.isin(self.filters.part_of_production)
            & loc.isin(self.filters.location)
            & (blt == self.filters.beeline_title)
            & plat.isin(self.filters.primary_platform)
        )

        # Initialize allocated with None (for blanks in Excel)
        allocated = pd.Series([None] * len(df), index=df.index, dtype="object")

        # Evaluate in-scope rows
        nwt_std = df[refs.new_worktype].map(standardize_cell_str_for_matching)

        unknown_map: Dict[str, Set[Any]] = {}
        true_count = 0
        false_count = 0

        scope_idx = df.index[in_scope]
        # Efficient loop only over in-scope rows
        for i in scope_idx:
            text = nwt_std.iat[df.index.get_loc(i)]
            ok, unknown = self.matcher.segment(text)
            if ok:
                allocated.iat[df.index.get_loc(i)] = True
                true_count += 1
            else:
                allocated.iat[df.index.get_loc(i)] = False
                false_count += 1
                # Record unknown fragments with CN#
                cn_val = df.at[i, refs.cn]
                for frag in unknown:
                    unknown_map.setdefault(frag, set()).add(cn_val)

        blank_count = int((~in_scope).sum())

        # Duplicate CN# mask
        dup_mask = df.duplicated(subset=[refs.cn], keep=False)

        # Build output DataFrame, keep original columns + 'allocated'
        df_out = df.copy()  # safe copy; adding new column
        df_out[self.output_cfg.allocated_col_name] = allocated

        counts = dict(
            total=len(df_out),
            in_scope=int(in_scope.sum()),
            allocated_true=true_count,
            allocated_false=false_count,
            allocated_blank=blank_count,
            duplicates=int(dup_mask.sum()),
            unknown_fragments=len(unknown_map),
        )

        if verbose:
            print("Counts:", counts, file=sys.stderr)

        return ProcessingResult(
            df_out=df_out,
            duplicates_mask=dup_mask,
            unknown_phrases_map=unknown_map,
            counts=counts,
        )


# ---------- Excel Writer with Conditional Formatting (single writer context) ----------

class ExcelWriterWithFormats:
    def __init__(self, out_path: str, output_cfg: OutputConfig, hl: HighlightColors):
        self.out_path = out_path
        self.cfg = output_cfg
        self.hl = hl

    def write_all(
        self,
        processed: ProcessingResult,
        refs: ColumnRefs,
        include_review: bool = True,
    ) -> None:
        # Use ONE writer context; xlsxwriter doesn't support append mode.
        with pd.ExcelWriter(self.out_path, engine="xlsxwriter") as writer:
            # Main sheet
            processed.df_out.to_excel(
                writer,
                sheet_name=self.cfg.main_sheet_name,
                index=False,
            )

            wb = writer.book
            ws = writer.sheets[self.cfg.main_sheet_name]

            nrows, ncols = processed.df_out.shape
            # Data rows start at row 2 in Excel (1-based) because row 1 is header.
            first_row = 2
            last_row = nrows + 1
            first_col_letter = "A"
            last_col_letter = excel_colname(ncols - 1)

            # Column letters for formulas
            alloc_col_idx = processed.df_out.columns.get_loc(self.cfg.allocated_col_name)
            alloc_col_letter = excel_colname(alloc_col_idx)

            cn_col_idx = processed.df_out.columns.get_loc(refs.cn)
            cn_col_letter = excel_colname(cn_col_idx)

            full_range = f"{first_col_letter}{first_row}:{last_col_letter}{last_row}"

            # Formats
            fmt_false = wb.add_format({"bg_color": self.hl.false_fill})
            fmt_blank = wb.add_format({"bg_color": self.hl.blank_fill})
            fmt_dup = wb.add_format({"bg_color": self.hl.duplicate_fill})


            # 1) Highlight duplicate CN# (magenta)
            ws.conditional_format(
                full_range,
                {
                    "type": "formula",
                    "criteria": f'=COUNTIF(${cn_col_letter}:${cn_col_letter},${cn_col_letter}{first_row})>1',
                    "format": fmt_dup,
                },
            )
            # 2) Grey out BLANK allocated
            ws.conditional_format(
                full_range,
                {
                    "type": "formula",
                    "criteria": f'=ISBLANK(${alloc_col_letter}{first_row})',
                    "format": fmt_blank,
                },
            )

            # 3) Highlight allocated == FALSE (orange)
            # Use relative row reference: =$AL2=FALSE applied from first_row, adjusts per row.
            ws.conditional_format(
                full_range,
                {
                    "type": "formula",
                    "criteria": f'=${alloc_col_letter}{first_row}=FALSE',
                    "format": fmt_false,
                },
            )

            # Auto-fit-ish: set a sensible width
            for idx, col in enumerate(processed.df_out.columns):
                try:
                    col_width = max(12, min(40, int(processed.df_out[col].astype(str).str.len().quantile(0.95)) + 2))
                except Exception:
                    col_width = 18
                ws.set_column(idx, idx, col_width)

            # ---------- Issues sheet (unknown fragments + duplicates) ----------
            issues_rows: List[Dict[str, Any]] = []
            for frag, cns in sorted(processed.unknown_phrases_map.items(), key=lambda kv: (-len(kv[1]), kv[0])):
                issues_rows.append({
                    "IssueType": "UnknownWorktypeFragment",
                    "Fragment": frag,
                    "CountRows": len(cns),
                    "SampleCNs": ", ".join(list(cns)[:10]),
                })
            issues_df = pd.DataFrame(issues_rows)
            if issues_df.empty:
                issues_df = pd.DataFrame([{"Note": "No unknown fragments detected."}])

            issues_df.to_excel(writer, sheet_name=self.cfg.issues_sheet_name, index=False, startrow=0)
            ws_issues = writer.sheets[self.cfg.issues_sheet_name]
            startrow = len(issues_df) + 2

            # Duplicate CN# listing
            dup_df = processed.df_out.loc[processed.duplicates_mask, [refs.cn]].copy()
            if not dup_df.empty:
                dup_counts = dup_df.value_counts().reset_index(name="Count")
                dup_counts.columns = [refs.cn, "Count"]
                dup_counts.to_excel(writer, sheet_name=self.cfg.issues_sheet_name, index=False, startrow=startrow)
            else:
                pd.DataFrame([{"Note": "No duplicate CN# detected."}]).to_excel(
                    writer, sheet_name=self.cfg.issues_sheet_name, index=False, startrow=startrow
                )

            # ---------- Summary sheet ----------
            rows = [{"Metric": k, "Value": v} for k, v in processed.counts.items()]
            summary_df = pd.DataFrame(rows)
            summary_df.to_excel(writer, sheet_name=self.cfg.summary_sheet_name, index=False)

            # ---------- Readme sheet ----------
            # Header normalization map (normalized -> original)
            readme_rows = [{"NormalizedKey": k, "OriginalHeader": v} for k, v in sorted(refs.header_map.items())]
            readme_df = pd.DataFrame(readme_rows)
            readme_df.to_excel(writer, sheet_name=self.cfg.readme_sheet_name, index=False, startrow=0)

            # Append rules under the mapping
            rules = [
                {"Rule": "In-scope PartofProduction", "Value": ", ".join(FiltersConfig().part_of_production)},
                {"Rule": "In-scope Location", "Value": ", ".join(FiltersConfig().location)},
                {"Rule": "BeelineTitle equals", "Value": FiltersConfig().beeline_title},
                {"Rule": "PrimaryPlatform in", "Value": ", ".join(FiltersConfig().primary_platform)},
                {"Rule": "allocated = True", "Value": "All NewWorkType phrases in allow-list (case & punctuation exact)"},
                {"Rule": "allocated = False", "Value": "Any unknown/extra/mismatched phrase OR empty NewWorkType for in-scope row"},
                {"Rule": "allocated = Blank", "Value": "Row is out of scope; visually de-emphasized"},
            ]
            pd.DataFrame(rules).to_excel(
                writer, sheet_name=self.cfg.readme_sheet_name, index=False, startrow=len(readme_df) + 2
            )

            # ---------- Optional Review sheet ----------
            if include_review:
                df = processed.df_out.copy()
                dup = processed.duplicates_mask
                alloc = df[self.cfg.allocated_col_name]

                def alloc_rank(v: Any) -> int:
                    # 1: False, 2: True, 3: Blank
                    if pd.isna(v) or v is None:
                        return 3
                    return 2 if bool(v) else 1

                sort_key = alloc.map(alloc_rank)
                df["_dup_"] = dup.astype(int)  # 1 duplicates, 0 non-duplicates
                df["_sort_"] = sort_key

                df = df.sort_values(by=["_dup_", "_sort_"], ascending=[False, True]).drop(columns=["_dup_", "_sort_"])
                df.to_excel(writer, sheet_name=self.cfg.review_sheet_name, index=False)


# ---------- I/O & CLI ----------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Sanitize roster and add 'allocated' with highlights.")
    ap.add_argument("--in", dest="in_path", help="Input Excel (.xlsx). If omitted with --demo, a synthetic file is generated.")
    ap.add_argument("--out", dest="out_path", default="sanitized_roster.xlsx", help="Output Excel (.xlsx)")
    ap.add_argument("--sheet", dest="sheet_name", default=None, help="Sheet name to read (default: first sheet)")
    ap.add_argument("--no-review", dest="no_review", action="store_true", help="Do not create the Review sheet")
    ap.add_argument("--verbose", action="store_true", help="Verbose logging to stderr")
    ap.add_argument("--demo", action="store_true", help="Generate a synthetic input and run end-to-end")
    return ap.parse_args(argv)


def read_excel_fast(path: str, sheet: Optional[str]) -> pd.DataFrame:
    """
    Prefer pyarrow dtype backend when supported; clean fallback otherwise.
    """
    read_kwargs = {"engine": "openpyxl", "sheet_name": sheet if sheet else 0}
    try:
        # Try dtype_backend only if supported by this pandas build.
        df = pd.read_excel(path, dtype_backend="pyarrow", **read_kwargs)  # type: ignore
        return df
    except TypeError:
        # Older pandas without dtype_backend
        return pd.read_excel(path, **read_kwargs)


# ---------- Synthetic Demo ----------

def make_synthetic_df() -> pd.DataFrame:
    headers = [
        "FirstName",
        "LastName",
        "CN#",
        "OPID",
        "Location",
        "ZIPCode",
        "City",
        "BeelineTitle",
        "Status\n[inTrainingorProduction]",
        "PrimaryPlatform\n[ABS,Amisys,Facets,Xcelys]",
        "PrimaryMarket(Medicare,Medicaid,Marketplace)",
        "Worktype(FTC/ADJ/COB)",
        "LOB",
        "Supervisor'sFullName",
        "Supervisor'sCN#",
        "UserStatus",
        "PartofProduction",
        "Production%",
        "NewWorkType",
        "State",
        "CenteneMailId",
        "NTTMailID",
    ]

    rows = [
        # In-scope, True: single allowed
        ["Alice", "Andrews", "CN1001", "OP001", "Global", "75001", "Austin", "Claims Analyst", "Prod", "Facets", "Medicare", "ADJ", "A", "Boss A", "S001", "Active", "Production", 100, "APP", "TX", "a@centene.com", "a@ntt.com"],
        # In-scope, False: unknown BASIC token
        ["Bob", "Baker", "CN1002", "OP002", "Domestic", "94102", "SF", "Claims Analyst", "Prod", "Amisys", "Medicaid", "ADJ", "B", "Boss B", "S002", "Active", "Production", 100, "APP BASIC", "CA", "b@centene.com", "b@ntt.com"],
        # In-scope, True: allowed hyphen/slash phrase
        ["Cara", "Cole", "CN1003", "OP003", "Global", "10001", "NYC", "Claims Analyst", "Prod", "Facets", "Medicare", "ADJ", "C", "Boss C", "S003", "Active", "Ramp", 100, "APP-BASIC/NON MMP", "NY", "c@centene.com", "c@ntt.com"],
        # Duplicate CN# (same as above), In-scope, True (multi-phrase)
        ["Carl", "Cole", "CN1003", "OP004", "Domestic", "10002", "NYC", "Claims Analyst", "Prod", "Xcelys", "Medicare", "ADJ", "C", "Boss D", "S004", "Active", "Ramp", 100, "FTC COB APP", "NY", "c2@centene.com", "c2@ntt.com"],
        # In-scope, False: case mismatch inside phrase (Non vs NON)
        ["Dana", "Dane", "CN1004", "OP005", "Global", "73301", "Austin", "Claims Analyst", "Prod", "Amisys", "Medicare", "ADJ", "D", "Boss E", "S005", "Active", "Production", 100, "OMN-Basic/Non MMP", "TX", "d@centene.com", "d@ntt.com"],
        # In-scope, True: multi-phrase segmentation
        ["Evan", "Elm", "CN1005", "OP006", "Domestic", "02110", "Boston", "Claims Analyst", "Prod", "Facets", "Medicaid", "ADJ", "E", "Boss F", "S006", "Active", "Production", 100, "FTC COB APP", "MA", "e@centene.com", "e@ntt.com"],
        # In-scope, False: empty NewWorkType
        ["Finn", "Frost", "CN1006", "OP007", "Global", "60601", "Chicago", "Claims Analyst", "Prod", "Xcelys", "Medicare", "ADJ", "F", "Boss G", "S007", "Active", "Production", 100, "", "IL", "f@centene.com", "f@ntt.com"],
        # Out-of-scope (Location not Global/Domestic)
        ["Gail", "Green", "CN1007", "OP008", "Offshore", "73344", "Austin", "Claims Analyst", "Prod", "Facets", "Medicare", "ADJ", "G", "Boss H", "S008", "Active", "Production", 100, "APP MCARE", "TX", "g@centene.com", "g@ntt.com"],
        # Out-of-scope (BeelineTitle different)
        ["Hank", "Hill", "CN1008", "OP009", "Global", "73344", "Austin", "Sr Analyst", "Prod", "Facets", "Medicare", "ADJ", "H", "Boss I", "S009", "Active", "Production", 100, "APP-COB NON MMP", "TX", "h@centene.com", "h@ntt.com"],
        # In-scope, True: composite including slashes
        ["Ivy", "Ives", "CN1009", "OP010", "Domestic", "33101", "Miami", "Claims Analyst", "Prod", "Amisys", "Medicaid", "ADJ", "I", "Boss J", "S010", "Active", "Production", 100, "ADJ/COR/APP APP MCARE", "FL", "i@centene.com", "i@ntt.com"],
        # In-scope, False: smashed token (no space)
        ["Jack", "June", "CN1010", "OP011", "Global", "73301", "Austin", "Claims Analyst", "Prod", "Amisys", "Medicare", "ADJ", "J", "Boss K", "S011", "Active", "Production", 100, "FTCCOB", "TX", "j@centene.com", "j@ntt.com"],
        # In-scope, True: Corrected Claims phrase
        ["Kate", "Kole", "CN1011", "OP012", "Domestic", "15201", "Pittsburgh", "Claims Analyst", "Prod", "Facets", "Medicare", "ADJ", "K", "Boss L", "S012", "Active", "Ramp", 100, "Corrected Claims - CenPas", "PA", "k@centene.com", "k@ntt.com"],
    ]

    return pd.DataFrame(rows, columns=headers)


# ---------- Orchestration ----------

def run_pipeline(df_in: pd.DataFrame, out_path: str, sheet_name: Optional[str], include_review: bool, verbose: bool) -> None:
    # Resolve headers
    refs = resolve_columns(df_in.columns)

    # Process
    processor = RosterProcessor(FiltersConfig(), OutputConfig(), ALLOW_WORKTYPES)
    result = processor.process(df_in, refs, verbose=verbose)

    # Write with formats (single writer context)
    writer = ExcelWriterWithFormats(out_path, OutputConfig(), HighlightColors())
    writer.write_all(result, refs, include_review=include_review)

    if verbose:
        print(f"Done. Wrote: {out_path}", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    if args.demo:
        # Generate synthetic input and run
        df_in = make_synthetic_df()
        run_pipeline(df_in, args.out_path, sheet_name=None, include_review=(not args.no_review), verbose=args.verbose)
        return

    if not args.in_path:
        print("Error: --in is required unless --demo is used.", file=sys.stderr)
        sys.exit(2)

    # Read Excel
    df_in = read_excel_fast(args.in_path, args.sheet_name)

    # Run
    run_pipeline(df_in, args.out_path, sheet_name=args.sheet_name, include_review=(not args.no_review), verbose=args.verbose)


if __name__ == "__main__":
    main()
