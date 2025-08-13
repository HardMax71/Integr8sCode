from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.dependencies import get_current_user, require_admin
from app.core.exceptions import IntegrationException
from app.core.logging import logger
from app.core.metrics import ACTIVE_EXECUTIONS, EXECUTION_DURATION, SCRIPT_EXECUTIONS
from app.core.tracing import EventAttributes, add_span_attributes, get_current_trace_id
from app.db.mongodb import DatabaseManager, get_database_manager
from app.db.repositories.event_repository import get_event_repository
from app.schemas_avro.event_schemas import EventType
from app.schemas_pydantic.execution import (
    CancelExecutionRequest,
    ExampleScripts,
    ExecutionEventResponse,
    ExecutionListResponse,
    ExecutionRequest,
    ExecutionResponse,
    ExecutionResult,
    ExecutionStatus,
    ResourceLimits,
    ResourceUsage,
    RetryExecutionRequest,
)
from app.schemas_pydantic.user import User, UserResponse, UserRole
from app.services.execution_service import (
    ExecutionService,
    get_execution_service,
)
from app.services.kafka_event_service import KafkaEventService, get_event_service

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


def check_execution_access(result: Any, current_user: UserResponse) -> None:
    """Check if user has access to the execution result."""
    if not result or not hasattr(result, 'user_id') or not result.user_id:
        return  # No user_id means public/system execution, allow access
    
    is_owner = result.user_id == current_user.user_id
    is_admin = current_user.role == UserRole.ADMIN
    
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")


@router.post("/execute", response_model=ExecutionResponse)
@limiter.limit("20/minute")
async def create_execution(
        request: Request,
        execution: ExecutionRequest,
        execution_service: ExecutionService = Depends(
            get_execution_service
        ),
        current_user: UserResponse = Depends(get_current_user),
) -> ExecutionResponse:
    """Create a new code execution request using event-driven architecture."""
    ACTIVE_EXECUTIONS.inc()

    trace_id = get_current_trace_id()

    add_span_attributes(
        **{
            "http.method": "POST",
            "http.route": "/api/v1/execute",
            "execution.language": execution.lang,
            "execution.language_version": execution.lang_version,
            "execution.script_length": len(execution.script),
            EventAttributes.USER_ID: current_user.user_id,
            "client.address": get_remote_address(request),
        }
    )

    logger.info(
        "Received script execution request",
        extra={
            "lang": execution.lang,
            "lang_version": execution.lang_version,
            "script_length": len(execution.script),
            "client_ip": get_remote_address(request),
            "endpoint": "/execute",
            "trace_id": trace_id,
            "user_id": current_user.user_id,
        },
    )

    lang_and_version = f"{execution.lang}-{execution.lang_version}"

    try:
        with EXECUTION_DURATION.labels(lang_and_version=lang_and_version).time():
            # Convert UserResponse to User object
            user = User.from_response(current_user)

            result = await execution_service.execute_script(
                script=execution.script,
                lang=execution.lang,
                lang_version=execution.lang_version,
                user=user,
                request=request,
            )

        SCRIPT_EXECUTIONS.labels(
            status="submitted", lang_and_version=lang_and_version
        ).inc()

        logger.info(
            "Script execution submitted successfully",
            extra={"execution_id": result.execution_id, "status": result.status},
        )

        return ExecutionResponse(execution_id=result.execution_id, status=result.status)

    except IntegrationException as e:
        SCRIPT_EXECUTIONS.labels(
            status="integration_error", lang_and_version=lang_and_version
        ).inc()

        logger.error(
            "Integration error during script execution",
            extra={
                "error_type": "IntegrationException",
                "status_code": e.status_code,
                "error_detail": e.detail,
                "lang_and_version": lang_and_version,
            },
        )
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    except Exception as e:
        SCRIPT_EXECUTIONS.labels(
            status="error", lang_and_version=lang_and_version
        ).inc()

        logger.error(
            "Unexpected error during script execution",
            extra={
                "error_type": type(e).__name__,
                "error_detail": str(e),
                "lang_and_version": lang_and_version,
            },
            exc_info=True  # This will log the full traceback
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error during script execution"
        ) from e
    finally:
        ACTIVE_EXECUTIONS.dec()


