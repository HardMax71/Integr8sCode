"""Saga schemas for distributed transaction management"""

from typing import Optional

from pydantic import BaseModel

from app.services.saga import SagaState


class SagaStatusResponse(BaseModel):
    """Response schema for saga status"""
    saga_id: str
    saga_name: str
    execution_id: str
    state: SagaState
    current_step: Optional[str]
    completed_steps: list[str]
    compensated_steps: list[str]
    error_message: Optional[str]
    created_at: str
    updated_at: str
    completed_at: Optional[str]
    retry_count: int


class SagaListResponse(BaseModel):
    """Response schema for saga list"""
    sagas: list[SagaStatusResponse]
    total: int


class SagaCancellationResponse(BaseModel):
    """Response schema for saga cancellation"""
    success: bool
    message: str
    saga_id: str
