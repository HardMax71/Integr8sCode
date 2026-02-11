from datetime import datetime
from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute, inject
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request

from app.api.dependencies import admin_user, current_user
from app.core.tracing import EventAttributes, add_span_attributes
from app.core.utils import get_client_ip
from app.domain.enums import EventType, ExecutionStatus, UserRole
from app.domain.events import DomainEvent
from app.domain.user import User
from app.schemas_pydantic.common import ErrorResponse
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
)
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService

router = APIRouter(route_class=DishkaRoute, tags=["execution"])


@inject
async def get_execution_with_access(
        execution_id: Annotated[str, Path()],
        current_user: Annotated[User, Depends(current_user)],
        execution_service: FromDishka[ExecutionService],
) -> ExecutionInDB:
    domain_exec = await execution_service.get_execution_result(execution_id)

    if domain_exec.user_id and domain_exec.user_id != current_user.user_id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")

    return ExecutionInDB.model_validate(domain_exec)


@router.post(
    "/execute",
    response_model=ExecutionResponse,
    responses={500: {"model": ErrorResponse, "description": "Script execution failed"}},
)
async def create_execution(
        request: Request,
        current_user: Annotated[User, Depends(current_user)],
        execution: ExecutionRequest,
        execution_service: FromDishka[ExecutionService],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExecutionResponse:
    """Submit a script for execution in an isolated Kubernetes pod."""
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

    exec_result = await execution_service.execute_script_idempotent(
        script=execution.script,
        lang=execution.lang,
        lang_version=execution.lang_version,
        user_id=current_user.user_id,
        idempotency_key=idempotency_key,
    )
    return ExecutionResponse.model_validate(exec_result)


@router.get(
    "/executions/{execution_id}/result",
    response_model=ExecutionResult,
    responses={403: {"model": ErrorResponse, "description": "Not the owner of this execution"}},
)
async def get_result(
        execution: Annotated[ExecutionInDB, Depends(get_execution_with_access)],
) -> ExecutionResult:
    """Retrieve the result of a specific execution."""
    return ExecutionResult.model_validate(execution)


@router.post(
    "/executions/{execution_id}/cancel",
    response_model=CancelResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Execution is in a terminal state"},
        403: {"model": ErrorResponse, "description": "Not the owner of this execution"},
    },
)
async def cancel_execution(
        execution: Annotated[ExecutionInDB, Depends(get_execution_with_access)],
        current_user: Annotated[User, Depends(current_user)],
        cancel_request: CancelExecutionRequest,
        execution_service: FromDishka[ExecutionService],
) -> CancelResponse:
    """Cancel a running or queued execution."""
    result = await execution_service.cancel_execution(
        execution_id=execution.execution_id,
        current_status=execution.status,
        user_id=current_user.user_id,
        reason=cancel_request.reason,
    )
    return CancelResponse.model_validate(result)


@router.post(
    "/executions/{execution_id}/retry",
    response_model=ExecutionResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Execution is still running or queued"},
        403: {"model": ErrorResponse, "description": "Not the owner of this execution"},
    },
)
async def retry_execution(
        original_execution: Annotated[ExecutionInDB, Depends(get_execution_with_access)],
        current_user: Annotated[User, Depends(current_user)],
        execution_service: FromDishka[ExecutionService],
) -> ExecutionResponse:
    """Retry a failed or completed execution."""

    if original_execution.status in [ExecutionStatus.RUNNING, ExecutionStatus.QUEUED]:
        raise HTTPException(status_code=400, detail=f"Cannot retry execution in {original_execution.status} state")

    new_result = await execution_service.execute_script(
        script=original_execution.script,
        lang=original_execution.lang,
        lang_version=original_execution.lang_version,
        user_id=current_user.user_id,
    )
    return ExecutionResponse.model_validate(new_result)


@router.get(
    "/executions/{execution_id}/events",
    response_model=list[DomainEvent],
    responses={403: {"model": ErrorResponse, "description": "Not the owner of this execution"}},
)
async def get_execution_events(
        execution: Annotated[ExecutionInDB, Depends(get_execution_with_access)],
        event_service: FromDishka[EventService],
        event_types: Annotated[list[EventType] | None, Query(description="Event types to filter")] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[DomainEvent]:
    """Get all events for an execution."""
    events = await event_service.get_events_by_aggregate(
        aggregate_id=execution.execution_id, event_types=event_types, limit=limit
    )
    return events


@router.get("/user/executions", response_model=ExecutionListResponse)
async def get_user_executions(
        current_user: Annotated[User, Depends(current_user)],
        execution_service: FromDishka[ExecutionService],
        status: Annotated[ExecutionStatus | None, Query(description="Filter by execution status")] = None,
        lang: Annotated[str | None, Query(description="Filter by programming language")] = None,
        start_time: Annotated[datetime | None, Query(description="Filter executions created after this time")] = None,
        end_time: Annotated[datetime | None, Query(description="Filter executions created before this time")] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        skip: Annotated[int, Query(ge=0)] = 0,
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
    """Get example scripts for the code editor."""
    scripts = await execution_service.get_example_scripts()
    return ExampleScripts(scripts=scripts)


@router.get("/k8s-limits", response_model=ResourceLimits)
async def get_k8s_resource_limits(
        execution_service: FromDishka[ExecutionService],
) -> ResourceLimits:
    """Get Kubernetes resource limits for script execution."""
    limits = await execution_service.get_k8s_resource_limits()
    return ResourceLimits.model_validate(limits)


@router.delete("/executions/{execution_id}", response_model=DeleteResponse)
async def delete_execution(
        execution_id: str,
        admin: Annotated[User, Depends(admin_user)],
        execution_service: FromDishka[ExecutionService],
) -> DeleteResponse:
    """Delete an execution and its associated data (admin only)."""
    await execution_service.delete_execution(execution_id, admin.user_id)
    return DeleteResponse(message="Execution deleted successfully", execution_id=execution_id)
