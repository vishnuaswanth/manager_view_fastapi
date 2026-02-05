"""
Alembic Environment Configuration for SQLModel

This module configures Alembic to work with SQLModel models and
automatically selects the correct database based on MODE setting.
"""

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import sys
from pathlib import Path

# Add the parent directory to the path so we can import our code
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import settings to get MODE and database URLs
try:
    from code.settings import MODE, SQLITE_DATABASE_URL, MSSQL_DATABASE_URL
except ImportError:
    # Fallback if settings module doesn't exist
    import os
    MODE = os.getenv("MODE", "DEBUG")
    SQLITE_DATABASE_URL = os.getenv("SQLITE_DATABASE_URL", "sqlite:///./database.db")
    MSSQL_DATABASE_URL = os.getenv("MSSQL_DATABASE_URL", "")

# Import SQLModel base and all models
from sqlmodel import SQLModel
from code.logics.db import (
    UploadDataTimeDetails,
    SkillingModel,
    RosterModel,
    RosterTemplate,
    ProdTeamRosterModel,
    ForecastModel,
    ForecastMonthsModel,
    AllocationReportsModel,
    MonthConfigurationModel,
    AllocationExecutionModel,
    HistoryLogModel,
    HistoryChangeModel,
    RawData,
    AllocationValidityModel,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set the SQLAlchemy URL based on MODE
if MODE.upper() == "DEBUG":
    db_url = SQLITE_DATABASE_URL
    print(f"[Alembic] Using DEBUG mode - SQLite: {db_url}")
elif MODE.upper() == "PRODUCTION":
    if not MSSQL_DATABASE_URL:
        raise ValueError("MSSQL_DATABASE_URL is required for PRODUCTION mode")
    db_url = MSSQL_DATABASE_URL
    print(f"[Alembic] Using PRODUCTION mode - MSSQL")
else:
    raise ValueError(f"Invalid MODE: {MODE}. Must be DEBUG or PRODUCTION")

# Override the sqlalchemy.url in alembic.ini with our dynamic URL
# Escape % as %% for Alembic's config parser (it interprets % as interpolation)
config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")

    # Check if we're using SQLite
    is_sqlite = url and url.startswith("sqlite")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # Detect column type changes
        compare_server_default=True,  # Detect default value changes
        render_as_batch=is_sqlite,  # Enable batch mode for SQLite
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # Check if we're using SQLite
    url = config.get_main_option("sqlalchemy.url")
    is_sqlite = url and url.startswith("sqlite")

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # Detect column type changes
            compare_server_default=True,  # Detect default value changes
            render_as_batch=is_sqlite,  # Enable batch mode for SQLite
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
