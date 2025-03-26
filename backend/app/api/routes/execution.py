from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.exceptions import IntegrationException
from app.core.logging import logger
from app.core.metrics import ACTIVE_EXECUTIONS, EXECUTION_DURATION, SCRIPT_EXECUTIONS
from app.schemas.execution import (
    ExecutionRequest,
    ExecutionResponse,
    ExecutionResult,
    K8SResourceLimits,
    ResourceUsage,
)
from app.services.execution_service import ExecutionService, get_execution_service

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/execute", response_model=ExecutionResponse)
@limiter.limit("20/minute")
async def create_execution(
        request: Request,
        execution: ExecutionRequest,
        execution_service: ExecutionService = Depends(get_execution_service),
) -> ExecutionResponse:
    ACTIVE_EXECUTIONS.inc()

    logger.info(
        "Received script execution request",
        extra={
            "python_version": execution.python_version,
            "script_length": len(execution.script),
            "client_ip": get_remote_address(request),
            "endpoint": "/execute",
        },
    )

    try:
        python_version = execution.python_version or "3.11"

        with EXECUTION_DURATION.labels(python_version=python_version).time():
            result = await execution_service.execute_script(
                execution.script, python_version
            )

        SCRIPT_EXECUTIONS.labels(
            status="success", python_version=python_version
        ).inc()

        logger.info(
            "Script execution initiated successfully",
            extra={"execution_id": result.id, "status": result.status},
        )
        return ExecutionResponse(execution_id=result.id, status=result.status)

    except IntegrationException as e:
        SCRIPT_EXECUTIONS.labels(
            status="integration_error", python_version=execution.python_version or "3.11"
        ).inc()

        logger.error(
            "Integration error during script execution",
            extra={
                "error_type": "IntegrationException",
                "status_code": e.status_code,
                "error_detail": e.detail,
                "python_version": execution.python_version,
            },
        )
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    except Exception as e:
        SCRIPT_EXECUTIONS.labels(
            status="error", python_version=execution.python_version or "3.11"
        ).inc()

        logger.error(
            "Unexpected error during script execution",
            extra={
                "error_type": type(e).__name__,
                "error_detail": str(e),
                "python_version": execution.python_version,
            },
        )
        raise HTTPException(status_code=400, detail=f"Error during execution: {str(e)}") from e
    finally:
        ACTIVE_EXECUTIONS.dec()


@router.get("/result/{execution_id}", response_model=ExecutionResult)
@limiter.limit("20/minute")
async def get_result(
        request: Request,
        execution_id: str,
        execution_service: ExecutionService = Depends(get_execution_service),
) -> ExecutionResult:
    logger.info(
        "Received execution result request",
        extra={
            "execution_id": execution_id,
            "client_ip": get_remote_address(request),
            "endpoint": "/result",
        },
    )

    result = await execution_service.get_execution_result(execution_id)

    if not result:
        logger.warning(
            "Execution result not found", extra={"execution_id": execution_id}
        )
        raise HTTPException(status_code=404, detail="Execution not found")

    logger.info(
        "Execution result retrieved successfully",
        extra={
            "execution_id": result.id,
            "status": result.status,
            "python_version": result.python_version,
            "has_errors": bool(result.errors),
            "resource_usage": result.resource_usage,
        },
    )

    # Convert dict to ResourceUsage if needed
    resource_usage_obj = None
    if result.resource_usage:
        resource_usage_obj = ResourceUsage(**result.resource_usage)

    return ExecutionResult(
        execution_id=result.id,
        status=result.status,
        output=result.output,
        errors=result.errors,
        python_version=result.python_version,
        resource_usage=resource_usage_obj,
    )


@router.get("/k8s-limits", response_model=K8SResourceLimits)
async def get_k8s_resource_limits(
        execution_service: ExecutionService = Depends(get_execution_service),
) -> K8SResourceLimits:
    logger.info("Retrieving K8s resource limits", extra={"endpoint": "/k8s-limits"})

    try:
        limits = await execution_service.get_k8s_resource_limits()
        logger.info(
            "K8s resource limits retrieved successfully", extra={"limits": limits}
        )
        return K8SResourceLimits(**limits)

    except Exception as e:
        logger.error(
            "Failed to retrieve K8s resource limits",
            extra={"error_type": type(e).__name__, "error_detail": str(e)},
        )
        raise HTTPException(
            status_code=500, detail=f"An unexpected error occurred: {str(e)}"
        ) from e
