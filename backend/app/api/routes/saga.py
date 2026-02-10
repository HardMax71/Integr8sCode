from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query

from app.api.dependencies import current_user
from app.domain.enums import SagaState
from app.domain.user import User
from app.schemas_pydantic.common import ErrorResponse
from app.schemas_pydantic.saga import (
    SagaCancellationResponse,
    SagaListResponse,
    SagaStatusResponse,
)
from app.services.saga.saga_service import SagaService

router = APIRouter(
    prefix="/sagas",
    tags=["sagas"],
    route_class=DishkaRoute,
)


@router.get(
    "/{saga_id}",
    response_model=SagaStatusResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Access denied"},
        404: {"model": ErrorResponse, "description": "Saga not found"},
    },
)
async def get_saga_status(
    saga_id: str,
    user: Annotated[User, Depends(current_user)],
    saga_service: FromDishka[SagaService],
) -> SagaStatusResponse:
    """Get saga status by ID."""
    saga = await saga_service.get_saga_with_access_check(saga_id, user)
    return SagaStatusResponse.model_validate(saga)


@router.get(
    "/execution/{execution_id}",
    response_model=SagaListResponse,
    responses={403: {"model": ErrorResponse, "description": "Access denied"}},
)
async def get_execution_sagas(
    execution_id: str,
    user: Annotated[User, Depends(current_user)],
    saga_service: FromDishka[SagaService],
    state: Annotated[SagaState | None, Query(description="Filter by saga state")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    skip: Annotated[int, Query(ge=0)] = 0,
) -> SagaListResponse:
    """Get all sagas for an execution."""
    result = await saga_service.get_execution_sagas(execution_id, user, state, limit=limit, skip=skip)
    saga_responses = [SagaStatusResponse.model_validate(s) for s in result.sagas]
    return SagaListResponse(
        sagas=saga_responses,
        total=result.total,
        skip=skip,
        limit=limit,
        has_more=result.has_more,
    )


@router.get("/", response_model=SagaListResponse)
async def list_sagas(
    user: Annotated[User, Depends(current_user)],
    saga_service: FromDishka[SagaService],
    state: Annotated[SagaState | None, Query(description="Filter by saga state")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    skip: Annotated[int, Query(ge=0)] = 0,
) -> SagaListResponse:
    """List sagas accessible by the current user."""
    result = await saga_service.list_user_sagas(user, state, limit, skip)
    saga_responses = [SagaStatusResponse.model_validate(s) for s in result.sagas]
    return SagaListResponse(
        sagas=saga_responses,
        total=result.total,
        skip=skip,
        limit=limit,
        has_more=result.has_more,
    )


@router.post(
    "/{saga_id}/cancel",
    response_model=SagaCancellationResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Saga is not in a cancellable state"},
        403: {"model": ErrorResponse, "description": "Access denied"},
        404: {"model": ErrorResponse, "description": "Saga not found"},
    },
)
async def cancel_saga(
    saga_id: str,
    user: Annotated[User, Depends(current_user)],
    saga_service: FromDishka[SagaService],
) -> SagaCancellationResponse:
    """Cancel a running saga."""
    success = await saga_service.cancel_saga(saga_id, user)

    return SagaCancellationResponse(
        success=success,
        message=("Saga cancelled successfully" if success else "Failed to cancel saga"),
        saga_id=saga_id,
    )
