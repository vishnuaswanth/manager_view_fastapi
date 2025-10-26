
from __future__ import annotations

from datetime import datetime, date, timedelta
import pandas as pd
import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
import os

from code.logics.core_utils import (
    get_model_or_all_models,
    PreProcessing, 
    CoreUtils, 
    PostProcessing,     
)

from code.logics.db import (
    RawData
)

from code.logics.export_utils import (
    get_processed_dataframe,
)
from code.settings import  (
    MODE,
    SQLITE_DATABASE_URL, 
    MSSQL_DATABASE_URL,
    BASE_DIR
)


def previous_month_info(current_month_name: str, year: int):
    """
    Given a month name (e.g., 'March' or 'Mar') and a year (e.g., 2025),
    return the previous month as a dict with:
      - month_number (1-12)
      - month_name (full English name)
      - year (adjusted if current month is January)

    Examples:
        >>> previous_month_info("March", 2025)
        {'month_number': 2, 'month_name': 'February', 'year': 2025}

        >>> previous_month_info("Jan", 2024)
        {'month_number': 12, 'month_name': 'December', 'year': 2023}
    """
    # Parse month name (accepts full or abbreviated, any case)
    month_num = None
    for fmt in ("%B", "%b"):  # Full name or abbreviated (e.g., March / Mar)
        try:
            month_num = datetime.strptime(current_month_name.strip(), fmt).month
            break
        except ValueError:
            continue
    if month_num is None:
        raise ValueError(f"Invalid month name: {current_month_name!r}")

    # Take the first day of the given month, then step back one day
    first_of_month = date(year, month_num, 1)
    last_of_prev_month = first_of_month - timedelta(days=1)

    # Build result
    prev_month_number = last_of_prev_month.month
    prev_month_name = last_of_prev_month.strftime("%B")
    prev_year = last_of_prev_month.year

    return {
        "month_number": prev_month_number,
        "month_name": prev_month_name,
        "year": prev_year,
    }



if MODE.upper() == "DEBUG":
    DATABASE_URL = SQLITE_DATABASE_URL
elif MODE.upper() == "PRODUCTION":
    DATABASE_URL = MSSQL_DATABASE_URL
else:
    raise ValueError("Invalid MODE specified in config.")

# Step 2: Initialize the CoreUtils instance with final DB URL
core_utils = CoreUtils(DATABASE_URL)

logger = logging.getLogger(__name__)

# ---------- logging bootstrap (uses `logger` var if already configured) ----------
try:
    logger  # type: ignore[name-defined]
except NameError:  # pragma: no cover
    import logging
    logger = logging.getLogger("capacity_summary")
    if not logger.handlers:
        _h = logging.StreamHandler()
        _f = logging.Formatter("%(levelname)s | %(name)s | %(message)s")
        _h.setFormatter(_f)
        logger.addHandler(_h)
    logger.setLevel(logging.INFO)

# ---------------------------
# Constants / Schema anchors
# ---------------------------
L1_PLAN = "Centene Capacity plan"
L1_FORECAST = "Client Forecast"
L1_FTE_AVAIL = "FTE Avail"
L1_CAPACITY = "Capacity"

PLAN_SUB = ["Main LOB", "State", "Case type", "Call Type ID", "Target CPH"]

# Output Level-2 blocks (fixed order)
L2_VENDOR_ELIGIBLE = "Vendor Eligible Forecast (WFM)"
L2_CAPACITY_NTT = "Capacity (NTT)"
L2_DIFFERENCE = "Difference"
L2_PRIOR = "Prior Month Capacity Provided"
L2_NEW_VS_PRIOR = "New Capacity v Prior month differences"


# ---------------------------
# Utilities (fast & memory-aware)
# ---------------------------
def extract_months(df: pd.DataFrame, group_name: str) -> List[str]:
    months = [c[1] for c in df.columns if c[0] == group_name and c[1] not in PLAN_SUB]
    logger.debug(f"extract_months: group={group_name}, months={months}")
    return months


