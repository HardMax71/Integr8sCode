from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute, inject
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request

from app.api.dependencies import AuthService
from app.api.rate_limit import DynamicRateLimiter
from app.core.exceptions import IntegrationException
from app.core.tracing import EventAttributes, add_span_attributes
from app.core.utils import get_client_ip
from app.domain.enums.common import ErrorType
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.storage import ExecutionErrorType
from app.domain.enums.user import UserRole
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.mappers.execution_api_mapper import ExecutionApiMapper
from app.schemas_pydantic.execution import (
    CancelExecutionRequest,
    CancelResponse,
    DeleteResponse,
    ExampleScripts,
    ExecutionEventResponse,
    ExecutionInDB,
    ExecutionListResponse,
    ExecutionRequest,
    ExecutionResponse,
    ExecutionResult,
    ResourceLimits,
    RetryExecutionRequest,
)
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService
from app.services.idempotency import IdempotencyManager
from app.services.kafka_event_service import KafkaEventService

router = APIRouter(route_class=DishkaRoute)


@inject
async def get_execution_with_access(
        execution_id: Annotated[str, Path()],
        request: Request,
        execution_service: FromDishka[ExecutionService],
        auth_service: FromDishka[AuthService],
) -> ExecutionInDB:
    current_user = await auth_service.get_current_user(request)
    domain_exec = await execution_service.get_execution_result(execution_id)

    if domain_exec.user_id and domain_exec.user_id != current_user.user_id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")

    # Map domain to Pydantic for dependency consumer
    ru = None
    if domain_exec.resource_usage is not None:
        ru = domain_exec.resource_usage.to_dict()
    # Map error_type to public ErrorType in API model via mapper rules
    error_type = (ErrorType.SCRIPT_ERROR if domain_exec.error_type == ExecutionErrorType.SCRIPT_ERROR
                  else ErrorType.SYSTEM_ERROR) if domain_exec.error_type is not None else None
    return ExecutionInDB(
        execution_id=domain_exec.execution_id,
        script=domain_exec.script,
        status=domain_exec.status,
        output=domain_exec.output,
        errors=domain_exec.errors,
        lang=domain_exec.lang,
        lang_version=domain_exec.lang_version,
        resource_usage=ru,
        user_id=domain_exec.user_id,
        exit_code=domain_exec.exit_code,
        error_type=error_type,
        created_at=domain_exec.created_at,
        updated_at=domain_exec.updated_at,
    )


@router.post("/execute", response_model=ExecutionResponse, dependencies=[Depends(DynamicRateLimiter)])
async def create_execution(
        request: Request,
        execution: ExecutionRequest,
        execution_service: FromDishka[ExecutionService],
        auth_service: FromDishka[AuthService],
        idempotency_manager: FromDishka[IdempotencyManager],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExecutionResponse:
    current_user = await auth_service.get_current_user(request)

    add_span_attributes(
        **{
            "http.method": "POST",
            "http.route": "/api/v1/execute",
            "execution.language": execution.lang,
            "execution.language_version": execution.lang_version,
            "execution.script_length": len(execution.script),
            EventAttributes.USER_ID: current_user.user_id,
            "client.address": get_client_ip(request),
        }
    )

    # Handle idempotency if key provided
    pseudo_event = None
    if idempotency_key:
        # Create a pseudo-event for idempotency tracking
        pseudo_event = BaseEvent(
            event_id=str(uuid4()),
            event_type=EventType.EXECUTION_REQUESTED,
            timestamp=datetime.now(timezone.utc),
            metadata=EventMetadata(
                user_id=current_user.user_id,
                correlation_id=str(uuid4()),
                service_name="api",
                service_version="1.0.0"
            )
        )

        # Check for duplicate request using custom key
        idempotency_result = await idempotency_manager.check_and_reserve(
            event=pseudo_event,
            key_strategy="custom",
            custom_key=f"http:{current_user.user_id}:{idempotency_key}",
            ttl_seconds=86400  # 24 hours TTL for HTTP idempotency
        )

        if idempotency_result.is_duplicate and idempotency_result.result:
            # Return cached result if available
            cached_result = idempotency_result.result
            if isinstance(cached_result, dict):
                return ExecutionResponse(
                    execution_id=cached_result.get("execution_id", ""),
                    status=cached_result.get("status", ExecutionStatus.QUEUED)
                )

    try:
        client_ip = get_client_ip(request)
        user_agent = request.headers.get("user-agent")
        exec_result = await execution_service.execute_script(
            script=execution.script,
            lang=execution.lang,
            lang_version=execution.lang_version,
            user_id=current_user.user_id,
            client_ip=client_ip,
            user_agent=user_agent,
        )

        # Store result for idempotency if key was provided
        if idempotency_key and pseudo_event:
            await idempotency_manager.mark_completed(
                event=pseudo_event,
                result={
                    "execution_id": exec_result.execution_id,
                    "status": exec_result.status
                },
                key_strategy="custom",
                custom_key=f"http:{current_user.user_id}:{idempotency_key}"
            )

        return ExecutionApiMapper.to_response(exec_result)

    except IntegrationException as e:
        # Mark as failed for idempotency
        if idempotency_key and pseudo_event:
            await idempotency_manager.mark_failed(
                event=pseudo_event,
                error=str(e),
                key_strategy="custom",
                custom_key=f"http:{current_user.user_id}:{idempotency_key}"
            )
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    except Exception as e:
        # Mark as failed for idempotency
        if idempotency_key and pseudo_event:
            await idempotency_manager.mark_failed(
                event=pseudo_event,
                error=str(e),
                key_strategy="custom",
                custom_key=f"http:{current_user.user_id}:{idempotency_key}"
            )
        raise HTTPException(
            status_code=500,
            detail="Internal server error during script execution"
        ) from e


@router.get("/result/{execution_id}", response_model=ExecutionResult, dependencies=[Depends(DynamicRateLimiter)])
async def get_result(
        execution: Annotated[ExecutionInDB, Depends(get_execution_with_access)],
        request: Request,
) -> ExecutionResult:
    return ExecutionResult.model_validate(execution)


@router.post("/{execution_id}/cancel", response_model=CancelResponse, dependencies=[Depends(DynamicRateLimiter)])
async def cancel_execution(
        execution: Annotated[ExecutionInDB, Depends(get_execution_with_access)],
        cancel_request: CancelExecutionRequest,
        request: Request,
        event_service: FromDishka[KafkaEventService],
        auth_service: FromDishka[AuthService],
) -> CancelResponse:
    current_user = await auth_service.get_current_user(request)

    # Handle terminal states
    terminal_states = [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT]

    if execution.status in terminal_states:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel execution in {str(execution.status)} state"
        )

    # Handle idempotency - if already cancelled, return success
    if execution.status == ExecutionStatus.CANCELLED:
        return CancelResponse(
            execution_id=execution.execution_id,
            status="already_cancelled",
            message="Execution was already cancelled",
            event_id="-1"  # exact event_id unknown
        )

    event_id = await event_service.publish_execution_event(
        event_type=EventType.EXECUTION_CANCELLED,
        execution_id=execution.execution_id,
        status=ExecutionStatus.CANCELLED,
        user_id=current_user.user_id,
        metadata={
            "reason": cancel_request.reason or "User requested cancellation",
            "previous_status": execution.status,
        }
    )

    return CancelResponse(
        execution_id=execution.execution_id,
        status="cancellation_requested",
        message="Cancellation request submitted",
        event_id=event_id
    )


