"""Saga schemas for distributed transaction management"""

from typing import List, Optional

from pydantic import BaseModel

from app.services.saga import SagaState


class SagaStatusResponse(BaseModel):
    """Response schema for saga status"""
    saga_id: str
    saga_name: str
    execution_id: str
    state: SagaState
    current_step: Optional[str]
    completed_steps: List[str]
    compensated_steps: List[str]
    error_message: Optional[str]
    created_at: str
    updated_at: str
    completed_at: Optional[str]
    retry_count: int


class SagaListResponse(BaseModel):
    """Response schema for saga list"""
    sagas: List[SagaStatusResponse]
    total: int
