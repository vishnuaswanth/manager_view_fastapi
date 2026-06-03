"""
Tests for ForecastMonthsModel upsert logic in DBManager.

Covers:
  - upsert_forecast_months: INSERT path (new filename → creates record)
  - upsert_forecast_months: UPDATE path (existing filename → updates Month1-6, CreatedBy, CreatedDateTime)
  - upsert_forecast_months: UPDATE path picks the latest when duplicates pre-exist
  - upsert_forecast_months: different filenames create separate records
  - get_forecast_months_list: returns data from the latest record (by CreatedDateTime)
"""

import time
import pytest
from datetime import datetime, timedelta
from sqlmodel import SQLModel, create_engine
from sqlalchemy.orm import sessionmaker

from code.logics.db import DBManager, ForecastMonthsModel


SQLITE_URL = "sqlite://"  # in-memory, discarded after each test


@pytest.fixture
def db_manager():
    engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    mgr = DBManager.__new__(DBManager)
    mgr.engine = engine
    mgr.SessionLocal = SessionLocal
    mgr.Model = ForecastMonthsModel
    mgr.skip = 0
    mgr.limit = 0
    mgr.select_columns = None
    mgr.METRIC_COLUMNS = []

    yield mgr

    SQLModel.metadata.drop_all(bind=engine)


def _sample_data(**overrides) -> dict:
    base = {
        "Month1": "January", "Month2": "February", "Month3": "March",
        "Month4": "April",   "Month5": "May",      "Month6": "June",
        "UploadedFile": "forecast_Jan_2025.xlsx",
        "CreatedBy": "user_a",
    }
    base.update(overrides)
    return base


class TestUpsertForecastMonths:

    def test_insert_creates_new_record(self, db_manager):
        db_manager.upsert_forecast_months(_sample_data())

        with db_manager.SessionLocal() as session:
            records = session.query(ForecastMonthsModel).all()

        assert len(records) == 1
        assert records[0].Month1 == "January"
        assert records[0].UploadedFile == "forecast_Jan_2025.xlsx"
        assert records[0].CreatedBy == "user_a"

    def test_update_overwrites_existing_record(self, db_manager):
        db_manager.upsert_forecast_months(_sample_data())

        updated = _sample_data(
            Month1="July", Month2="August", Month3="September",
            Month4="October", Month5="November", Month6="December",
            CreatedBy="user_b"
        )
        db_manager.upsert_forecast_months(updated)

        with db_manager.SessionLocal() as session:
            records = session.query(ForecastMonthsModel).all()

        assert len(records) == 1, "Must not create a duplicate row for the same filename"
        assert records[0].Month1 == "July"
        assert records[0].Month6 == "December"
        assert records[0].CreatedBy == "user_b"

    def test_update_refreshes_created_datetime(self, db_manager):
        db_manager.upsert_forecast_months(_sample_data())

        with db_manager.SessionLocal() as session:
            original_dt = session.query(ForecastMonthsModel).first().CreatedDateTime

        time.sleep(0.05)  # ensure the clock advances
        db_manager.upsert_forecast_months(_sample_data(CreatedBy="user_b"))

        with db_manager.SessionLocal() as session:
            updated_dt = session.query(ForecastMonthsModel).first().CreatedDateTime

        assert updated_dt > original_dt

    def test_all_six_month_fields_updated(self, db_manager):
        db_manager.upsert_forecast_months(_sample_data())

        new_months = {f"Month{i}": f"NewMonth{i}" for i in range(1, 7)}
        db_manager.upsert_forecast_months(_sample_data(**new_months))

        with db_manager.SessionLocal() as session:
            record = session.query(ForecastMonthsModel).first()

        for i in range(1, 7):
            assert getattr(record, f"Month{i}") == f"NewMonth{i}"

    def test_different_filenames_create_separate_records(self, db_manager):
        db_manager.upsert_forecast_months(_sample_data(UploadedFile="file_A.xlsx"))
        db_manager.upsert_forecast_months(_sample_data(UploadedFile="file_B.xlsx"))

        with db_manager.SessionLocal() as session:
            records = session.query(ForecastMonthsModel).all()

        assert len(records) == 2
        filenames = {r.UploadedFile for r in records}
        assert filenames == {"file_A.xlsx", "file_B.xlsx"}

    def test_update_targets_latest_when_duplicates_exist(self, db_manager):
        """If legacy duplicate rows exist (same filename), the newest one gets updated."""
        older_dt = datetime(2025, 1, 1, 10, 0, 0)
        newer_dt = datetime(2025, 6, 1, 10, 0, 0)

        with db_manager.SessionLocal() as session:
            session.add(ForecastMonthsModel(
                Month1="Jan", Month2="Feb", Month3="Mar",
                Month4="Apr", Month5="May", Month6="Jun",
                UploadedFile="dup_file.xlsx", CreatedBy="old_user",
                CreatedDateTime=older_dt
            ))
            session.add(ForecastMonthsModel(
                Month1="Jul", Month2="Aug", Month3="Sep",
                Month4="Oct", Month5="Nov", Month6="Dec",
                UploadedFile="dup_file.xlsx", CreatedBy="newer_user",
                CreatedDateTime=newer_dt
            ))
            session.commit()

        db_manager.upsert_forecast_months(_sample_data(
            UploadedFile="dup_file.xlsx", CreatedBy="final_user"
        ))

        with db_manager.SessionLocal() as session:
            updated = session.query(ForecastMonthsModel).filter(
                ForecastMonthsModel.CreatedBy == "final_user"
            ).first()
            old_untouched = session.query(ForecastMonthsModel).filter(
                ForecastMonthsModel.CreatedBy == "old_user"
            ).first()

        assert updated is not None, "Newest record should have been updated"
        assert old_untouched is not None, "Older duplicate should remain untouched"


class TestFetchLatestByCreatedDateTime:

    def test_get_forecast_months_list_returns_latest(self, db_manager):
        """get_forecast_months_list with filename returns months from the newest record."""
        older_dt = datetime(2025, 1, 1)
        newer_dt = datetime(2025, 6, 1)

        with db_manager.SessionLocal() as session:
            session.add(ForecastMonthsModel(
                Month1="Jan", Month2="Feb", Month3="Mar",
                Month4="Apr", Month5="May", Month6="Jun",
                UploadedFile="test.xlsx", CreatedBy="u1",
                CreatedDateTime=older_dt
            ))
            session.add(ForecastMonthsModel(
                Month1="Jul", Month2="Aug", Month3="Sep",
                Month4="Oct", Month5="Nov", Month6="Dec",
                UploadedFile="test.xlsx", CreatedBy="u2",
                CreatedDateTime=newer_dt
            ))
            session.commit()

        result = db_manager.get_forecast_months_list(
            month="June", year=2025, filename="test.xlsx"
        )

        assert result[0] == "Jul", "Should return months from the newest record"
        assert result[5] == "Dec"

    def test_get_forecast_months_list_missing_filename_returns_nones(self, db_manager):
        # When a filename is provided but no record exists, the method returns
        # [None, None, None, None, None, None] (existing behaviour — record not found,
        # getattr on None produces None for each Month field).
        result = db_manager.get_forecast_months_list(
            month="March", year=2025, filename="nonexistent.xlsx"
        )
        assert result == [None] * 6

    def test_get_forecast_months_list_missing_month_returns_empty(self, db_manager):
        result = db_manager.get_forecast_months_list(month="", year=2025)
        assert result == []
