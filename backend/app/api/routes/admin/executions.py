from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import admin_user
from app.domain.enums import ExecutionStatus, QueuePriority
from app.domain.execution import ExecutionNotFoundError
from app.domain.user import User
from app.schemas_pydantic.admin_executions import (
    AdminExecutionListResponse,
    AdminExecutionResponse,
    PriorityUpdateRequest,
    QueueStatusResponse,
)
from app.schemas_pydantic.common import ErrorResponse
from app.services.admin import AdminExecutionService

router = APIRouter(
    prefix="/admin/executions",
    tags=["admin-executions"],
    route_class=DishkaRoute,
)


@router.get(
    "/",
    response_model=AdminExecutionListResponse,
    responses={403: {"model": ErrorResponse}},
)
async def list_executions(
    _: Annotated[User, Depends(admin_user)],
    service: FromDishka[AdminExecutionService],
    status: ExecutionStatus | None = Query(None),
    priority: QueuePriority | None = Query(None),
    user_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
) -> AdminExecutionListResponse:
    executions, total = await service.list_executions(
        status=status, priority=priority, user_id=user_id, limit=limit, skip=skip,
    )
    return AdminExecutionListResponse(
        executions=[AdminExecutionResponse.model_validate(e) for e in executions],
        total=total,
        limit=limit,
        skip=skip,
        has_more=(skip + len(executions)) < total,
    )


@router.put(
    "/{execution_id}/priority",
    response_model=AdminExecutionResponse,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def update_priority(
    execution_id: str,
    body: PriorityUpdateRequest,
    _: Annotated[User, Depends(admin_user)],
    service: FromDishka[AdminExecutionService],
) -> AdminExecutionResponse:
    try:
        updated = await service.update_priority(execution_id, body.priority)
    except ExecutionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
    return AdminExecutionResponse.model_validate(updated)


@router.get(
    "/queue",
    response_model=QueueStatusResponse,
    responses={403: {"model": ErrorResponse}},
)
async def get_queue_status(
    _: Annotated[User, Depends(admin_user)],
    service: FromDishka[AdminExecutionService],
) -> QueueStatusResponse:
    status = await service.get_queue_status()
    return QueueStatusResponse(**status)
