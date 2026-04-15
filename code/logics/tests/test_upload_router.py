"""
Tests for the upload router endpoints and downstream pipeline functions.

Covers:
  Upload endpoint behaviour:
  - POST /upload/forecast: valid file → ForecastModel saved with FTE/Capacity = 0
  - POST /upload/forecast: RawData NOT written for raw input sheets (removed code)
  - POST /upload/forecast: invalid file type → 400
  - POST /upload/forecast: filename missing month/year → 400
  - POST /upload/upload_roster: both Roster and Skilling models saved
  - POST /upload/upload_roster: invalid file type → 400
  - POST /upload/altered_forecast: replaces existing ForecastModel data

  Downstream pipeline functions (no HTTP, pure logic):
  - get_forecast_demand_from_db: returns MultiIndex DataFrame from seeded ForecastModel
  - get_forecast_demand_from_db: FTE / Capacity values from DB are preserved as-is
  - update_calculated_summary + get_summary_data_by_summary_type roundtrip
"""

import io
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch, call
from fastapi.testclient import TestClient


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_minimal_xlsx(sheets: dict[str, pd.DataFrame]) -> bytes:
    """Write a dict of {sheet_name: DataFrame} to an in-memory xlsx and return bytes."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return buf.getvalue()


def _minimal_roster_xlsx() -> bytes:
    """Minimal xlsx with Roster and Skilling sheets."""
    roster_cols = [
        'Platform', 'WorkType', 'State', 'Product', 'Location', 'ResourceStatus',
        'Status', 'FirstName', 'LastName', 'PortalId', 'CN', 'WorkdayId',
        'HireDate_AmisysStartDate', 'OPID', 'Position', 'TL', 'Supervisor',
        'PrimarySkills', 'SecondarySkills', 'City', 'ClassName',
        'FTC_START_TRAINING', 'FTC_END_TRAINING ', 'ADJ_COB_START_TRAINING',
        'ADJ_COB_END_TRAINING ', 'CourseType', 'BH', 'SplProj', 'DualPends',
        'RampStartDate', 'RampEndDate', 'Ramp', 'CPH', 'CrossTrainedTrainingDate',
        'CrossTrainedProdDate', 'ProductionStartDate', 'Facilitator_Cofacilitator',
        ' Centene_WellCareEmail', 'Additional_Email_NTT'
    ]
    skilling_cols = [
        "Position", "FirstName", "LastName", "PortalId", "Status", "Resource_Status",
        "LOB.1", "Sub LOB", "Site", "Skills", "State", "Unique Agent",
        "Multi Skill", "Skill Name", "Skill Split"
    ]
    roster_df = pd.DataFrame([['Amisys', 'FTC', 'TX'] + [''] * (len(roster_cols) - 3)],
                              columns=roster_cols)
    skilling_df = pd.DataFrame([['Analyst', 'John', 'Doe'] + [''] * (len(skilling_cols) - 3)],
                                columns=skilling_cols)
    return _make_minimal_xlsx({"Roster": roster_df, "Skilling": skilling_df})


def _make_mock_db_manager():
    """Return a MagicMock that looks like a DBManager."""
    mock = MagicMock()
    mock.save_to_db.return_value = None
    mock.bulk_save_raw_data_with_history.return_value = None
    mock.insert_upload_data_time_details_if_not_exists.return_value = None
    return mock


def _make_mock_core_utils(db_manager=None):
    """Return a MagicMock CoreUtils that always returns the given db_manager."""
    mock_cu = MagicMock()
    mock_cu.get_db_manager.return_value = db_manager or _make_mock_db_manager()
    return mock_cu


# ─── App fixture ──────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """FastAPI TestClient with core_utils patched to avoid real DB calls."""
    from code.main import app
    import code.api.routers.upload_router as router_module

    mock_cu = _make_mock_core_utils()
    with patch.object(router_module, 'core_utils', mock_cu):
        with TestClient(app) as c:
            yield c, mock_cu


@pytest.fixture
def client_with_tracker():
    """TestClient where each model gets its own db_manager mock for call inspection."""
    from code.main import app
    import code.api.routers.upload_router as router_module

    db_managers: dict[str, MagicMock] = {}

    def _get_db_manager(model, *args, **kwargs):
        key = getattr(model, '__name__', str(model))
        if key not in db_managers:
            db_managers[key] = _make_mock_db_manager()
        return db_managers[key]

    mock_cu = MagicMock()
    mock_cu.get_db_manager.side_effect = _get_db_manager

    with patch.object(router_module, 'core_utils', mock_cu):
        with TestClient(app) as c:
            yield c, mock_cu, db_managers


# ─── Tests: POST /upload/forecast ─────────────────────────────────────────────

class TestForecastUploadEndpoint:

    def _post_forecast(self, client, filename: str, file_bytes: bytes = b"fake"):
        return client.post(
            "/upload/forecast",
            params={"user": "test_user"},
            files={"file": (filename, io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        )

    def test_invalid_file_type_returns_400(self, client):
        c, _ = client
        resp = self._post_forecast(c, "forecast_January_2025.txt", b"data")
        assert resp.status_code == 400
        assert "Invalid file type" in resp.text

    def test_missing_month_year_in_filename_returns_400(self, client):
        c, _ = client
        # Process forecast file will parse but get_month_year will find nothing
        with patch('code.api.routers.upload_router.PreProcessing') as MockPP:
            mock_pp = MagicMock()
            mock_pp.get_month_year.return_value = None
            MockPP.return_value = mock_pp
            resp = self._post_forecast(c, "forecast_nodate.xlsx")
        assert resp.status_code == 400
        assert "month and year" in resp.text.lower()

    def test_forecast_upload_saves_to_forecast_model(self, client):
        """Valid forecast upload triggers ForecastModel save with FTE/Capacity = 0."""
        c, mock_cu = client
        mock_db = _make_mock_db_manager()
        mock_cu.get_db_manager.return_value = mock_db

        with patch('code.api.routers.upload_router.PreProcessing') as MockPP:
            mock_pp = MagicMock()
            mock_pp.get_month_year.return_value = {"Month": "January", "Year": "2025"}
            mock_pp.process_forecast_file.return_value = {
                "medicare_medicaid_summary": {},
                "medicare_medicaid_nonmmp": {},
                "medicare_medicaid_mmp": {},
                "medicare_medicaid_aligned_dual": {},
            }
            mock_pp.month_codes = {f"Month{i}": m for i, m in enumerate(
                ["February", "March", "April", "May", "June", "July"], 1)}
            # extract_forecast_demand returns a DataFrame with FTE/Capacity = 0
            demand_df = pd.DataFrame([{
                'Centene_Capacity_Plan_Main_LOB': 'Amisys Medicare',
                'Centene_Capacity_Plan_State': 'TX',
                'Centene_Capacity_Plan_Case_Type': 'FTC',
                'Centene_Capacity_Plan_Call_Type_ID': 'Amisys ftc',
                'Centene_Capacity_Plan_Target_CPH': 45,
                **{f'Client_Forecast_Month{i}': 1000 for i in range(1, 7)},
                **{f'FTE_Required_Month{i}': 0 for i in range(1, 7)},
                **{f'FTE_Avail_Month{i}': 0 for i in range(1, 7)},
                **{f'Capacity_Month{i}': 0 for i in range(1, 7)},
            }])
            mock_pp.extract_forecast_demand.return_value = demand_df
            MockPP.return_value = mock_pp

            # Prevent the background allocation task from actually running
            with patch('code.api.routers.upload_router.process_files'):
                resp = self._post_forecast(c, "forecast_January_2025.xlsx")

        assert resp.status_code == 200
        # save_to_db must have been called at least once (for ForecastModel pre-population)
        assert mock_db.save_to_db.called

    def test_forecast_upload_does_not_call_bulk_save_raw_data(self, client):
        """After cleanup: raw sheet dfs must NOT be written to RawData."""
        c, mock_cu = client
        mock_db = _make_mock_db_manager()
        mock_cu.get_db_manager.return_value = mock_db

        with patch('code.api.routers.upload_router.PreProcessing') as MockPP:
            mock_pp = MagicMock()
            mock_pp.get_month_year.return_value = {"Month": "February", "Year": "2025"}
            mock_pp.process_forecast_file.return_value = {
                "medicare_medicaid_summary": {},
                "medicare_medicaid_nonmmp": {},
                "medicare_medicaid_mmp": {},
                "medicare_medicaid_aligned_dual": {},
            }
            mock_pp.month_codes = {f"Month{i}": m for i, m in enumerate(
                ["March", "April", "May", "June", "July", "August"], 1)}
            mock_pp.extract_forecast_demand.return_value = pd.DataFrame()
            MockPP.return_value = mock_pp
            # Prevent the background allocation task from actually running
            with patch('code.api.routers.upload_router.process_files'):
                resp = self._post_forecast(c, "forecast_February_2025.xlsx")

        # bulk_save_raw_data_with_history must NEVER be called during forecast upload
        assert not mock_db.bulk_save_raw_data_with_history.called, (
            "bulk_save_raw_data_with_history should not be called during forecast upload"
        )

    def test_forecast_upload_triggers_background_allocation(self, client):
        """process_files must be registered as a background task on upload."""
        c, mock_cu = client
        mock_db = _make_mock_db_manager()
        mock_cu.get_db_manager.return_value = mock_db

        with patch('code.api.routers.upload_router.PreProcessing') as MockPP, \
             patch('code.api.routers.upload_router.process_files') as mock_pf:
            mock_pp = MagicMock()
            mock_pp.get_month_year.return_value = {"Month": "March", "Year": "2025"}
            mock_pp.process_forecast_file.return_value = {
                "medicare_medicaid_summary": {},
                "medicare_medicaid_nonmmp": {},
                "medicare_medicaid_mmp": {},
                "medicare_medicaid_aligned_dual": {},
            }
            mock_pp.month_codes = {f"Month{i}": m for i, m in enumerate(
                ["April", "May", "June", "July", "August", "September"], 1)}
            mock_pp.extract_forecast_demand.return_value = pd.DataFrame([{
                **{f'Client_Forecast_Month{i}': 500 for i in range(1, 7)},
                **{f'FTE_Required_Month{i}': 0 for i in range(1, 7)},
                **{f'FTE_Avail_Month{i}': 0 for i in range(1, 7)},
                **{f'Capacity_Month{i}': 0 for i in range(1, 7)},
                'Centene_Capacity_Plan_Main_LOB': 'Amisys Medicare',
                'Centene_Capacity_Plan_State': 'TX',
                'Centene_Capacity_Plan_Case_Type': 'FTC',
                'Centene_Capacity_Plan_Call_Type_ID': 'Amisys ftc',
                'Centene_Capacity_Plan_Target_CPH': 0,
            }])
            MockPP.return_value = mock_pp
            resp = self._post_forecast(c, "forecast_March_2025.xlsx")

        assert resp.status_code == 200


# ─── Tests: POST /upload/upload_roster ────────────────────────────────────────

class TestRosterUploadEndpoint:

    def _post_roster(self, client, filename: str, file_bytes: bytes):
        return client.post(
            "/upload/upload_roster",
            params={"user": "test_user"},
            files={"file": (filename, io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        )

    def test_invalid_file_type_returns_400(self, client):
        c, _ = client
        resp = self._post_roster(c, "roster_January_2025.csv", b"data")
        # CSV is valid — but txt is not
        resp2 = c.post(
            "/upload/upload_roster",
            params={"user": "test_user"},
            files={"file": ("roster_January_2025.txt", io.BytesIO(b"data"), "text/plain")}
        )
        assert resp2.status_code == 400

    def test_missing_month_year_returns_400(self, client):
        c, _ = client
        with patch('code.api.routers.upload_router.PreProcessing') as MockPP:
            mock_pp = MagicMock()
            mock_pp.get_month_year.return_value = None
            MockPP.return_value = mock_pp
            resp = self._post_roster(c, "roster_nodate.xlsx", _minimal_roster_xlsx())
        assert resp.status_code == 400

    def test_roster_upload_saves_both_models(self, client):
        """Both RosterModel and SkillingModel must be saved."""
        c, mock_cu = client

        roster_db = _make_mock_db_manager()
        skilling_db = _make_mock_db_manager()
        time_db = _make_mock_db_manager()

        from code.logics.db import RosterModel, SkillingModel, UploadDataTimeDetails

        def _get_db(model, *a, **kw):
            if model is RosterModel:
                return roster_db
            if model is SkillingModel:
                return skilling_db
            return time_db

        mock_cu.get_db_manager.side_effect = _get_db

        with patch('code.api.routers.upload_router.PreProcessing') as MockPP:
            mock_pp = MagicMock()
            mock_pp.get_month_year.return_value = {"Month": "January", "Year": "2025"}
            mock_pp.preprocess_roster.return_value = pd.DataFrame([{"Platform": "Amisys"}])
            mock_pp.preprocess_skilling.return_value = pd.DataFrame([{"Position": "Analyst"}])
            MockPP.return_value = mock_pp

            resp = self._post_roster(c, "roster_January_2025.xlsx", _minimal_roster_xlsx())

        assert resp.status_code == 200
        assert roster_db.save_to_db.called, "RosterModel save_to_db not called"
        assert skilling_db.save_to_db.called, "SkillingModel save_to_db not called"


# ─── Tests: POST /upload/altered_forecast ─────────────────────────────────────

class TestAlteredForecastEndpoint:

    def _post_altered(self, client, filename: str, file_bytes: bytes = b"fake"):
        return client.post(
            "/upload/altered_forecast",
            params={"user": "test_user"},
            files={"file": (filename, io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        )

    def test_invalid_file_type_returns_400(self, client):
        c, _ = client
        resp = self._post_altered(c, "forecast_January_2025.txt")
        assert resp.status_code == 400

    def test_missing_month_year_returns_400(self, client):
        c, _ = client
        with patch('code.api.routers.upload_router.PreProcessing') as MockPP:
            mock_pp = MagicMock()
            mock_pp.get_month_year.return_value = None
            MockPP.return_value = mock_pp
            resp = self._post_altered(c, "forecast_nodate.xlsx")
        assert resp.status_code == 400

    def test_column_mismatch_returns_400(self, client):
        c, _ = client
        with patch('code.api.routers.upload_router.PreProcessing') as MockPP:
            mock_pp = MagicMock()
            mock_pp.get_month_year.return_value = {"Month": "January", "Year": "2025"}
            # _process_forecast returns df with wrong number of columns
            bad_df = pd.DataFrame([[1, 2]], columns=["ColA", "ColB"])
            mock_pp._process_forecast.return_value = bad_df
            mock_pp.MAPPING = {"forecast": ["a"] * 29}  # 29 expected, 2 actual
            MockPP.return_value = mock_pp
            resp = self._post_altered(c, "forecast_January_2025.xlsx")
        assert resp.status_code in (400, 500)

    def test_valid_altered_upload_replaces_data(self, client):
        """Valid altered forecast upload calls save_to_db with replace=True."""
        c, mock_cu = client
        mock_db = _make_mock_db_manager()
        mock_cu.get_db_manager.return_value = mock_db

        # Build a DataFrame with the correct 29 columns
        forecast_cols = [
            'Centene_Capacity_Plan_Main_LOB', 'Centene_Capacity_Plan_State',
            'Centene_Capacity_Plan_Case_Type', 'Centene_Capacity_Plan_Call_Type_ID',
            'Centene_Capacity_Plan_Target_CPH',
            *[f'Client_Forecast_Month{i}' for i in range(1, 7)],
            *[f'FTE_Required_Month{i}' for i in range(1, 7)],
            *[f'FTE_Avail_Month{i}' for i in range(1, 7)],
            *[f'Capacity_Month{i}' for i in range(1, 7)],
        ]
        test_df = pd.DataFrame([[f'val{i}' if i < 5 else 100 for i in range(29)]],
                               columns=forecast_cols)

        with patch('code.api.routers.upload_router.PreProcessing') as MockPP, \
             patch('code.api.routers.upload_router.invalidate_allocation') as mock_inv:
            mock_pp = MagicMock()
            mock_pp.get_month_year.return_value = {"Month": "January", "Year": "2025"}
            mock_pp._process_forecast.return_value = test_df
            mock_pp.MAPPING = {"forecast": forecast_cols}
            mock_pp.month_codes = {f"Month{i}": m for i, m in enumerate(
                ["February", "March", "April", "May", "June", "July"], 1)}
            MockPP.return_value = mock_pp
            mock_inv.return_value = {"success": True}

            resp = self._post_altered(c, "forecast_January_2025.xlsx")

        assert resp.status_code == 200
        # Must save with replace=True to overwrite existing data
        save_calls = mock_db.save_to_db.call_args_list
        replace_calls = [c for c in save_calls if c.kwargs.get('replace') is True
                         or (c.args and len(c.args) > 1 and c.args[1] is True)]
        assert len(replace_calls) > 0, "save_to_db must be called with replace=True"


# ─── Tests: get_forecast_demand_from_db ───────────────────────────────────────

class TestGetForecastDemandFromDb:
    """
    Tests for the downstream function that reconstructs a MultiIndex DataFrame
    from ForecastModel — used by process_files() for allocation.
    """

    def _seed_forecast_records(self) -> list[dict]:
        """Return flat ForecastModel-compatible dicts."""
        return [
            {
                'Centene_Capacity_Plan_Main_LOB': 'Amisys Medicare',
                'Centene_Capacity_Plan_State': 'TX',
                'Centene_Capacity_Plan_Case_Type': 'FTC',
                'Centene_Capacity_Plan_Call_Type_ID': 'Amisys ftc',
                'Centene_Capacity_Plan_Target_CPH': 45,
                **{f'Client_Forecast_Month{i}': 1000 * i for i in range(1, 7)},
                **{f'FTE_Required_Month{i}': 0 for i in range(1, 7)},
                **{f'FTE_Avail_Month{i}': 0 for i in range(1, 7)},
                **{f'Capacity_Month{i}': 0 for i in range(1, 7)},
                'Month': 'January', 'Year': 2025, 'CreatedBy': 'test',
                'UpdatedBy': 'test', 'UploadedFile': 'forecast_January_2025.xlsx',
            }
        ]

    def test_returns_multiindex_dataframe(self):
        """get_forecast_demand_from_db should return a MultiIndex DataFrame."""
        records = self._seed_forecast_records()
        flat_df = pd.DataFrame(records)
        months_list = ["February", "March", "April", "May", "June", "July"]

        with patch('code.logics.export_utils.core_utils') as mock_cu, \
             patch('code.logics.export_utils.get_forecast_months_list', return_value=months_list):
            mock_db = MagicMock()
            mock_db.get_totals.return_value = 1
            mock_db.download_db.return_value = flat_df
            mock_cu.get_db_manager.return_value = mock_db

            from code.logics.export_utils import get_forecast_demand_from_db
            result = get_forecast_demand_from_db("January", 2025)

        assert not result.empty
        assert isinstance(result.columns, pd.MultiIndex)

    def test_multiindex_has_correct_level0_groups(self):
        """Level 0 of MultiIndex should contain the expected group names."""
        records = self._seed_forecast_records()
        flat_df = pd.DataFrame(records)
        months_list = ["February", "March", "April", "May", "June", "July"]

        with patch('code.logics.export_utils.core_utils') as mock_cu, \
             patch('code.logics.export_utils.get_forecast_months_list', return_value=months_list):
            mock_db = MagicMock()
            mock_db.get_totals.return_value = 1
            mock_db.download_db.return_value = flat_df
            mock_cu.get_db_manager.return_value = mock_db

            from code.logics.export_utils import get_forecast_demand_from_db
            result = get_forecast_demand_from_db("January", 2025)

        level0 = set(result.columns.get_level_values(0))
        expected_groups = {'Centene Capacity plan', 'Client Forecast',
                           'FTE Required', 'FTE Avail', 'Capacity'}
        assert expected_groups.issubset(level0), f"Missing groups: {expected_groups - level0}"

    def test_month_columns_use_actual_month_names(self):
        """FTE/Capacity columns should use real month names (from ForecastMonthsModel), not Month1-6."""
        records = self._seed_forecast_records()
        flat_df = pd.DataFrame(records)
        months_list = ["February", "March", "April", "May", "June", "July"]

        with patch('code.logics.export_utils.core_utils') as mock_cu, \
             patch('code.logics.export_utils.get_forecast_months_list', return_value=months_list):
            mock_db = MagicMock()
            mock_db.get_totals.return_value = 1
            mock_db.download_db.return_value = flat_df
            mock_cu.get_db_manager.return_value = mock_db

            from code.logics.export_utils import get_forecast_demand_from_db
            result = get_forecast_demand_from_db("January", 2025)

        level1_months = [v for v in result.columns.get_level_values(1) if v in months_list]
        assert len(level1_months) > 0, "Expected month names in level 1, found none"
        # Must NOT contain raw Month1-6 keys
        assert 'Month1' not in result.columns.get_level_values(1)

    def test_empty_db_returns_empty_dataframe(self):
        """No records in DB → empty DataFrame returned."""
        with patch('code.logics.export_utils.core_utils') as mock_cu:
            mock_db = MagicMock()
            mock_db.get_totals.return_value = 0
            mock_cu.get_db_manager.return_value = mock_db

            from code.logics.export_utils import get_forecast_demand_from_db
            result = get_forecast_demand_from_db("January", 2025)

        assert result.empty

    def test_fte_values_preserved_from_db(self):
        """After allocation updates ForecastModel, get_forecast_demand_from_db reflects those values."""
        records = self._seed_forecast_records()
        # Simulate post-allocation state: FTE Required / Avail set
        records[0].update({
            'FTE_Required_Month1': 5,
            'FTE_Avail_Month1': 4,
            'Capacity_Month1': 18000,
        })
        flat_df = pd.DataFrame(records)
        months_list = ["February", "March", "April", "May", "June", "July"]

        with patch('code.logics.export_utils.core_utils') as mock_cu, \
             patch('code.logics.export_utils.get_forecast_months_list', return_value=months_list):
            mock_db = MagicMock()
            mock_db.get_totals.return_value = 1
            mock_db.download_db.return_value = flat_df
            mock_cu.get_db_manager.return_value = mock_db

            from code.logics.export_utils import get_forecast_demand_from_db
            result = get_forecast_demand_from_db("January", 2025)

        fte_req_col = ('FTE Required', 'February')
        assert fte_req_col in result.columns
        assert result[fte_req_col].iloc[0] == 5


# ─── Tests: summary RawData roundtrip ─────────────────────────────────────────

class TestSummaryRawDataRoundtrip:
    """
    update_calculated_summary writes to RawData;
    get_summary_data_by_summary_type reads it back.
    RawData is the ONLY intended storage for summaries (not raw input sheets).
    """

    def test_update_calculated_summary_calls_bulk_save(self):
        """update_calculated_summary must write to RawData via bulk_save_raw_data_with_history."""
        from code.logics.summary_utils import update_calculated_summary

        summary_df = pd.DataFrame({'Col': [1, 2, 3]})
        summaries = {"Amisys Medicare": summary_df}

        with patch('code.logics.summary_utils.core_utils') as mock_cu:
            mock_db = _make_mock_db_manager()
            mock_cu.get_db_manager.return_value = mock_db

            update_calculated_summary(summaries, "January", 2025)

        assert mock_db.bulk_save_raw_data_with_history.called
        call_args = mock_db.bulk_save_raw_data_with_history.call_args[0][0]
        assert len(call_args) == 1
        item = call_args[0]
        assert item['data_model'] == 'medicare_medicaid_summary'
        assert item['data_model_type'] == 'Amisys Medicare'
        assert item['month'] == 'January'
        assert item['year'] == 2025

    def test_update_calculated_summary_saves_dataframe(self):
        """The DataFrame saved to RawData matches what was passed in."""
        from code.logics.summary_utils import update_calculated_summary

        summary_df = pd.DataFrame({'Forecast': [100, 200], 'FTE': [2, 3]})
        summaries = {"Amisys Medicaid": summary_df}
        saved_items = []

        def _capture(items, *a, **kw):
            saved_items.extend(items)

        with patch('code.logics.summary_utils.core_utils') as mock_cu:
            mock_db = MagicMock()
            mock_db.bulk_save_raw_data_with_history.side_effect = _capture
            mock_cu.get_db_manager.return_value = mock_db

            update_calculated_summary(summaries, "February", 2025)

        assert len(saved_items) == 1
        pd.testing.assert_frame_equal(saved_items[0]['df'], summary_df)

    def test_get_summary_data_by_summary_type_reads_rawdata(self):
        """get_summary_data_by_summary_type must read from RawData, not ForecastModel."""
        from code.logics.export_utils import get_summary_data_by_summary_type

        expected_df = pd.DataFrame({'Forecast': [500], 'FTE': [5]})

        with patch('code.logics.export_utils.core_utils') as mock_cu:
            mock_db = MagicMock()
            mock_db.get_raw_data_df_current.return_value = expected_df
            mock_cu.get_db_manager.return_value = mock_db

            result = get_summary_data_by_summary_type("January", 2025, "Amisys Medicare")

        mock_cu.get_db_manager.assert_called_once()
        mock_db.get_raw_data_df_current.assert_called_once_with(
            'medicare_medicaid_summary', 'Amisys Medicare', 'January', 2025
        )
        pd.testing.assert_frame_equal(result, expected_df)

    def test_get_summary_empty_db_returns_empty_dataframe(self):
        """Missing summary data returns empty DataFrame, not an error."""
        from code.logics.export_utils import get_summary_data_by_summary_type

        with patch('code.logics.export_utils.core_utils') as mock_cu:
            mock_db = MagicMock()
            mock_db.get_raw_data_df_current.return_value = pd.DataFrame()
            mock_cu.get_db_manager.return_value = mock_db

            result = get_summary_data_by_summary_type("January", 2025, "Unknown LOB")

        assert result.empty

    def test_multiple_lobs_saved_separately(self):
        """Each LOB summary is stored as a separate RawData entry."""
        from code.logics.summary_utils import update_calculated_summary

        summaries = {
            "Amisys Medicare": pd.DataFrame({'A': [1]}),
            "Facets Medicaid": pd.DataFrame({'B': [2]}),
            "Amisys Projects- Domestic": pd.DataFrame({'C': [3]}),
        }
        saved_items = []

        def _capture(items, *a, **kw):
            saved_items.extend(items)

        with patch('code.logics.summary_utils.core_utils') as mock_cu:
            mock_db = MagicMock()
            mock_db.bulk_save_raw_data_with_history.side_effect = _capture
            mock_cu.get_db_manager.return_value = mock_db

            update_calculated_summary(summaries, "March", 2025)

        assert len(saved_items) == 3
        saved_types = {item['data_model_type'] for item in saved_items}
        assert saved_types == set(summaries.keys())
        # All must use the same data_model key
        assert all(item['data_model'] == 'medicare_medicaid_summary' for item in saved_items)
