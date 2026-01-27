"""
FastAPI application entry point.

Registers all API routers and handles application startup configuration.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import logging
import json

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
from code.api.routers.edit_view_router import router as edit_view_router
from code.api.routers.history_router import router as history_router
from code.api.routers.llm_router import router as llm_router

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


# Custom exception handler for Pydantic validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Log detailed validation errors before returning 422 response.

    This helps debug Pydantic validation issues that occur before endpoint code runs.
    """
    # Get request body for logging
    try:
        body = await request.body()
        body_str = body.decode('utf-8')
        try:
            body_json = json.loads(body_str)
            body_preview = json.dumps(body_json, indent=2)[:1000]  # First 1000 chars
        except:
            body_preview = body_str[:1000]
    except:
        body_preview = "<unable to read body>"

    # Log detailed error information
    logger.error(
        f"Validation Error on {request.method} {request.url.path}\n"
        f"Request Body Preview:\n{body_preview}\n"
        f"Validation Errors:\n{json.dumps(exc.errors(), indent=2)}"
    )

    # Return standard FastAPI validation error response
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()}
    )


# Register routers
app.include_router(upload_router, tags=["File Management"])
app.include_router(manager_view_router, tags=["Manager View"])
app.include_router(forecast_router, tags=["Forecast Filters"])
app.include_router(allocation_router, tags=["Allocation"])
app.include_router(month_config_router, tags=["Month Configuration"])
app.include_router(edit_view_router, tags=["Edit View"])
app.include_router(history_router, tags=["History Log"])
app.include_router(llm_router, tags=["LLM Tools"])

logger.info("[Startup] All routers registered successfully")
logger.info("[Startup] Application started in %s mode", MODE.upper())