@router.post("/{execution_id}/retry", response_model=ExecutionResponse, dependencies=[Depends(DynamicRateLimiter)])
async def retry_execution(
        original_execution: Annotated[ExecutionInDB, Depends(get_execution_with_access)],
        retry_request: RetryExecutionRequest,
        request: Request,
        execution_service: FromDishka[ExecutionService],
        auth_service: FromDishka[AuthService],
) -> ExecutionResponse:
    """Retry a failed or completed execution."""
    current_user = await auth_service.get_current_user(request)

    if original_execution.status in [ExecutionStatus.RUNNING, ExecutionStatus.QUEUED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry execution in {original_execution.status} state"
        )

    # Convert UserResponse to User object
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    new_result = await execution_service.execute_script(
        script=original_execution.script,
        lang=original_execution.lang,
        lang_version=original_execution.lang_version,
        user_id=current_user.user_id,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    return ExecutionApiMapper.to_response(new_result)


@router.get("/executions/{execution_id}/events",
            response_model=list[ExecutionEventResponse],
            dependencies=[Depends(DynamicRateLimiter)])
async def get_execution_events(
        execution: Annotated[ExecutionInDB, Depends(get_execution_with_access)],
        event_service: FromDishka[EventService],
        request: Request,
        event_types: str | None = Query(
            None, description="Comma-separated event types to filter"
        ),
        limit: int = Query(100, ge=1, le=1000),
) -> list[ExecutionEventResponse]:
    """Get all events for an execution."""
    event_type_list = None
    if event_types:
        event_type_list = [t.strip() for t in event_types.split(",")]

    events = await event_service.get_events_by_aggregate(
        aggregate_id=execution.execution_id,
        event_types=event_type_list,
        limit=limit
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


@router.get("/user/executions", response_model=ExecutionListResponse, dependencies=[Depends(DynamicRateLimiter)])
async def get_user_executions(
        request: Request,
        execution_service: FromDishka[ExecutionService],
        auth_service: FromDishka[AuthService],
        status: ExecutionStatus | None = Query(None),
        lang: str | None = Query(None),
        start_time: datetime | None = Query(None),
        end_time: datetime | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        skip: int = Query(0, ge=0),
) -> ExecutionListResponse:
    """Get executions for the current user."""
    current_user = await auth_service.get_current_user(request)

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

    execution_results = [ExecutionApiMapper.to_result(e) for e in executions]

    return ExecutionListResponse(
        executions=execution_results,
        total=total_count,
        limit=limit,
        skip=skip,
        has_more=(skip + limit) < total_count
    )


@router.get("/example-scripts", response_model=ExampleScripts)
async def get_example_scripts(
        execution_service: FromDishka[ExecutionService],
) -> ExampleScripts:
    scripts = await execution_service.get_example_scripts()
    return ExampleScripts(scripts=scripts)


@router.get("/k8s-limits", response_model=ResourceLimits)
async def get_k8s_resource_limits(
        execution_service: FromDishka[ExecutionService],
) -> ResourceLimits:
    try:
        limits = await execution_service.get_k8s_resource_limits()
        return ResourceLimits(**limits)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail="Failed to retrieve resource limits"
        ) from e


@router.delete("/{execution_id}", response_model=DeleteResponse, dependencies=[Depends(DynamicRateLimiter)])
async def delete_execution(
        execution_id: str,
        request: Request,
        execution_service: FromDishka[ExecutionService],
        auth_service: FromDishka[AuthService],
) -> DeleteResponse:
    """Delete an execution and its associated data (admin only)."""
    _ = await auth_service.require_admin(request)
    await execution_service.delete_execution(execution_id)
    return DeleteResponse(
        message="Execution deleted successfully",
        execution_id=execution_id
    )
