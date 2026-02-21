from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import SagaState


class SagaStatusResponse(BaseModel):
    """Response schema for saga status"""

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

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

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    sagas: list[SagaStatusResponse]
    total: int
    skip: int
    limit: int
    has_more: bool


class SagaCancellationResponse(BaseModel):
    """Response schema for saga cancellation"""

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    success: bool
    message: str
    saga_id: str
