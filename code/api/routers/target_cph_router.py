"""
Target CPH configuration management endpoints.

Provides CRUD operations for Target CPH (Cases Per Hour) configuration data
that is used in allocation logic for FTE calculations.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
import logging

from code.logics.target_cph_utils import (
    add_target_cph_configuration,
    bulk_add_target_cph_configurations,
    get_target_cph_configuration,
    update_target_cph_configuration,
    delete_target_cph_configuration,
    get_target_cph_count,
    get_distinct_main_lobs,
    get_distinct_case_types
)
from code.api.dependencies import get_logger
from code.api.utils.responses import success_response, error_response
from code.cache import (
    target_cph_cache,
    generate_target_cph_cache_key,
    invalidate_target_cph_cache
)

# Initialize router and dependencies
router = APIRouter()
logger = get_logger(__name__)


# ============ Pydantic Request Models ============

class TargetCPHRequest(BaseModel):
    """Request model for single Target CPH configuration creation."""
    main_lob: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Main line of business (e.g., 'Amisys Medicaid GLOBAL')"
    )
    case_type: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Case type identifier (e.g., 'FTC-Basic/Non MMP')"
    )
    target_cph: float = Field(
        ...,
        gt=0,
        le=200,
        description="Target cases per hour value (e.g., 12.0)"
    )
    created_by: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Username of the person creating the record"
    )

    class Config:
        extra = "forbid"  # Reject unknown fields


class TargetCPHUpdateRequest(BaseModel):
    """Request model for updating Target CPH configuration."""
    target_cph: Optional[float] = Field(
        None,
        gt=0,
        le=200,
        description="New Target CPH value"
    )
    main_lob: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="New Main LOB value"
    )
    case_type: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="New Case Type value"
    )
    updated_by: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Username of the person updating the record"
    )

    class Config:
        extra = "forbid"


class BulkTargetCPHRequest(BaseModel):
    """Request model for bulk Target CPH configuration creation."""
    configurations: List[TargetCPHRequest] = Field(
        ...,
        min_length=1,
        description="List of Target CPH configurations to add"
    )

    class Config:
        extra = "forbid"


# ============ API Endpoints ============

@router.get("")
def list_target_cph_configurations(
    main_lob: Optional[str] = Query(
        None,
        description="Filter by Main LOB (partial match, case-insensitive)"
    ),
    case_type: Optional[str] = Query(
        None,
        description="Filter by Case Type (partial match, case-insensitive)"
    )
):
    """
    List Target CPH configurations with optional filters.

    Query Parameters:
        main_lob: Optional Main LOB filter (partial match, case-insensitive)
        case_type: Optional Case Type filter (partial match, case-insensitive)

    Returns:
        List of configuration objects with count

    Cache:
        TTL: 15 minutes (900 seconds)
        Key: target_cph:v1:{main_lob}:{case_type}
    """
    # Generate cache key
    cache_key = generate_target_cph_cache_key(main_lob, case_type)

    # Check cache first
    cached_response = target_cph_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cache] Returning cached Target CPH config for {cache_key}")
        return cached_response

    try:
        configs = get_target_cph_configuration(
            main_lob=main_lob,
            case_type=case_type
        )

        response = success_response(
            data={"count": len(configs), "configurations": configs}
        )

        # Cache the response
        target_cph_cache.set(cache_key, response)
        logger.info(f"[Cache] Cached Target CPH response: {len(configs)} configs")

        return response

    except Exception as e:
        logger.error(f"Error retrieving Target CPH configurations: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.get("/distinct/main-lobs")
def list_distinct_main_lobs():
    """
    Get list of distinct Main LOB values.

    Returns:
        Sorted list of distinct Main LOB values
    """
    try:
        main_lobs = get_distinct_main_lobs()
        return success_response(
            data={"count": len(main_lobs), "main_lobs": main_lobs}
        )
    except Exception as e:
        logger.error(f"Error retrieving distinct Main LOBs: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.get("/distinct/case-types")
def list_distinct_case_types(
    main_lob: Optional[str] = Query(
        None,
        description="Optional Main LOB filter"
    )
):
    """
    Get list of distinct Case Type values.

    Query Parameters:
        main_lob: Optional Main LOB filter

    Returns:
        Sorted list of distinct Case Type values
    """
    try:
        case_types = get_distinct_case_types(main_lob=main_lob)
        return success_response(
            data={"count": len(case_types), "case_types": case_types}
        )
    except Exception as e:
        logger.error(f"Error retrieving distinct Case Types: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.get("/count")
def get_configuration_count():
    """
    Get total count of Target CPH configurations.

    Returns:
        Total count of configurations
    """
    try:
        count = get_target_cph_count()
        return success_response(
            data={"count": count}
        )
    except Exception as e:
        logger.error(f"Error getting Target CPH count: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.get("/{config_id}")
def get_target_cph_by_id(config_id: int):
    """
    Get a specific Target CPH configuration by ID.

    Path Parameters:
        config_id: ID of the configuration

    Returns:
        Configuration object or 404 if not found
    """
    try:
        configs = get_target_cph_configuration(config_id=config_id)

        if not configs:
            raise HTTPException(
                status_code=404,
                detail=error_response(f"Configuration with ID {config_id} not found")
            )

        return success_response(data=configs[0])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving Target CPH configuration: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.post("")
def create_target_cph_configuration(request: TargetCPHRequest):
    """
    Add a single Target CPH configuration.

    Body Parameters (JSON):
        main_lob: Main line of business (e.g., "Amisys Medicaid GLOBAL")
        case_type: Case type identifier (e.g., "FTC-Basic/Non MMP")
        target_cph: Target cases per hour value (e.g., 12.0)
        created_by: Username

    Returns:
        Success/error message

    Error Codes:
        400: Validation failed or duplicate configuration
        500: Internal server error
    """
    try:
        success, message = add_target_cph_configuration(
            main_lob=request.main_lob,
            case_type=request.case_type,
            target_cph=request.target_cph,
            created_by=request.created_by
        )

        if success:
            # Invalidate cache after successful creation
            invalidate_target_cph_cache()
            logger.info("[Cache] Invalidated Target CPH cache after creation")
            return success_response(message=message)
        else:
            raise HTTPException(status_code=400, detail=error_response(message))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating Target CPH configuration: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.post("/bulk")
def bulk_create_target_cph_configurations(request: BulkTargetCPHRequest):
    """
    Bulk add multiple Target CPH configurations.

    Body Parameters (JSON):
        configurations: Array of configuration objects, each with:
            - main_lob: str
            - case_type: str
            - target_cph: float
            - created_by: str

    Returns:
        Summary of bulk operation:
            - total: Total configurations attempted
            - succeeded: Number of successful insertions
            - failed: Number of failed insertions
            - duplicates_skipped: Number of duplicates skipped
            - errors: List of error messages

    Error Codes:
        400: All configurations failed
        500: Internal server error
    """
    try:
        # Convert Pydantic models to dicts
        configs = [
            {
                'main_lob': c.main_lob,
                'case_type': c.case_type,
                'target_cph': c.target_cph,
                'created_by': c.created_by
            }
            for c in request.configurations
        ]

        result = bulk_add_target_cph_configurations(configurations=configs)

        # Invalidate cache if any configurations were added
        if result.get('succeeded', 0) > 0:
            invalidate_target_cph_cache()
            logger.info(f"[Cache] Invalidated Target CPH cache after bulk operation ({result['succeeded']} configs added)")

        # If all failed, return 400
        if result.get('succeeded', 0) == 0 and result.get('failed', 0) > 0:
            raise HTTPException(
                status_code=400,
                detail={
                    "success": False,
                    "message": "All configurations failed",
                    "data": result
                }
            )

        return success_response(data=result, message="Bulk operation completed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk create Target CPH configurations: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.put("/{config_id}")
def update_target_cph_configuration_endpoint(
    config_id: int,
    request: TargetCPHUpdateRequest
):
    """
    Update an existing Target CPH configuration.

    Path Parameters:
        config_id: ID of the configuration to update

    Body Parameters (JSON):
        target_cph: New Target CPH value (optional)
        main_lob: New Main LOB value (optional)
        case_type: New Case Type value (optional)
        updated_by: Username (required)

    Returns:
        Success/error message

    Error Codes:
        400: Validation failed or no changes provided
        404: Configuration not found
        409: Update would create duplicate
        500: Internal server error
    """
    try:
        success, message = update_target_cph_configuration(
            config_id=config_id,
            target_cph=request.target_cph,
            main_lob=request.main_lob,
            case_type=request.case_type,
            updated_by=request.updated_by
        )

        if success:
            # Invalidate cache after successful update
            invalidate_target_cph_cache()
            logger.info(f"[Cache] Invalidated Target CPH cache after update (config_id={config_id})")
            return success_response(message=message)
        else:
            # Determine appropriate status code
            if "not found" in message.lower():
                raise HTTPException(status_code=404, detail=error_response(message))
            elif "duplicate" in message.lower():
                raise HTTPException(status_code=409, detail=error_response(message))
            else:
                raise HTTPException(status_code=400, detail=error_response(message))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating Target CPH configuration: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )


@router.delete("/{config_id}")
def delete_target_cph_configuration_endpoint(config_id: int):
    """
    Delete a Target CPH configuration.

    Path Parameters:
        config_id: ID of the configuration to delete

    Returns:
        Success/error message

    Error Codes:
        404: Configuration not found
        500: Internal server error
    """
    try:
        success, message = delete_target_cph_configuration(config_id=config_id)

        if success:
            # Invalidate cache after successful deletion
            invalidate_target_cph_cache()
            logger.info(f"[Cache] Invalidated Target CPH cache after deletion (config_id={config_id})")
            return success_response(message=message)
        else:
            raise HTTPException(status_code=404, detail=error_response(message))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting Target CPH configuration: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Internal server error", str(e))
        )