def drop_plan_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    plan_keys = [(L1_PLAN, c) for c in PLAN_SUB]
    before = len(df)
    df2 = df.drop_duplicates(subset=plan_keys, keep="first", ignore_index=True)
    after = len(df2)
    if after != before:
        logger.info(f"drop_plan_duplicates: dropped {before - after} duplicate rows (kept first).")
    else:
        logger.info("drop_plan_duplicates: no duplicates found.")
    return df2


def fill_and_downcast_month_blocks(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for g in (L1_FORECAST, L1_FTE_AVAIL, L1_CAPACITY):
        mcols = [(g, m) for m in extract_months(df, g)]
        if mcols:
            logger.info(f"fill_and_downcast_month_blocks: group={g}, casting {len(mcols)} columns to int32 with NA->0.")
            df.loc[:, mcols] = df.loc[:, mcols].fillna(0).astype("int32")
    cph_col = (L1_PLAN, "Target CPH")
    if cph_col in df.columns:
        logger.info("fill_and_downcast_month_blocks: normalizing Target CPH to int32 with NA->0.")
        df[cph_col] = pd.to_numeric(df[cph_col], errors="coerce").fillna(0).astype("int32")
    return df


def group_sum_by_lob_case(df: pd.DataFrame, group_name: str) -> pd.DataFrame:
    months = extract_months(df, group_name)
    key_lob = (L1_PLAN, "Main LOB")
    key_case = (L1_PLAN, "Case type")
    out = df.groupby([key_lob, key_case], observed=True)[[(group_name, m) for m in months]].sum()
    out = out.astype("int32")
    logger.info(f"group_sum_by_lob_case: group={group_name}, rows_in={len(df)}, groups_out={len(out)}, months={len(months)}")
    return out


def first_target_cph_by_lob_case(df: pd.DataFrame) -> pd.Series:
    plan_cols = [
        (L1_PLAN, "Main LOB"),
        (L1_PLAN, "Case type"),
        (L1_PLAN, "Target CPH"),
    ]
    tmp = df.loc[:, plan_cols].copy()
    tmp.columns = ["LOB", "Case", "CPH"]
    s = tmp.groupby(["LOB", "Case"], observed=True)["CPH"].first().fillna(0).astype("int32")
    s.index = pd.MultiIndex.from_tuples(
        s.index.tolist(),
        names=[(L1_PLAN, "Main LOB"), (L1_PLAN, "Case type")]
    )
    logger.info(f"first_target_cph_by_lob_case: unique (LOB,Case) pairs={len(s)}")
    return s


def get_lobs(df: pd.DataFrame) -> List[str]:
    lob_series = df[(L1_PLAN, "Main LOB")]
    if not isinstance(lob_series.dtype, pd.CategoricalDtype):
        lob_series = lob_series.astype("category")
    lobs = list(lob_series.cat.categories)
    logger.info(f"get_lobs: found LOBs={lobs}")
    return lobs


def common_months_in_order(months_curr: List[str], months_prev: List[str]) -> List[str]:
    prev_set = set(months_prev)
    common = [m for m in months_curr if m in prev_set]
    logger.info(f"common_months_in_order: current={months_curr}, prev={months_prev}, common={common}")
    return common


def build_output_columns(lob: str, months_curr: List[str], months_prior: List[str]) -> pd.MultiIndex:
    cols: List[Tuple[str, str, str, str]] = []
    # Vendor Eligible Forecast (WFM)
    cols.append((lob, L2_VENDOR_ELIGIBLE, "Work Type", ""))
    cols.append((lob, L2_VENDOR_ELIGIBLE, "CPH", ""))
    for m in months_curr: cols.append((lob, L2_VENDOR_ELIGIBLE, m, "Capacity"))
    # Capacity (NTT)
    cols.append((lob, L2_CAPACITY_NTT, "Work Type", ""))
    for m in months_curr:
        cols.append((lob, L2_CAPACITY_NTT, m, "Capacity"))
        cols.append((lob, L2_CAPACITY_NTT, m, "Vendor HC"))
    # Difference
    cols.append((lob, L2_DIFFERENCE, "Work Type", ""))
    for m in months_curr: cols.append((lob, L2_DIFFERENCE, m, "Capacity"))
    # Prior
    cols.append((lob, L2_PRIOR, "Work Type", ""))
    for m in months_prior:
        cols.append((lob, L2_PRIOR, m, "Capacity"))
        cols.append((lob, L2_PRIOR, m, "Vendor HC"))
    # New vs Prior
    cols.append((lob, L2_NEW_VS_PRIOR, "Work Type", ""))
    for m in months_prior:
        cols.append((lob, L2_NEW_VS_PRIOR, m, "Capacity"))
        cols.append((lob, L2_NEW_VS_PRIOR, m, "Vendor HC"))
    mi = pd.MultiIndex.from_tuples(cols)
    logger.debug(f"build_output_columns: lob={lob}, months_curr={len(months_curr)}, months_prior={len(months_prior)}, total_cols={len(mi)}")
    return mi


def zero_block(index: pd.MultiIndex, group_name: str, months: List[str]) -> pd.DataFrame:
    cols = pd.MultiIndex.from_tuples([(group_name, m) for m in months], names=[0, 1])
    df = pd.DataFrame(0, index=index, columns=cols, dtype="int32")
    logger.debug(f"zero_block: group={group_name}, shape={df.shape}")
    return df


def assemble_lob_dataframe(
    lob: str,
    case_types: List[str],
    months_curr: List[str],
    months_prior: List[str],
    fc_block: pd.DataFrame,
    cap_block: pd.DataFrame,
    hc_block: pd.DataFrame,
    cph_series: pd.Series,
    cap_prior_block: pd.DataFrame,
    hc_prior_block: pd.DataFrame,
) -> pd.DataFrame:
    logger.info(f"assemble_lob_dataframe: lob={lob}, cases={len(case_types)}, months_curr={len(months_curr)}, months_prior={len(months_prior)}")
    out_cols = build_output_columns(lob, months_curr, months_prior)
    nrows = len(case_types) + 1
    df_out = pd.DataFrame(index=range(nrows), columns=out_cols)

    # Fill Work Type and CPH
    for g in (L2_VENDOR_ELIGIBLE, L2_CAPACITY_NTT, L2_DIFFERENCE, L2_PRIOR, L2_NEW_VS_PRIOR):
        df_out[(lob, g, "Work Type", "")] = case_types + ["Total"]

    cph_vals = cph_series.reindex(
        pd.MultiIndex.from_product([[lob], case_types], names=cph_series.index.names)
    ).droplevel(0).fillna(0).astype("int32").tolist()
    df_out[(lob, L2_VENDOR_ELIGIBLE, "CPH", "")] = cph_vals + [""]

    def write_month_col(block: pd.DataFrame, l2: str, month: str, leaf: str, col_l1: str):
        vec = block[(col_l1, month)].astype("int32")
        vals = vec.values.tolist()
        df_out[(lob, l2, month, leaf)] = vals + [int(np.sum(vals))]

    for m in months_curr:
        write_month_col(fc_block, L2_VENDOR_ELIGIBLE, m, "Capacity", L1_FORECAST)
        write_month_col(cap_block, L2_CAPACITY_NTT, m, "Capacity", L1_CAPACITY)
        write_month_col(hc_block,  L2_CAPACITY_NTT, m, "Vendor HC", L1_FTE_AVAIL)
        diff_vals = (cap_block[(L1_CAPACITY, m)] - fc_block[(L1_FORECAST, m)]).astype("int32").values.tolist()
        df_out[(lob, L2_DIFFERENCE, m, "Capacity")] = diff_vals + [int(np.sum(diff_vals))]

    tupl_index = pd.MultiIndex.from_product([[lob], case_types], names=fc_block.index.names)
    cap_prior_block = cap_prior_block.reindex(tupl_index).fillna(0).astype("int32")
    hc_prior_block  = hc_prior_block.reindex(tupl_index).fillna(0).astype("int32")

    for m in months_prior:
        write_month_col(cap_prior_block, L2_PRIOR, m, "Capacity", L1_CAPACITY)
        write_month_col(hc_prior_block,  L2_PRIOR, m, "Vendor HC", L1_FTE_AVAIL)
        new_cap_vals = (cap_block[(L1_CAPACITY, m)] - cap_prior_block[(L1_CAPACITY, m)]).astype("int32").values.tolist()
        new_hc_vals  = (hc_block[(L1_FTE_AVAIL, m)] - hc_prior_block[(L1_FTE_AVAIL, m)]).astype("int32").values.tolist()
        df_out[(lob, L2_NEW_VS_PRIOR, m, "Capacity")] = new_cap_vals + [int(np.sum(new_cap_vals))]
        df_out[(lob, L2_NEW_VS_PRIOR, m, "Vendor HC")] = new_hc_vals + [int(np.sum(new_hc_vals))]

    month_set = set(months_curr) | set(months_prior)
    for c in df_out.columns:
        if c[2] in month_set:
            df_out[c] = pd.to_numeric(df_out[c], errors="coerce").fillna(0).astype("int32")

    return df_out


def build_capacity_summary(
    df_curr: pd.DataFrame,
    df_prev: Optional[pd.DataFrame] = None,
    sort_case_types: bool = True,
) -> Dict[str, pd.DataFrame]:
    logger.info("build_capacity_summary: start")
    df_curr = drop_plan_duplicates(df_curr)
    df_curr = fill_and_downcast_month_blocks(df_curr)
    months_curr = extract_months(df_curr, L1_FORECAST)

    agg_fc_c = group_sum_by_lob_case(df_curr, L1_FORECAST)
    agg_hc_c = group_sum_by_lob_case(df_curr, L1_FTE_AVAIL)
    agg_cap_c = group_sum_by_lob_case(df_curr, L1_CAPACITY)
    cph_first = first_target_cph_by_lob_case(df_curr)

    needs_zero_prior = (df_prev is None) or (isinstance(df_prev, pd.DataFrame) and df_prev.empty)
    if needs_zero_prior:
        months_prior = list(months_curr)
        logger.info("build_capacity_summary: previous cycle is None/empty -> using zero prior for ALL current months.")
        agg_cap_p = agg_hc_p = None
    else:
        df_prev = drop_plan_duplicates(df_prev)
        df_prev = fill_and_downcast_month_blocks(df_prev)
        months_prev = extract_months(df_prev, L1_FORECAST)
        months_prior = common_months_in_order(months_curr, months_prev)
        if months_prior:
            agg_hc_p = group_sum_by_lob_case(df_prev, L1_FTE_AVAIL)
            agg_cap_p = group_sum_by_lob_case(df_prev, L1_CAPACITY)
        else:
            logger.info("build_capacity_summary: no common months with previous -> months_prior is empty (prior/new blocks will have no months).")
            agg_cap_p = agg_hc_p = None

    outputs: Dict[str, pd.DataFrame] = {}
    for lob in get_lobs(df_curr):
        try:
            cs = agg_fc_c.loc[(lob, slice(None)), :].index.get_level_values(1).unique().tolist()
        except KeyError:
            logger.info(f"build_capacity_summary: LOB={lob} has no forecast rows; skipping.")
            continue
        if sort_case_types:
            cs = sorted(cs)

        tupl_index = pd.MultiIndex.from_product([[lob], cs], names=agg_fc_c.index.names)
        fc_block = agg_fc_c.reindex(tupl_index).fillna(0).astype("int32")
        cap_block = agg_cap_c.reindex(tupl_index).fillna(0).astype("int32")
        hc_block  = agg_hc_c.reindex(tupl_index).fillna(0).astype("int32")
        cph_series = cph_first.reindex(tupl_index).fillna(0).astype("int32")

        if needs_zero_prior:
            cap_prior_block = zero_block(tupl_index, L1_CAPACITY, months_prior)
            hc_prior_block  = zero_block(tupl_index, L1_FTE_AVAIL, months_prior)
        else:
            if months_prior and ('agg_cap_p' in locals()) and (agg_cap_p is not None):
                cap_prior_block = agg_cap_p.reindex(tupl_index).fillna(0).astype("int32")
                hc_prior_block  = agg_hc_p.reindex(tupl_index).fillna(0).astype("int32")
                cap_prior_block = cap_prior_block.loc[:, [(L1_CAPACITY, m) for m in months_prior]]
                hc_prior_block  = hc_prior_block.loc[:,  [(L1_FTE_AVAIL, m) for m in months_prior]]
            else:
                cap_prior_block = zero_block(tupl_index, L1_CAPACITY, [])
                hc_prior_block  = zero_block(tupl_index, L1_FTE_AVAIL, [])

        out_df = assemble_lob_dataframe(
            lob=lob,
            case_types=cs,
            months_curr=months_curr,
            months_prior=months_prior,
            fc_block=fc_block,
            cap_block=cap_block,
            hc_block=hc_block,
            cph_series=cph_series,
            cap_prior_block=cap_prior_block,
            hc_prior_block=hc_prior_block,
        )
        outputs[lob] = out_df
        logger.info(f"build_capacity_summary: built table for LOB={lob}, shape={out_df.shape}")

    logger.info("build_capacity_summary: done")
    return outputs


def update_summary_data(month:str, year:int):
    if not (month and year):
        logger.error(f"Month and year data not provided")
        return
    file_id = "forecast"
    current_month, current_year =  month, year
    prev_month_info = previous_month_info(current_month, current_year)
    prev_month, prev_year = prev_month_info.get("month_name", month), prev_month_info.get("year", year)
    current_forecast_df = get_processed_dataframe(file_id, current_month, current_year)
    if current_forecast_df is None or current_forecast_df.empty:
        logger.error(f"forecast file not found for month: {month} year: {year}")
        return
    prev_forecast_df = get_processed_dataframe(file_id, prev_month, prev_year)
    summaries_dict = build_capacity_summary(current_forecast_df, prev_forecast_df)
    update_calculated_summary(summaries_dict, month, year)
    
    # return summaries_dict
    # months = ['January']
    # test_export_summaries_to_excel(summaries)
    pass

def update_calculated_summary(summaries: Dict[str, pd.DataFrame], month:str, year:int)-> None:
    try:
        items = []
        for model_type, df in summaries.items():
            raw_data = {
                'df': df,
                'data_model': 'medicare_medicaid_summary',
                'data_model_type': model_type,
                'month': month,
                'year': year,
                'created_by': 'system'
            }
            items.append(raw_data)
            logger.info(f"Processed Data Model: medicare_medicaid_summary | Data Model Type: {model_type} successfully.")
        db_manager = core_utils.get_db_manager(RawData)
        db_manager.bulk_save_raw_data_with_history(items)
    except Exception as e:
        logger.error(f"Error updating raw data: {e}")
        # raise HTTPException(status_code=500, detail=f"Error processing forecast file: Upload error")
    return


def test_export_summaries_to_excel(summaries: Dict[str, pd.DataFrame]):
    output_base = BASE_DIR
    
    folder_path = os.path.join(output_base, "forecast_summaries")
    os.makedirs(folder_path, exist_ok=True)
    for summary_type, df in summaries.items():
        file_path = os.path.join(folder_path, f"{summary_type}.xlsx")
        df.to_excel(file_path)

def test_update_summary_data():
    month = "February"
    year = 2025
    _ = update_summary_data(month, year)
    # test_export_summaries_to_excel(summaries)

if __name__ == "__main__":
    test_update_summary_data()
    pass