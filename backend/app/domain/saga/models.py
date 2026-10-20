from dataclasses import dataclass, field
from datetime import datetime
from typing import TypedDict
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
    pod_creation_triggered: bool = False
    user_id: str = field(default_factory=lambda: str(uuid4()))


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
    search: str | None = None


@dataclass
class SagaQuery:
    """Query parameters for saga search."""

    filter: SagaFilter
    sort_by: str = "created_at"
    sort_order: str = "desc"
    limit: int = 100
    skip: int = 0


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
    publish_commands: bool = True


@dataclass
class SagaCancellationResult:
    """Domain result for saga cancellation operations."""

    success: bool
    message: str
    saga_id: str


class SagaChanges(TypedDict, total=False):
    """Fields a saga step or the orchestrator writes; a missing key keeps the stored value."""

    state: SagaState
    current_step: str | None
    completed_steps: list[str]
    compensated_steps: list[str]
    context_data: SagaContextData
    error_message: str | None
    completed_at: datetime | None
    retry_count: int