@router.get("/result/{execution_id}", response_model=ExecutionResult)
@limiter.limit("20/minute")
async def get_result(
        request: Request,
        execution_id: str,
        execution_service: ExecutionService = Depends(
            get_execution_service
        ),
        current_user: UserResponse = Depends(get_current_user),
) -> ExecutionResult:
    """Get execution result by ID."""
    logger.info(
        "Received execution result request",
        extra={
            "execution_id": execution_id,
            "client_ip": get_remote_address(request),
            "endpoint": "/result",
            "user_id": current_user.user_id,
        },
    )

    result = await execution_service.get_execution_result(execution_id)

    if not result:
        logger.warning(
            "Execution result not found", extra={"execution_id": execution_id}
        )
        raise HTTPException(status_code=404, detail="Execution not found")

    check_execution_access(result, current_user)

    logger.info(
        "Execution result retrieved successfully",
        extra={
            "execution_id": result.execution_id,
            "status": result.status,
            "lang": result.lang,
            "lang_version": result.lang_version,
            "has_errors": bool(result.errors),
            "resource_usage": result.resource_usage,
        },
    )

    resource_usage_obj = None
    if result.resource_usage:
        resource_usage_obj = ResourceUsage(**result.resource_usage)

    return ExecutionResult(
        execution_id=result.execution_id,
        status=result.status,
        output=result.output,
        errors=result.errors,
        lang=result.lang,
        lang_version=result.lang_version,
        resource_usage=resource_usage_obj,
        exit_code=result.exit_code,
    )


@router.post("/{execution_id}/cancel", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def cancel_execution(
        request: Request,
        execution_id: str,
        cancel_request: CancelExecutionRequest,
        execution_service: ExecutionService = Depends(
            get_execution_service
        ),
        event_service: KafkaEventService = Depends(get_event_service),
        current_user: UserResponse = Depends(get_current_user),
) -> Dict[str, Any]:
    """Cancel a running or queued execution."""
    logger.info(
        "Received execution cancellation request",
        extra={
            "execution_id": execution_id,
            "user_id": current_user.user_id,
            "reason": cancel_request.reason,
        },
    )

    result = await execution_service.get_execution_result(execution_id)

    if not result:
        raise HTTPException(status_code=404, detail="Execution not found")

    check_execution_access(result, current_user)

    if result.status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED,
                         ExecutionStatus.TIMEOUT, ExecutionStatus.CANCELLED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel execution in {result.status} state"
        )

    user = User.from_response(current_user)

    event_id = await event_service.publish_execution_event(
        event_type=EventType.EXECUTION_CANCELLED,
        execution_id=execution_id,
        status=ExecutionStatus.CANCELLED,
        user=user,
        metadata={
            "reason": cancel_request.reason or "User requested cancellation",
            "previous_status": result.status,
        }
    )

    logger.info(
        "Execution cancellation event published",
        extra={
            "execution_id": execution_id,
            "event_id": event_id,
        },
    )

    return {
        "execution_id": execution_id,
        "status": "cancellation_requested",
        "event_id": event_id,
        "message": "Cancellation request submitted"
    }


@router.post("/{execution_id}/retry", response_model=ExecutionResponse)
@limiter.limit("10/minute")
async def retry_execution(
        request: Request,
        execution_id: str,
        retry_request: RetryExecutionRequest,
        execution_service: ExecutionService = Depends(
            get_execution_service
        ),
        event_service: KafkaEventService = Depends(get_event_service),
        current_user: UserResponse = Depends(get_current_user),
) -> ExecutionResponse:
    """Retry a failed or completed execution."""
    logger.info(
        "Received execution retry request",
        extra={
            "execution_id": execution_id,
            "user_id": current_user.user_id,
            "reason": retry_request.reason,
        },
    )

    original_result = await execution_service.get_execution_result(execution_id)

    if not original_result:
        raise HTTPException(status_code=404, detail="Execution not found")

    check_execution_access(original_result, current_user)

    if original_result.status in [ExecutionStatus.RUNNING, ExecutionStatus.QUEUED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry execution in {original_result.status} state"
        )

    # Convert UserResponse to User object
    user = User.from_response(current_user)

    new_result = await execution_service.execute_script(
        script=original_result.script,
        lang=original_result.lang,
        lang_version=original_result.lang_version,
        user=user,
        request=request,
    )

    logger.info(
        "Execution retry submitted successfully",
        extra={
            "original_execution_id": execution_id,
            "new_execution_id": str(new_result.execution_id),
            "status": new_result.status,
        },
    )

    return ExecutionResponse(execution_id=new_result.execution_id, status=new_result.status)


