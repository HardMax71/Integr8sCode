from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.domain.enums.saga import SagaState


@dataclass
class Saga:
    """Domain model for saga."""

    saga_id: str
    saga_name: str
    execution_id: str
    state: SagaState
    current_step: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    compensated_steps: list[str] = field(default_factory=list)
    context_data: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    retry_count: int = 0


@dataclass
class SagaFilter:
    """Filter criteria for saga queries."""

    state: SagaState | None = None
    execution_ids: list[str] | None = None
    user_id: str | None = None
    saga_name: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    error_status: bool | None = None


@dataclass
class SagaQuery:
    """Query parameters for saga search."""

    filter: SagaFilter
    sort_by: str = "created_at"
    sort_order: str = "desc"
    limit: int = 100
    skip: int = 0


@dataclass
class SagaListResult:
    """Result of saga list query."""

    sagas: list[Saga]
    total: int
    skip: int
    limit: int
    has_more: bool = field(init=False)

    def __post_init__(self) -> None:
        """Calculate has_more after initialization."""
        self.has_more = (self.skip + len(self.sagas)) < self.total


@dataclass
class SagaDetail:
    """Detailed saga information."""

    saga: Saga
    execution_details: dict[str, Any] | None = None
    step_details: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SagaStatistics:
    """Saga statistics."""

    total_sagas: int
    sagas_by_state: dict[str, int] = field(default_factory=dict)
    sagas_by_name: dict[str, int] = field(default_factory=dict)
    average_duration_seconds: float = 0.0
    success_rate: float = 0.0
    failure_rate: float = 0.0
    compensation_rate: float = 0.0


@dataclass
class SagaConfig:
    """Configuration for saga orchestration (domain)."""

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


@dataclass
class SagaInstance:
    """Runtime instance of a saga execution (domain)."""

    saga_name: str
    execution_id: str
    state: SagaState = SagaState.CREATED
    saga_id: str = field(default_factory=lambda: str(uuid4()))
    current_step: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    compensated_steps: list[str] = field(default_factory=list)
    context_data: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    retry_count: int = 0


@dataclass
class DomainResourceAllocation:
    """Domain model for resource allocation."""

    allocation_id: str
    execution_id: str
    language: str
    cpu_request: str
    memory_request: str
    cpu_limit: str
    memory_limit: str
    status: str = "active"
    allocated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    released_at: datetime | None = None


@dataclass
class DomainResourceAllocationCreate:
    """Data for creating a resource allocation."""

    execution_id: str
    language: str
    cpu_request: str
    memory_request: str
    cpu_limit: str
    memory_limit: str
