from datetime import datetime
from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute, inject
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request

from app.api.dependencies import admin_user, current_user
from app.core.tracing import EventAttributes, add_span_attributes
from app.core.utils import get_client_ip
from app.db.repositories.redis.idempotency_repository import IdempotencyRepository
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.user import UserRole
from app.domain.events.typed import DomainEvent, EventMetadata
from app.domain.exceptions import DomainError
from app.schemas_pydantic.execution import (
    CancelExecutionRequest,
    CancelResponse,
    DeleteResponse,
    ExampleScripts,
    ExecutionInDB,
    ExecutionListResponse,
    ExecutionRequest,
    ExecutionResponse,
    ExecutionResult,
    ResourceLimits,
    RetryExecutionRequest,
)
from app.schemas_pydantic.user import UserResponse
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService
from app.services.kafka_event_service import KafkaEventService
from app.settings import Settings

router = APIRouter(route_class=DishkaRoute, tags=["execution"])


@inject
async def get_execution_with_access(
        execution_id: Annotated[str, Path()],
        current_user: Annotated[UserResponse, Depends(current_user)],
        execution_service: FromDishka[ExecutionService],
) -> ExecutionInDB:
    domain_exec = await execution_service.get_execution_result(execution_id)

    if domain_exec.user_id and domain_exec.user_id != current_user.user_id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")

    return ExecutionInDB.model_validate(domain_exec)


@router.post("/execute", response_model=ExecutionResponse)
async def create_execution(
        request: Request,
        current_user: Annotated[UserResponse, Depends(current_user)],
        execution: ExecutionRequest,
        execution_service: FromDishka[ExecutionService],
        idempotency_repo: FromDishka[IdempotencyRepository],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExecutionResponse:
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
    idem_key = f"exec:{current_user.user_id}:{idempotency_key}" if idempotency_key else None

    if idem_key:
        is_new = await idempotency_repo.try_reserve(idem_key, ttl=86400)
        if not is_new:
            cached = await idempotency_repo.get_result(idem_key)
            if cached:
                return ExecutionResponse.model_validate_json(cached)

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

        response = ExecutionResponse.model_validate(exec_result)

        if idem_key:
            await idempotency_repo.store_result(idem_key, response.model_dump_json(), ttl=86400)

        return response

    except DomainError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error during script execution") from e


@router.get("/executions/{execution_id}/result", response_model=ExecutionResult)
async def get_result(
        execution: Annotated[ExecutionInDB, Depends(get_execution_with_access)],
) -> ExecutionResult:
    return ExecutionResult.model_validate(execution)


@router.post("/executions/{execution_id}/cancel", response_model=CancelResponse)
async def cancel_execution(
        execution: Annotated[ExecutionInDB, Depends(get_execution_with_access)],
        current_user: Annotated[UserResponse, Depends(current_user)],
        cancel_request: CancelExecutionRequest,
        event_service: FromDishka[KafkaEventService],
        settings: FromDishka[Settings],
) -> CancelResponse:
    # Handle terminal states
    terminal_states = [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT]

    if execution.status in terminal_states:
        raise HTTPException(status_code=400, detail=f"Cannot cancel execution in {str(execution.status)} state")

    # Handle idempotency - if already cancelled, return success
    if execution.status == ExecutionStatus.CANCELLED:
        return CancelResponse(
            execution_id=execution.execution_id,
            status="already_cancelled",
            message="Execution was already cancelled",
            event_id="-1",  # exact event_id unknown
        )

    payload = {
        "execution_id": execution.execution_id,
        "status": str(ExecutionStatus.CANCELLED),
        "reason": cancel_request.reason or "User requested cancellation",
        "previous_status": str(execution.status),
    }
    meta = EventMetadata(
        service_name=settings.SERVICE_NAME,
        service_version=settings.SERVICE_VERSION,
        user_id=current_user.user_id,
    )
    event_id = await event_service.publish_event(
        event_type=EventType.EXECUTION_CANCELLED,
        payload=payload,
        aggregate_id=execution.execution_id,
        metadata=meta,
    )

    return CancelResponse(
        execution_id=execution.execution_id,
        status="cancellation_requested",
        message="Cancellation request submitted",
        event_id=event_id,
    )


@router.post("/executions/{execution_id}/retry", response_model=ExecutionResponse)
async def retry_execution(
        original_execution: Annotated[ExecutionInDB, Depends(get_execution_with_access)],
        current_user: Annotated[UserResponse, Depends(current_user)],
        retry_request: RetryExecutionRequest,
        request: Request,
        execution_service: FromDishka[ExecutionService],
) -> ExecutionResponse:
    """Retry a failed or completed execution."""

    if original_execution.status in [ExecutionStatus.RUNNING, ExecutionStatus.QUEUED]:
        raise HTTPException(status_code=400, detail=f"Cannot retry execution in {original_execution.status} state")

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
    return ExecutionResponse.model_validate(new_result)


@router.get("/executions/{execution_id}/events", response_model=list[DomainEvent])
async def get_execution_events(
        execution: Annotated[ExecutionInDB, Depends(get_execution_with_access)],
        event_service: FromDishka[EventService],
        event_types: list[EventType] | None = Query(None, description="Event types to filter"),
        limit: int = Query(100, ge=1, le=1000),
) -> list[DomainEvent]:
    """Get all events for an execution."""
    events = await event_service.get_events_by_aggregate(
        aggregate_id=execution.execution_id, event_types=event_types, limit=limit
    )
    return events


@router.get("/user/executions", response_model=ExecutionListResponse)
async def get_user_executions(
        current_user: Annotated[UserResponse, Depends(current_user)],
        execution_service: FromDishka[ExecutionService],
        status: ExecutionStatus | None = Query(None),
        lang: str | None = Query(None),
        start_time: datetime | None = Query(None),
        end_time: datetime | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        skip: int = Query(0, ge=0),
) -> ExecutionListResponse:
    """Get executions for the current user."""

    executions = await execution_service.get_user_executions(
        user_id=current_user.user_id,
        status=status,
        lang=lang,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        skip=skip,
    )

    total_count = await execution_service.count_user_executions(
        user_id=current_user.user_id, status=status, lang=lang, start_time=start_time, end_time=end_time
    )

    execution_results = [ExecutionResult.model_validate(e) for e in executions]

    return ExecutionListResponse(
        executions=execution_results, total=total_count, limit=limit, skip=skip, has_more=(skip + limit) < total_count
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
        return ResourceLimits.model_validate(limits)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to retrieve resource limits") from e


@router.delete("/executions/{execution_id}", response_model=DeleteResponse)
async def delete_execution(
        execution_id: str,
        admin: Annotated[UserResponse, Depends(admin_user)],
        execution_service: FromDishka[ExecutionService],
) -> DeleteResponse:
    """Delete an execution and its associated data (admin only)."""
    await execution_service.delete_execution(execution_id)
    return DeleteResponse(message="Execution deleted successfully", execution_id=execution_id)
