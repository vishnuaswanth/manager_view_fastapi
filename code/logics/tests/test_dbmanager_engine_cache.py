"""
Tests for the DBManager engine/connection-pool cache (code.logics.db._get_or_create_engine).

Covers:
  - Repeated DBManager(...) construction with the same database_url shares one Engine/SessionLocal
  - Different database_url values get distinct Engines
  - Per-instance fields (Model/limit/skip/select_columns) stay independent even when engine is shared
  - metadata.create_all runs at most once per unique database_url
  - Concurrent first-time construction against a cold cache still creates only one Engine
  - Bare in-memory sqlite URLs are rejected (would silently share state across unrelated callers)
  - connect_args only includes check_same_thread for sqlite URLs
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, MagicMock

import pytest
from sqlmodel import SQLModel

from code.logics import db as db_module
from code.logics.db import DBManager, ForecastModel


@pytest.fixture(autouse=True)
def clean_engine_cache_entries():
    """Track which cache keys this test adds and remove them afterward, so tests don't leak
    state into each other via the module-level, process-lifetime _engine_cache."""
    keys_before = set(db_module._engine_cache.keys())
    yield
    keys_after = set(db_module._engine_cache.keys())
    for key in keys_after - keys_before:
        db_module._engine_cache.pop(key, None)


def _temp_sqlite_url(tmp_path, name: str) -> str:
    return f"sqlite:///{tmp_path / name}"


def test_dbmanager_reuses_engine_for_same_url(tmp_path):
    url = _temp_sqlite_url(tmp_path, "shared.db")

    m1 = DBManager(url, ForecastModel, 0, 0, None)
    m2 = DBManager(url, ForecastModel, 10, 5, None)

    assert m1.engine is m2.engine
    assert m1.SessionLocal is m2.SessionLocal
    # Per-instance fields must still differ correctly despite the shared engine
    assert m1.limit == 0 and m2.limit == 10
    assert m1.skip == 0 and m2.skip == 5


def test_dbmanager_creates_distinct_engine_for_different_url(tmp_path):
    url1 = _temp_sqlite_url(tmp_path, "one.db")
    url2 = _temp_sqlite_url(tmp_path, "two.db")

    m1 = DBManager(url1, ForecastModel, 0, 0, None)
    m3 = DBManager(url2, ForecastModel, 0, 0, None)

    assert m3.engine is not m1.engine


def test_dbmanager_create_all_called_once_per_url(tmp_path):
    url = _temp_sqlite_url(tmp_path, "create_all_once.db")

    with patch.object(SQLModel.metadata, "create_all", wraps=SQLModel.metadata.create_all) as spy:
        DBManager(url, ForecastModel, 0, 0, None)
        DBManager(url, ForecastModel, 5, 1, None)
        DBManager(url, ForecastModel, 9, 2, None)

    assert spy.call_count == 1


def test_dbmanager_concurrent_first_call_creates_one_engine(tmp_path):
    url = _temp_sqlite_url(tmp_path, "concurrent.db")

    def build():
        return DBManager(url, ForecastModel, 0, 0, None)

    with ThreadPoolExecutor(max_workers=20) as pool:
        managers = list(pool.map(lambda _: build(), range(20)))

    engines = {id(m.engine) for m in managers}
    assert len(engines) == 1
    assert url in db_module._engine_cache


def test_dbmanager_rejects_bare_inmemory_sqlite_url():
    with pytest.raises(ValueError):
        DBManager("sqlite://", ForecastModel, 0, 0, None)

    with pytest.raises(ValueError):
        DBManager("sqlite:///:memory:", ForecastModel, 0, 0, None)


def test_dbmanager_sqlite_connect_args_only_for_sqlite():
    fake_engine = MagicMock()
    fake_engine.dialect.name = "fake"

    with patch.object(db_module, "create_engine", return_value=fake_engine) as mock_create_engine, \
         patch.object(SQLModel.metadata, "create_all"), \
         patch.object(db_module, "sessionmaker"):

        db_module._get_or_create_engine("sqlite:///some/fake/path.db")
        sqlite_kwargs = mock_create_engine.call_args.kwargs["connect_args"]
        assert sqlite_kwargs == {"check_same_thread": False}

        mock_create_engine.reset_mock()

        db_module._get_or_create_engine("mssql+pyodbc://user:pass@host/db?driver=x")
        mssql_kwargs = mock_create_engine.call_args.kwargs["connect_args"]
        assert mssql_kwargs == {}
