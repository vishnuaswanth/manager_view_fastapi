"""
Ramp Calculation API Router.

Provides three endpoints for weekly staffing ramp calculations on forecast rows:
  GET  /forecasts/{forecast_id}/months/{month_key}/ramp          - Get applied ramp
  POST /forecasts/{forecast_id}/months/{month_key}/ramp/preview  - Preview ramp impact
  POST /forecasts/{forecast_id}/months/{month_key}/ramp/apply    - Apply ramp to DB
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from code.api.dependencies import get_core_utils, get_logger
from code.logics.ramp_calculator import apply_ramp, get_applied_ramp, preview_ramp

logger = get_logger(__name__)

router = APIRouter()


# ============================================================================
# PYDANTIC MODELS
# ============================================================================


class RampWeek(BaseModel):
    """A single week's ramp configuration."""
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, description="Week label, e.g. 'Jan-1-2026'")
    startDate: str = Field(min_length=10, description="Week start date 'YYYY-MM-DD'")
    endDate: str = Field(min_length=10, description="Week end date 'YYYY-MM-DD'")
    workingDays: int = Field(ge=0, description="Number of working days in this week")
    rampPercent: float = Field(ge=0, le=100, description="Ramp percentage 0-100")
    rampEmployees: int = Field(ge=0, description="Number of employees ramping this week")


class RampPreviewRequest(BaseModel):
    """Request body for ramp preview endpoint."""
    model_config = ConfigDict(extra="forbid")

    weeks: List[RampWeek] = Field(min_length=1, description="List of weekly ramp entries")
    totalRampEmployees: int = Field(ge=0, description="Total employees across all weeks (must equal sum of rampEmployees)")


class RampApplyRequest(RampPreviewRequest):
    """Request body for ramp apply endpoint (extends preview with optional notes)."""
    model_config = ConfigDict(extra="forbid")

    user_notes: Optional[str] = Field(None, max_length=1000, description="Optional audit notes")


# ============================================================================
# VALIDATION HELPERS
# ============================================================================


def _validate_ramp_request(request: RampPreviewRequest) -> None:
    """
    Validate ramp request data before database operations.

    Args:
        request: RampPreviewRequest or RampApplyRequest

    Raises:
        HTTPException 400: If validation fails
    """
    # At least one week must have employees > 0
    if all(w.rampEmployees == 0 for w in request.weeks):
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "All rampEmployees are zero — no ramp to apply",
                "recommendation": "At least one week must have rampEmployees > 0"
            }
        )

    # totalRampEmployees must equal sum of rampEmployees
    computed_total = sum(w.rampEmployees for w in request.weeks)
    if request.totalRampEmployees != computed_total:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": (
                    f"totalRampEmployees ({request.totalRampEmployees}) does not match "
                    f"sum of rampEmployees across weeks ({computed_total})"
                ),
                "recommendation": "Ensure totalRampEmployees equals the sum of all week rampEmployees"
            }
        )


# ============================================================================
# ENDPOINTS
# ============================================================================


@router.get(
    "/forecasts/{forecast_id}/months/{month_key}/ramp",
    summary="Get applied ramp data",
    response_description="Ramp data applied to this forecast row and month"
)
async def get_ramp(
    forecast_id: int,
    month_key: str = Path(..., pattern=r"^\d{4}-\d{2}$", description="Target month in YYYY-MM format")
):
    """
    Retrieve any previously applied ramp for a forecast row and month.

    Returns ramp_applied=false and ramp_data=null if no ramp has been applied.
    """
    try:
        result = get_applied_ramp(forecast_id, month_key)
        return result
    except HTTPException:
        raise
    except (ValueError, KeyError, AttributeError) as e:
        logger.error(f"Validation error in get_ramp: {e}", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": str(e),
                "recommendation": "Check forecast_id and month_key parameters"
            }
        )
    except SQLAlchemyError as e:
        logger.error(f"Database error in get_ramp: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "Database operation failed"}
        )
    except Exception as e:
        logger.critical(f"Unexpected error in get_ramp: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "An unexpected error occurred"}
        )


@router.post(
    "/forecasts/{forecast_id}/months/{month_key}/ramp/preview",
    summary="Preview ramp impact",
    response_description="Current and projected FTE/capacity values without writing to DB"
)
async def preview_ramp_endpoint(
    forecast_id: int,
    month_key: str = Path(..., pattern=r"^\d{4}-\d{2}$", description="Target month in YYYY-MM format"),
    request: RampPreviewRequest = None
):
    """
    Calculate the impact of a ramp schedule without persisting changes.

    Returns current, projected, and diff values for FTE_Avail and Capacity
    for the target month.
    """
    if request is None:
        raise HTTPException(
            status_code=422,
            detail={"success": False, "error": "Request body is required"}
        )

    try:
        _validate_ramp_request(request)
        result = preview_ramp(forecast_id, month_key, request.weeks)
        return result
    except HTTPException:
        raise
    except (ValueError, KeyError, AttributeError) as e:
        logger.error(f"Validation error in preview_ramp: {e}", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": str(e),
                "recommendation": "Check your request payload structure"
            }
        )
    except SQLAlchemyError as e:
        logger.error(f"Database error in preview_ramp: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "Database operation failed"}
        )
    except Exception as e:
        logger.critical(f"Unexpected error in preview_ramp: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "An unexpected error occurred"}
        )


@router.post(
    "/forecasts/{forecast_id}/months/{month_key}/ramp/apply",
    summary="Apply ramp calculation",
    response_description="Result of applying ramp: updated DB values and history log ID"
)
async def apply_ramp_endpoint(
    forecast_id: int,
    month_key: str = Path(..., pattern=r"^\d{4}-\d{2}$", description="Target month in YYYY-MM format"),
    request: RampApplyRequest = None
):
    """
    Apply a ramp schedule to the forecast row and persist changes.

    Updates FTE_Avail and Capacity for the target month in ForecastModel,
    persists per-week RampModel records, and creates a history log entry.

    Note: Applying twice adds the delta twice (additive-only, no reversal in scope).
    """
    if request is None:
        raise HTTPException(
            status_code=422,
            detail={"success": False, "error": "Request body is required"}
        )

    try:
        _validate_ramp_request(request)
        result = apply_ramp(
            forecast_id=forecast_id,
            month_key=month_key,
            weeks=request.weeks,
            user_notes=request.user_notes
        )
        return result
    except HTTPException:
        raise
    except (ValueError, KeyError, AttributeError) as e:
        logger.error(f"Validation error in apply_ramp: {e}", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": str(e),
                "recommendation": "Check your request payload structure"
            }
        )
    except SQLAlchemyError as e:
        logger.error(f"Database error in apply_ramp: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "Database operation failed"}
        )
    except Exception as e:
        logger.critical(f"Unexpected error in apply_ramp: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "An unexpected error occurred"}
        )
