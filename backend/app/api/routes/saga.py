from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_current_user
from app.db.repositories.saga_repository import SagaRepository, get_saga_repository
from app.schemas_pydantic.saga import SagaListResponse, SagaStatusResponse
from app.schemas_pydantic.user import UserResponse
from app.services.saga import SagaState

router = APIRouter(prefix="/sagas", tags=["sagas"])


@router.get("/{saga_id}", response_model=SagaStatusResponse)
async def get_saga_status(
        saga_id: str,
        current_user: UserResponse = Depends(get_current_user),
        repository: SagaRepository = Depends(get_saga_repository),
) -> SagaStatusResponse:
    """Get status of a specific saga"""
    return await repository.get_saga_status(saga_id, current_user)


@router.get("/execution/{execution_id}", response_model=SagaListResponse)
async def get_execution_sagas(
        execution_id: str,
        state: Optional[SagaState] = Query(None, description="Filter by saga state"),
        current_user: UserResponse = Depends(get_current_user),
        repository: SagaRepository = Depends(get_saga_repository),
) -> SagaListResponse:
    """Get all sagas for a specific execution"""
    return await repository.get_execution_sagas(execution_id, state, current_user)


@router.get("/", response_model=SagaListResponse)
async def list_sagas(
        state: Optional[SagaState] = Query(None, description="Filter by saga state"),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        current_user: UserResponse = Depends(get_current_user),
        repository: SagaRepository = Depends(get_saga_repository),
) -> SagaListResponse:
    """List sagas with filtering and pagination"""
    return await repository.list_sagas(state, limit, offset, current_user)
