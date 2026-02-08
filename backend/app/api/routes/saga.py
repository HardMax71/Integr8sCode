from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Query, Request

from app.domain.enums import SagaState
from app.schemas_pydantic.common import ErrorResponse
from app.schemas_pydantic.saga import (
    SagaCancellationResponse,
    SagaListResponse,
    SagaStatusResponse,
)
from app.schemas_pydantic.user import User
from app.services.auth_service import AuthService
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
    request: Request,
    saga_service: FromDishka[SagaService],
    auth_service: FromDishka[AuthService],
) -> SagaStatusResponse:
    """Get saga status by ID.

    Args:
        saga_id: The saga identifier
        request: FastAPI request object
        saga_service: Saga service from DI
        auth_service: Auth service from DI

    Returns:
        Saga status response

    Raises:
        HTTPException: 404 if saga not found, 403 if access denied
    """
    current_user = await auth_service.get_current_user(request)
    user = User.model_validate(current_user)
    saga = await saga_service.get_saga_with_access_check(saga_id, user)
    return SagaStatusResponse.model_validate(saga)


@router.get(
    "/execution/{execution_id}",
    response_model=SagaListResponse,
    responses={403: {"model": ErrorResponse, "description": "Access denied"}},
)
async def get_execution_sagas(
    execution_id: str,
    request: Request,
    saga_service: FromDishka[SagaService],
    auth_service: FromDishka[AuthService],
    state: Annotated[SagaState | None, Query(description="Filter by saga state")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    skip: Annotated[int, Query(ge=0)] = 0,
) -> SagaListResponse:
    """Get all sagas for an execution.

    Args:
        execution_id: The execution identifier
        request: FastAPI request object
        saga_service: Saga service from DI
        auth_service: Auth service from DI
        state: Optional state filter
        limit: Maximum number of results
        skip: Number of results to skip

    Returns:
        Paginated list of sagas for the execution

    Raises:
        HTTPException: 403 if access denied
    """
    current_user = await auth_service.get_current_user(request)
    user = User.model_validate(current_user)
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
    request: Request,
    saga_service: FromDishka[SagaService],
    auth_service: FromDishka[AuthService],
    state: Annotated[SagaState | None, Query(description="Filter by saga state")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    skip: Annotated[int, Query(ge=0)] = 0,
) -> SagaListResponse:
    """List sagas accessible by the current user.

    Args:
        request: FastAPI request object
        saga_service: Saga service from DI
        auth_service: Auth service from DI
        state: Optional state filter
        limit: Maximum number of results
        skip: Number of results to skip

    Returns:
        Paginated list of sagas
    """
    current_user = await auth_service.get_current_user(request)
    user = User.model_validate(current_user)
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
    request: Request,
    saga_service: FromDishka[SagaService],
    auth_service: FromDishka[AuthService],
) -> SagaCancellationResponse:
    """Cancel a running saga.

    Args:
        saga_id: The saga identifier
        request: FastAPI request object
        saga_service: Saga service from DI
        auth_service: Auth service from DI

    Returns:
        Cancellation response with success status

    Raises:
        HTTPException: 404 if not found, 403 if denied, 400 if invalid state
    """
    current_user = await auth_service.get_current_user(request)
    user = User.model_validate(current_user)
    success = await saga_service.cancel_saga(saga_id, user)

    return SagaCancellationResponse(
        success=success,
        message=("Saga cancelled successfully" if success else "Failed to cancel saga"),
        saga_id=saga_id,
    )
