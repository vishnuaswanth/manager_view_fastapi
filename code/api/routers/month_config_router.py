"""
Month configuration management endpoints.

Provides CRUD operations for month configuration data (working days, occupancy,
shrinkage, work hours) separated by work type (Domestic vs Global).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
import logging

from code.logics.month_config_utils import (
    add_month_configuration,
    bulk_add_month_configurations,
    get_month_configuration,
    update_month_configuration,
    delete_month_configuration,
    seed_initial_data,
    validate_all_pairs
)
from code.api.dependencies import get_logger
from code.api.utils.responses import success_response, error_response
from code.cache import (
    month_config_cache,
    generate_month_config_cache_key,
    invalidate_month_config_cache
)

# Initialize router and dependencies
router = APIRouter()
logger = get_logger(__name__)


# Pydantic models for request validation
class MonthConfigRequest(BaseModel):
    """Request model for single month configuration creation."""
    month: str
    year: int
    work_type: str
    working_days: int
    occupancy: float
    shrinkage: float
    work_hours: float
    created_by: str


class BulkMonthConfigRequest(BaseModel):
    """Request model for bulk month configuration creation."""
    configurations: List[Dict]
    created_by: str
    skip_pairing_validation: bool = False


class SeedMonthConfigRequest(BaseModel):
    """Request model for seeding month configurations."""
    base_year: int = 2025
    num_years: int = 2
    created_by: str = "System"


@router.post("/api/month-config")
def create_month_configuration(request: MonthConfigRequest):
    """
    Add a single month configuration to the database.

    Body Parameters (JSON):
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)
        work_type: "Domestic" or "Global"
        working_days: Number of working days (e.g., 21)
        occupancy: Occupancy rate (0.0-1.0, e.g., 0.95 for 95%)
        shrinkage: Shrinkage rate (0.0-1.0, e.g., 0.10 for 10%)
        work_hours: Work hours per day (e.g., 9)
        created_by: Username

    Returns:
        Success/error message
    """
    try:
        success, message = add_month_configuration(
            month=request.month,
            year=request.year,
            work_type=request.work_type,
            working_days=request.working_days,
            occupancy=request.occupancy,
            shrinkage=request.shrinkage,
            work_hours=request.work_hours,
            created_by=request.created_by
        )

        if success:
            # Invalidate month config cache after successful creation
            invalidate_month_config_cache()
            logger.info("[Cache] Invalidated month config cache after creation")
            return success_response(message=message)
        else:
            raise HTTPException(status_code=400, detail=error_response(message))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating month configuration: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.post("/api/month-config/bulk")
def bulk_create_month_configurations(request: BulkMonthConfigRequest):
    """
    Bulk add multiple month configurations.

    PAIRING VALIDATION: By default, validates that for each (month, year) in the batch,
    both Domestic and Global configurations are present. This ensures data integrity.

    Body Parameters (JSON):
        configurations: Array of configuration objects, each with:
            - month: str
            - year: int
            - work_type: str
            - working_days: int
            - occupancy: float
            - shrinkage: float
            - work_hours: int
        created_by: Username
        skip_pairing_validation: If true, skips batch pairing validation (default: false)
                                Use with caution - may create orphaned records

    Returns:
        Summary of bulk operation (total, succeeded, failed, errors, validation_errors)

    Error Codes:
        400: Validation failed - missing pairs
        500: Internal server error
    """
    try:
        result = bulk_add_month_configurations(
            configurations=request.configurations,
            created_by=request.created_by,
            skip_pairing_validation=request.skip_pairing_validation
        )

        # Check if validation failed
        if result.get('validation_errors'):
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Batch validation failed",
                    "validation_errors": result['validation_errors'],
                    "total": result['total']
                }
            )

        # Invalidate month config cache after successful bulk operation
        if result.get('succeeded', 0) > 0:
            invalidate_month_config_cache()
            logger.info(f"[Cache] Invalidated month config cache after bulk operation ({result['succeeded']} configs added)")

        return success_response(data=result, message="Bulk operation completed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk create month configurations: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.get("/api/month-config")
def get_month_configurations(
    month: Optional[str] = None,
    year: Optional[int] = None,
    work_type: Optional[str] = None
):
    """
    Retrieve month configurations with optional filters.

    Query Parameters:
        month: Optional month filter (e.g., "January")
        year: Optional year filter (e.g., 2025)
        work_type: Optional work type filter ("Domestic" or "Global")

    Returns:
        List of configuration objects

    Cache:
        TTL: 15 minutes (900 seconds)
        Key: month_config:v1:{month}:{year}:{work_type}
    """
    # Generate cache key
    cache_key = generate_month_config_cache_key(month, year, work_type)

    # Check cache first
    cached_response = month_config_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cache] Returning cached month config for {cache_key}")
        return cached_response

    try:
        configs = get_month_configuration(
            month=month,
            year=year,
            work_type=work_type
        )

        response = success_response(
            data={"count": len(configs), "configurations": configs}
        )

        # Cache the response
        month_config_cache.set(cache_key, response)
        logger.info(f"[Cache] Cached month config response: {len(configs)} configs")

        return response

    except Exception as e:
        logger.error(f"Error retrieving month configurations: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.put("/api/month-config/{config_id}")
def update_month_configuration_endpoint(
    config_id: int,
    working_days: Optional[int] = None,
    occupancy: Optional[float] = None,
    shrinkage: Optional[float] = None,
    work_hours: Optional[float] = None,
    updated_by: str = "System"
):
    """
    Update an existing month configuration.

    Path Parameters:
        config_id: ID of the configuration to update

    Body Parameters (all optional):
        working_days: New working days value
        occupancy: New occupancy value
        shrinkage: New shrinkage value
        work_hours: New work hours value
        updated_by: Username

    Returns:
        Success/error message
    """
    try:
        success, message = update_month_configuration(
            config_id=config_id,
            working_days=working_days,
            occupancy=occupancy,
            shrinkage=shrinkage,
            work_hours=work_hours,
            updated_by=updated_by
        )

        if success:
            # Invalidate month config cache after successful update
            invalidate_month_config_cache()
            logger.info(f"[Cache] Invalidated month config cache after update (config_id={config_id})")
            return success_response(message=message)
        else:
            raise HTTPException(
                status_code=404,
                detail=error_response(message)
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating month configuration: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.delete("/api/month-config/{config_id}")
def delete_month_configuration_endpoint(config_id: int, allow_orphan: bool = False):
    """
    Delete a month configuration.

    ORPHAN PREVENTION: By default, prevents deletion if it would leave an orphaned
    record (month-year with only Domestic or only Global). This ensures data integrity
    and prevents inconsistent allocation calculations.

    Path Parameters:
        config_id: ID of the configuration to delete

    Query Parameters:
        allow_orphan: If true, allows deletion even if it orphans the pair (default: false)
                     Use with caution - may create inconsistent calculation behavior

    Returns:
        Success/error message

    Error Codes:
        404: Configuration not found
        409: Cannot delete - would orphan a record (when allow_orphan=false)
        500: Internal server error
    """
    try:
        success, message = delete_month_configuration(config_id=config_id, allow_orphan=allow_orphan)

        if success:
            # Invalidate month config cache after successful deletion
            invalidate_month_config_cache()
            logger.info(f"[Cache] Invalidated month config cache after deletion (config_id={config_id})")
            return success_response(message=message)
        else:
            # Check if this is an orphan prevention error
            if "would orphan" in message.lower():
                raise HTTPException(
                    status_code=409,
                    detail=error_response(message)
                )
            else:
                raise HTTPException(
                    status_code=404,
                    detail=error_response(message)
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting month configuration: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.post("/api/month-config/seed")
def seed_month_configurations(request: SeedMonthConfigRequest = SeedMonthConfigRequest()):
    """
    Seed the database with initial month configuration data for deployment.

    Creates configurations for all 12 months for the specified number of years,
    for both Domestic and Global work types.

    Default parameters:
    - Occupancy: 95% (0.95)
    - Shrinkage: 10% (0.10)
    - Work Hours: 9
    - Working Days: Varies by month (20-22 days)

    Body Parameters (JSON, all optional):
        base_year: Starting year (default: 2025)
        num_years: Number of years to seed (default: 2)
        created_by: Username (default: "System")

    Returns:
        Summary of seeding operation
    """
    try:
        result = seed_initial_data(
            base_year=request.base_year,
            num_years=request.num_years,
            created_by=request.created_by
        )

        return success_response(
            data=result,
            message=f"Seeded {result['succeeded']}/{result['total']} configurations"
        )

    except Exception as e:
        logger.error(f"Error seeding month configurations: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.get("/api/month-config/validate")
def validate_month_configurations():
    """
    Validate data integrity of month configurations.

    Checks for orphaned records where a month-year has only Domestic OR only Global
    configuration, but not both. This violates the pairing rule and causes
    inconsistent allocation calculations.

    Returns:
        Validation report with:
            - is_valid: bool - True if all configurations are properly paired
            - orphaned_records: List of orphaned configurations
            - total_configs: Total configurations in database
            - paired_count: Number of properly paired month-years
            - orphaned_count: Number of orphaned configurations
            - recommendations: Suggested actions to fix issues

    Cache:
        TTL: 5 minutes (300 seconds)
        Key: month_config_validate:v1
    """
    # Generate cache key
    cache_key = "month_config_validate:v1"

    # Check cache first
    cached_response = month_config_cache.get(cache_key)
    if cached_response is not None:
        logger.debug("[Cache] Returning cached month config validation")
        return cached_response

    try:
        validation_result = validate_all_pairs()

        response = success_response(data=validation_result)

        # Cache the response (5 minutes TTL - handled by cache instance default)
        month_config_cache.set(cache_key, response)
        logger.info(f"[Cache] Cached validation result: {validation_result.get('total_configs')} configs checked")

        return response

    except Exception as e:
        logger.error(f"Error validating month configurations: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )
