from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query

from app.api.dependencies import admin_user
from app.db.docs import UserDocument
from app.domain.enums import ExecutionStatus, QueuePriority
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
    dependencies=[Depends(admin_user)],
)


@router.get(
    "/",
    responses={403: {"model": ErrorResponse}},
)
async def list_executions(
    _: Annotated[UserDocument, Depends(admin_user)],
    service: FromDishka[AdminExecutionService],
    status: Annotated[ExecutionStatus | None, Query()] = None,
    priority: Annotated[QueuePriority | None, Query()] = None,
    user_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    skip: Annotated[int, Query(ge=0)] = 0,
) -> AdminExecutionListResponse:
    executions, total = await service.list_executions(
        status=status,
        priority=priority,
        user_id=user_id,
        limit=limit,
        skip=skip,
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
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def update_priority(
    execution_id: str,
    body: PriorityUpdateRequest,
    _: Annotated[UserDocument, Depends(admin_user)],
    service: FromDishka[AdminExecutionService],
) -> AdminExecutionResponse:
    updated = await service.update_priority(execution_id, body.priority)
    return AdminExecutionResponse.model_validate(updated)


@router.get(
    "/queue",
    responses={403: {"model": ErrorResponse}},
)
async def get_queue_status(
    _: Annotated[UserDocument, Depends(admin_user)],
    service: FromDishka[AdminExecutionService],
) -> QueueStatusResponse:
    status = await service.get_queue_status()
    return QueueStatusResponse(**status)
