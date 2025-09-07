from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import AuthService
from app.api.rate_limit import check_rate_limit
from app.domain.enums.saga import SagaState
from app.infrastructure.mappers.admin_mapper import UserMapper as AdminUserMapper
from app.infrastructure.mappers.saga_mapper import SagaResponseMapper
from app.schemas_pydantic.saga import (
    SagaCancellationResponse,
    SagaListResponse,
    SagaStatusResponse,
)
from app.schemas_pydantic.user import User
from app.services.saga_service import SagaService

router = APIRouter(
    prefix="/sagas",
    tags=["sagas"],
    route_class=DishkaRoute,
    dependencies=[Depends(check_rate_limit)]
)


@router.get("/{saga_id}", response_model=SagaStatusResponse)
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

    service_user = User.from_response(current_user)
    domain_user = AdminUserMapper.from_pydantic_service_user(service_user)
    saga = await saga_service.get_saga_with_access_check(saga_id, domain_user)
    mapper = SagaResponseMapper()
    return mapper.to_response(saga)


@router.get("/execution/{execution_id}", response_model=SagaListResponse)
async def get_execution_sagas(
        execution_id: str,
        request: Request,
        saga_service: FromDishka[SagaService],
        auth_service: FromDishka[AuthService],
        state: SagaState | None = Query(None, description="Filter by saga state"),
) -> SagaListResponse:
    """Get all sagas for an execution.
    
    Args:
        execution_id: The execution identifier
        request: FastAPI request object
        saga_service: Saga service from DI
        auth_service: Auth service from DI
        state: Optional state filter
        
    Returns:
        List of sagas for the execution
        
    Raises:
        HTTPException: 403 if access denied
    """
    current_user = await auth_service.get_current_user(request)

    service_user = User.from_response(current_user)
    domain_user = AdminUserMapper.from_pydantic_service_user(service_user)
    sagas = await saga_service.get_execution_sagas(execution_id, domain_user, state)
    mapper = SagaResponseMapper()
    saga_responses = mapper.list_to_responses(sagas)
    return SagaListResponse(sagas=saga_responses, total=len(saga_responses))


@router.get("/", response_model=SagaListResponse)
async def list_sagas(
        request: Request,
        saga_service: FromDishka[SagaService],
        auth_service: FromDishka[AuthService],
        state: SagaState | None = Query(None, description="Filter by saga state"),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
) -> SagaListResponse:
    """List sagas accessible by the current user.
    
    Args:
        request: FastAPI request object
        saga_service: Saga service from DI
        auth_service: Auth service from DI
        state: Optional state filter
        limit: Maximum number of results
        offset: Number of results to skip
        
    Returns:
        Paginated list of sagas
    """
    current_user = await auth_service.get_current_user(request)

    service_user = User.from_response(current_user)
    domain_user = AdminUserMapper.from_pydantic_service_user(service_user)
    result = await saga_service.list_user_sagas(
        domain_user,
        state,
        limit,
        offset
    )
    mapper = SagaResponseMapper()
    saga_responses = mapper.list_to_responses(result.sagas)
    return SagaListResponse(sagas=saga_responses, total=result.total)


@router.post("/{saga_id}/cancel", response_model=SagaCancellationResponse)
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

    service_user = User.from_response(current_user)
    domain_user = AdminUserMapper.from_pydantic_service_user(service_user)
    success = await saga_service.cancel_saga(saga_id, domain_user)

    return SagaCancellationResponse(
        success=success,
        message=(
            "Saga cancelled successfully" if success
            else "Failed to cancel saga"
        ),
        saga_id=saga_id
    )
