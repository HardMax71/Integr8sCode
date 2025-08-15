from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_current_user
from app.core.logging import logger
from app.core.service_dependencies import SagaOrchestratorDep, SagaRepositoryDep
from app.schemas_pydantic.saga import SagaCancellationResponse, SagaListResponse, SagaStatusResponse
from app.schemas_pydantic.user import UserResponse, UserRole
from app.services.saga import SagaState

router = APIRouter(prefix="/sagas", tags=["sagas"])


@router.get("/{saga_id}", response_model=SagaStatusResponse)
async def get_saga_status(
        saga_id: str,
        repository: SagaRepositoryDep,
        orchestrator: SagaOrchestratorDep,
        current_user: UserResponse = Depends(get_current_user),
) -> SagaStatusResponse:
    """Get status of a specific saga"""
    return await repository.get_saga_status(saga_id, current_user, orchestrator)


@router.get("/execution/{execution_id}", response_model=SagaListResponse)
async def get_execution_sagas(
        execution_id: str,
        repository: SagaRepositoryDep,
        orchestrator: SagaOrchestratorDep,
        state: SagaState | None = Query(None, description="Filter by saga state"),
        current_user: UserResponse = Depends(get_current_user),
) -> SagaListResponse:
    """Get all sagas for a specific execution"""
    return await repository.get_execution_sagas(execution_id, state, current_user, orchestrator)


@router.get("/", response_model=SagaListResponse)
async def list_sagas(
        repository: SagaRepositoryDep,
        state: SagaState | None = Query(None, description="Filter by saga state"),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        current_user: UserResponse = Depends(get_current_user),
) -> SagaListResponse:
    """List sagas with filtering and pagination"""
    return await repository.list_sagas(state, limit, offset, current_user)


@router.post("/{saga_id}/cancel", response_model=SagaCancellationResponse)
async def cancel_saga(
        saga_id: str,
        repository: SagaRepositoryDep,
        orchestrator: SagaOrchestratorDep,
        current_user: UserResponse = Depends(get_current_user),
) -> SagaCancellationResponse:
    """Cancel a running saga and trigger compensation.
    
    Only the saga owner or admin users can cancel a saga.
    Cancellation will trigger compensation for any completed steps.
    """
    try:
        # Get saga to check ownership
        saga_status = await orchestrator.get_saga_status(saga_id)
        if not saga_status:
            raise HTTPException(status_code=404, detail="Saga not found")
        
        # Check if user has permission to cancel
        if current_user.role != UserRole.ADMIN:
            # Get execution to check ownership
            execution = await repository.db.executions.find_one({
                "execution_id": saga_status.execution_id,
                "user_id": current_user.user_id
            })
            
            if not execution:
                raise HTTPException(
                    status_code=403,
                    detail="You don't have permission to cancel this saga"
                )
        
        # Cancel the saga
        success = await orchestrator.cancel_saga(saga_id)
        
        if success:
            logger.info(f"User {current_user.user_id} cancelled saga {saga_id}")
            return SagaCancellationResponse(
                success=True,
                message="Saga cancelled successfully",
                saga_id=saga_id
            )
        else:
            return SagaCancellationResponse(
                success=False,
                message="Failed to cancel saga - check if saga is in a cancellable state",
                saga_id=saga_id
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling saga {saga_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e
