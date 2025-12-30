from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums.saga import SagaState


class SagaStatusResponse(BaseModel):
    """Response schema for saga status"""

    model_config = ConfigDict(from_attributes=True)

    saga_id: str
    saga_name: str
    execution_id: str
    state: SagaState
    current_step: str | None
    completed_steps: list[str]
    compensated_steps: list[str]
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    retry_count: int


class SagaListResponse(BaseModel):
    """Response schema for saga list"""

    sagas: list[SagaStatusResponse]
    total: int
    skip: int
    limit: int
    has_more: bool


class SagaCancellationResponse(BaseModel):
    """Response schema for saga cancellation"""

    success: bool
    message: str
    saga_id: str
