"""
FastAPI application entry point.

Registers all API routers and handles application startup configuration.
"""

from fastapi import FastAPI
import logging

from code.settings import (
    MODE,
    SQLITE_DATABASE_URL,
    MSSQL_DATABASE_URL,
    setup_logging
)
from code.logics.manager_view import load_category_config
from code.logics.core_utils import CoreUtils

# Import all routers
from code.api.routers.upload_router import router as upload_router
from code.api.routers.manager_view_router import router as manager_view_router
from code.api.routers.forecast_router import router as forecast_router
from code.api.routers.allocation_router import router as allocation_router
from code.api.routers.month_config_router import router as month_config_router

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Validate forecast grouping config at startup
try:
    logger.info("[Startup] Validating forecast grouping configuration...")
    load_category_config()  # This will validate and raise exception if invalid
    logger.info("[Startup] Forecast grouping configuration validated successfully")
except (FileNotFoundError, ValueError) as e:
    logger.critical(f"[Startup] FATAL: Invalid forecast grouping configuration: {e}")
    logger.critical("[Startup] Application cannot start with invalid configuration")
    raise RuntimeError(f"Application startup failed: {e}") from e

# Determine database URL based on mode
if MODE.upper() == "DEBUG":
    DATABASE_URL = SQLITE_DATABASE_URL
elif MODE.upper() == "PRODUCTION":
    DATABASE_URL = MSSQL_DATABASE_URL
else:
    raise ValueError("Invalid MODE specified in config.")

# Initialize CoreUtils instance with database URL
core_utils = CoreUtils(DATABASE_URL)

# Initialize FastAPI application
app = FastAPI(
    title="Centene Forecasting API",
    description="API for forecast management, allocation, and manager view reporting",
    version="0.2.0",  # Incremented version for router refactor
)

# Register routers
app.include_router(upload_router, tags=["File Management"])
app.include_router(manager_view_router, tags=["Manager View"])
app.include_router(forecast_router, tags=["Forecast Filters"])
app.include_router(allocation_router, tags=["Allocation"])
app.include_router(month_config_router, tags=["Month Configuration"])

logger.info("[Startup] All routers registered successfully")
logger.info("[Startup] Application started in %s mode", MODE.upper())
