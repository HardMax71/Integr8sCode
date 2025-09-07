from pydantic import BaseModel

from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga


class SagaStatusResponse(BaseModel):
    """Response schema for saga status"""
    saga_id: str
    saga_name: str
    execution_id: str
    state: SagaState
    current_step: str | None
    completed_steps: list[str]
    compensated_steps: list[str]
    error_message: str | None
    created_at: str
    updated_at: str
    completed_at: str | None
    retry_count: int

    @classmethod
    def from_domain(cls, saga: "Saga") -> "SagaStatusResponse":
        """Create response from domain model."""
        return cls(
            saga_id=saga.saga_id,
            saga_name=saga.saga_name,
            execution_id=saga.execution_id,
            state=saga.state,
            current_step=saga.current_step,
            completed_steps=saga.completed_steps,
            compensated_steps=saga.compensated_steps,
            error_message=saga.error_message,
            created_at=saga.created_at.isoformat(),
            updated_at=saga.updated_at.isoformat(),
            completed_at=saga.completed_at.isoformat() if saga.completed_at else None,
            retry_count=saga.retry_count
        )


class SagaListResponse(BaseModel):
    """Response schema for saga list"""
    sagas: list[SagaStatusResponse]
    total: int


class SagaCancellationResponse(BaseModel):
    """Response schema for saga cancellation"""
    success: bool
    message: str
    saga_id: str
