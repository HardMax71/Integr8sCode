from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domain.enums.saga import SagaState


class Saga(BaseModel):
    """Domain model for saga."""

    model_config = ConfigDict(from_attributes=True)

    saga_id: str
    saga_name: str
    execution_id: str
    state: SagaState
    current_step: str | None = None
    completed_steps: list[str] = Field(default_factory=list)
    compensated_steps: list[str] = Field(default_factory=list)
    context_data: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    retry_count: int = 0


class SagaFilter(BaseModel):
    """Filter criteria for saga queries."""

    model_config = ConfigDict(from_attributes=True)

    state: SagaState | None = None
    execution_ids: list[str] | None = None
    user_id: str | None = None
    saga_name: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    error_status: bool | None = None


class SagaQuery(BaseModel):
    """Query parameters for saga search."""

    model_config = ConfigDict(from_attributes=True)

    filter: SagaFilter
    sort_by: str = "created_at"
    sort_order: str = "desc"
    limit: int = 100
    skip: int = 0


class SagaListResult(BaseModel):
    """Result of saga list query."""

    model_config = ConfigDict(from_attributes=True)

    sagas: list[Saga]
    total: int
    skip: int
    limit: int

    @property
    def has_more(self) -> bool:
        """Calculate has_more."""
        return (self.skip + len(self.sagas)) < self.total


class SagaDetail(BaseModel):
    """Detailed saga information."""

    model_config = ConfigDict(from_attributes=True)

    saga: Saga
    execution_details: dict[str, Any] | None = None
    step_details: list[dict[str, Any]] = Field(default_factory=list)


class SagaStatistics(BaseModel):
    """Saga statistics."""

    model_config = ConfigDict(from_attributes=True)

    total_sagas: int
    sagas_by_state: dict[str, int] = Field(default_factory=dict)
    sagas_by_name: dict[str, int] = Field(default_factory=dict)
    average_duration_seconds: float = 0.0
    success_rate: float = 0.0
    failure_rate: float = 0.0
    compensation_rate: float = 0.0


class SagaConfig(BaseModel):
    """Configuration for saga orchestration (domain)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    timeout_seconds: int = 300
    max_retries: int = 3
    retry_delay_seconds: int = 5
    enable_compensation: bool = True
    store_events: bool = True
    # When True, saga steps publish orchestration commands (e.g., to k8s worker).
    # Keep False when another component (e.g., coordinator) publishes commands
    # to avoid duplicate actions while still creating saga instances.
    publish_commands: bool = False


class SagaInstance(BaseModel):
    """Runtime instance of a saga execution (domain)."""

    model_config = ConfigDict(from_attributes=True)

    saga_name: str
    execution_id: str
    state: SagaState = SagaState.CREATED
    saga_id: str = Field(default_factory=lambda: str(uuid4()))
    current_step: str | None = None
    completed_steps: list[str] = Field(default_factory=list)
    compensated_steps: list[str] = Field(default_factory=list)
    context_data: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    retry_count: int = 0


class DomainResourceAllocation(BaseModel):
    """Domain model for resource allocation."""

    model_config = ConfigDict(from_attributes=True)

    allocation_id: str
    execution_id: str
    language: str
    cpu_request: str
    memory_request: str
    cpu_limit: str
    memory_limit: str
    status: str = "active"
    allocated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    released_at: datetime | None = None


class DomainResourceAllocationCreate(BaseModel):
    """Data for creating a resource allocation."""

    model_config = ConfigDict(from_attributes=True)

    execution_id: str
    language: str
    cpu_request: str
    memory_request: str
    cpu_limit: str
    memory_limit: str