@router.get("/events/{execution_id}", response_model=List[ExecutionEventResponse])
@limiter.limit("20/minute")
async def get_execution_events(
        request: Request,
        execution_id: str,
        event_types: Optional[str] = Query(
            None, description="Comma-separated event types to filter"
        ),
        limit: int = Query(100, ge=1, le=1000),
        execution_service: ExecutionService = Depends(get_execution_service),
        db_manager: DatabaseManager = Depends(get_database_manager),
        current_user: UserResponse = Depends(get_current_user),
) -> List[ExecutionEventResponse]:
    """Get all events for an execution."""
    logger.info(
        "Received execution events request",
        extra={
            "execution_id": execution_id,
            "client_ip": get_remote_address(request),
            "event_types": event_types,
            "user_id": current_user.user_id,
        },
    )

    result = await execution_service.get_execution_result(execution_id)
    check_execution_access(result, current_user)

    event_type_list = None
    if event_types:
        event_type_list = [t.strip() for t in event_types.split(",")]

    event_repository = get_event_repository(db_manager)
    events = await event_repository.get_events_by_aggregate(
        aggregate_id=execution_id,
        event_types=event_type_list,
        limit=limit
    )

    logger.info(
        "Execution events retrieved",
        extra={
            "execution_id": execution_id,
            "event_count": len(events),
        },
    )

    return [
        ExecutionEventResponse(
            event_id=event.event_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            payload=event.payload
        )
        for event in events
    ]


@router.get("/user/executions", response_model=ExecutionListResponse)
@limiter.limit("20/minute")
async def get_user_executions(
        request: Request,
        status: Optional[ExecutionStatus] = Query(None),
        lang: Optional[str] = Query(None),
        start_time: Optional[datetime] = Query(None),
        end_time: Optional[datetime] = Query(None),
        limit: int = Query(50, ge=1, le=200),
        skip: int = Query(0, ge=0),
        execution_service: ExecutionService = Depends(
            get_execution_service
        ),
        current_user: UserResponse = Depends(get_current_user),
) -> ExecutionListResponse:
    """Get executions for the current user."""
    logger.info(
        "Received user executions request",
        extra={
            "user_id": current_user.user_id,
            "status": status,
            "lang": lang,
            "limit": limit,
            "skip": skip,
        },
    )

    executions = await execution_service.get_user_executions(
        user_id=current_user.user_id,
        status=status,
        lang=lang,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        skip=skip
    )

    total_count = await execution_service.count_user_executions(
        user_id=current_user.user_id,
        status=status,
        lang=lang,
        start_time=start_time,
        end_time=end_time
    )

    execution_results = [
        ExecutionResult(
            execution_id=exec.execution_id,
            status=exec.status,
            output=exec.output,
            errors=exec.errors,
            lang=exec.lang,
            lang_version=exec.lang_version,
            resource_usage=ResourceUsage(**exec.resource_usage) if exec.resource_usage else None
        )
        for exec in executions
    ]

    return ExecutionListResponse(
        executions=execution_results,
        total=total_count,
        limit=limit,
        skip=skip,
        has_more=(skip + limit) < total_count
    )


@router.get("/example-scripts", response_model=ExampleScripts)
async def get_example_scripts(
        execution_service: ExecutionService = Depends(
            get_execution_service
        ),
) -> ExampleScripts:
    logger.info("Received example scripts request")
    scripts = await execution_service.get_example_scripts()
    logger.info("Example scripts retrieved successfully")
    return ExampleScripts(scripts=scripts)


@router.get("/k8s-limits", response_model=ResourceLimits)
async def get_k8s_resource_limits(
        execution_service: ExecutionService = Depends(
            get_execution_service
        ),
) -> ResourceLimits:
    logger.info("Retrieving K8s resource limits", extra={"endpoint": "/k8s-limits"})

    try:
        limits = await execution_service.get_k8s_resource_limits()
        logger.info(
            "K8s resource limits retrieved successfully", extra={"limits": limits}
        )
        return ResourceLimits(**limits)

    except Exception as e:
        logger.error(
            "Failed to retrieve K8s resource limits",
            extra={"error_type": type(e).__name__, "error_detail": str(e)},
        )
        raise HTTPException(
            status_code=500, detail="Failed to retrieve resource limits"
        ) from e


@router.delete("/{execution_id}")
@limiter.limit("10/minute")
async def delete_execution(
        request: Request,
        execution_id: str,
        execution_service: ExecutionService = Depends(
            get_execution_service
        ),
        current_user: UserResponse = Depends(require_admin),
) -> Dict[str, Any]:
    """Delete an execution and its associated data (admin only)."""
    logger.info(
        "Received execution deletion request",
        extra={
            "execution_id": execution_id,
            "admin_user": current_user.email,
        },
    )

    result = await execution_service.get_execution_result(execution_id)

    if not result:
        raise HTTPException(status_code=404, detail="Execution not found")

    await execution_service.delete_execution(execution_id)

    logger.warning(
        f"Execution {execution_id} deleted by admin {current_user.email}",
        extra={
            "execution_id": execution_id,
            "user_id": result.user_id,
            "status": result.status,
        }
    )

    return {
        "message": "Execution deleted successfully",
        "execution_id": execution_id
    }
