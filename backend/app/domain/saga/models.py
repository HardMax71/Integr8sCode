from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.domain.enums import SagaState


@dataclass
class SagaContextData:
    """Typed saga execution context. Populated incrementally by saga steps."""

    execution_id: str = ""
    language: str = ""
    language_version: str | None = None
    script: str = ""
    timeout_seconds: int | None = None
    allocation_id: str | None = None
    resources_allocated: bool = False
    pod_creation_triggered: bool = False
    user_id: str = field(default_factory=lambda: str(uuid4()))


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
    context_data: SagaContextData = field(default_factory=SagaContextData)
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    retry_count: int = 0

    def __post_init__(self) -> None:
        raw: Any = self.context_data
        if isinstance(raw, dict):
            self.context_data = SagaContextData(**raw)


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

    def __post_init__(self) -> None:
        raw: Any = self.filter
        if isinstance(raw, dict):
            self.filter = SagaFilter(**raw)


@dataclass
class SagaListResult:
    """Result of saga list query."""

    sagas: list[Saga]
    total: int
    skip: int
    limit: int

    @property
    def has_more(self) -> bool:
        """Calculate has_more."""
        return (self.skip + len(self.sagas)) < self.total


@dataclass
class SagaCancellationResult:
    """Result of saga cancellation."""

    success: bool
    message: str
    saga_id: str


@dataclass
class SagaConfig:
    """Configuration for saga orchestration (domain)."""

    name: str
    timeout_seconds: int = 300
    max_retries: int = 3
    retry_delay_seconds: int = 5
    enable_compensation: bool = True
    store_events: bool = True
    publish_commands: bool = False


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
