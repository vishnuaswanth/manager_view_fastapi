"""
Shared dependencies for API routers.

Provides dependency injection for commonly used services
like database managers, loggers, and configuration.
"""

import logging
from typing import Optional
from code.settings import MODE, SQLITE_DATABASE_URL, MSSQL_DATABASE_URL
from code.logics.core_utils import CoreUtils
from code.logics.db import (
    ForecastModel,
    ForecastMonthsModel,
    ProdTeamRosterModel,
    UploadDataTimeDetails,
    MonthConfigurationModel,
    AllocationExecutionModel,
    RawData
)


# Initialize logger for API routers
def get_logger(name: str = "api") -> logging.Logger:
    """
    Get a logger instance for API routers.

    Args:
        name: Logger name (default: "api")

    Returns:
        Logger instance

    Usage in routers:
        from code.api.dependencies import get_logger
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)


# Core utils instance (singleton pattern)
_core_utils_instance: Optional[CoreUtils] = None


def get_core_utils() -> CoreUtils:
    """
    Get CoreUtils singleton instance.

    Returns:
        CoreUtils instance configured with DATABASE_URL

    Usage in routers:
        from code.api.dependencies import get_core_utils
        core_utils = get_core_utils()
    """
    global _core_utils_instance
    if _core_utils_instance is None:
        # Determine database URL based on mode (lazy initialization)
        if MODE.upper() == "DEBUG":
            DATABASE_URL = SQLITE_DATABASE_URL
        elif MODE.upper() == "PRODUCTION":
            DATABASE_URL = MSSQL_DATABASE_URL
        else:
            raise ValueError("Invalid MODE specified in config.")

        _core_utils_instance = CoreUtils(DATABASE_URL)
    return _core_utils_instance


def get_db_manager(
    model_class,
    limit: Optional[int] = None,
    skip: Optional[int] = 0,
    select_columns: Optional[list] = None
):
    """
    Get a database manager for a specific model.

    Args:
        model_class: SQLModel class to manage (e.g., ForecastModel)
        limit: Maximum records to return (optional)
        skip: Number of records to skip (optional)
        select_columns: Columns to select (optional)

    Returns:
        Database manager instance

    Usage in routers:
        from code.api.dependencies import get_db_manager
        from code.logics.db import ForecastModel

        db_manager = get_db_manager(ForecastModel, limit=50, skip=0)
        records = db_manager.get_data_from_db()
    """
    core_utils = get_core_utils()
    return core_utils.get_db_manager(
        model_class,
        limit=limit,
        skip=skip,
        select_columns=select_columns
    )


# Model mapping for convenience
MODEL_MAP = {
    "Forecast": ForecastModel,
    "ForecastMonths": ForecastMonthsModel,
    "ProdTeamRoster": ProdTeamRosterModel,
    "UploadDataTimeDetails": UploadDataTimeDetails,
    "MonthConfiguration": MonthConfigurationModel,
    "AllocationExecution": AllocationExecutionModel,
    "RawData": RawData
}


def get_model_by_name(model_name: str):
    """
    Get model class by name.

    Args:
        model_name: Name of the model (e.g., "Forecast", "ProdTeamRoster")

    Returns:
        Model class

    Raises:
        ValueError: If model name is not recognized

    Usage in routers:
        from code.api.dependencies import get_model_by_name

        model_class = get_model_by_name("Forecast")
        db_manager = get_db_manager(model_class)
    """
    if model_name not in MODEL_MAP:
        raise ValueError(
            f"Unknown model name: {model_name}. "
            f"Valid names: {list(MODEL_MAP.keys())}"
        )
    return MODEL_MAP[model_name]
