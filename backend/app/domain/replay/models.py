from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.domain.enums import EventType, KafkaTopic, ReplayStatus, ReplayTarget, ReplayType


@dataclass
class ReplayError:
    """Error details for replay operations.

    Attributes:
        timestamp: When the error occurred.
        error: Human-readable error message.
        error_type: Python exception class name (e.g., "ValueError", "KafkaException").
            This is the result of `type(exception).__name__`, NOT the ErrorType enum.
            Present for session-level errors.
        event_id: ID of the event that failed to replay. Present for event-level errors.
    """

    timestamp: datetime
    error: str
    error_type: str | None = None
    event_id: str | None = None


@dataclass
class ReplayFilter:
    event_ids: list[str] | None = None
    execution_id: str | None = None
    aggregate_id: str | None = None
    event_types: list[EventType] | None = None
    exclude_event_types: list[EventType] | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    user_id: str | None = None
    service_name: str | None = None

    def is_empty(self) -> bool:
        return not any(
            [
                self.event_ids,
                self.execution_id,
                self.aggregate_id,
                self.event_types,
                self.start_time,
                self.end_time,
                self.user_id,
                self.service_name,
            ]
        )

    def to_mongo_query(self) -> dict[str, Any]:
        query: dict[str, Any] = {}

        if self.event_ids:
            query["event_id"] = {"$in": self.event_ids}

        if self.execution_id:
            query["execution_id"] = self.execution_id

        if self.aggregate_id:
            query["aggregate_id"] = self.aggregate_id

        if self.event_types:
            query["event_type"] = {"$in": list(self.event_types)}

        if self.exclude_event_types:
            if "event_type" in query:
                query["event_type"]["$nin"] = list(self.exclude_event_types)
            else:
                query["event_type"] = {"$nin": list(self.exclude_event_types)}

        if self.start_time or self.end_time:
            time_query: dict[str, Any] = {}
            if self.start_time:
                time_query["$gte"] = self.start_time
            if self.end_time:
                time_query["$lte"] = self.end_time
            query["timestamp"] = time_query

        if self.user_id:
            query["metadata.user_id"] = self.user_id

        if self.service_name:
            query["metadata.service_name"] = self.service_name

        return query


@dataclass
class ReplayConfig:
    replay_type: ReplayType
    target: ReplayTarget = ReplayTarget.KAFKA
    filter: ReplayFilter = field(default_factory=ReplayFilter)
    speed_multiplier: float = 1.0
    preserve_timestamps: bool = False
    batch_size: int = 100
    max_events: int | None = None
    target_topics: dict[EventType, KafkaTopic] | None = None
    target_file_path: str | None = None
    skip_errors: bool = True
    retry_failed: bool = False
    retry_attempts: int = 3
    enable_progress_tracking: bool = True

    def __post_init__(self) -> None:
        raw: Any = self.filter
        if isinstance(raw, dict):
            self.filter = ReplayFilter(**raw)
        if not (0.1 <= self.speed_multiplier <= 100.0):
            raise ValueError("speed_multiplier must be between 0.1 and 100.0")
        if not (1 <= self.batch_size <= 1000):
            raise ValueError("batch_size must be between 1 and 1000")
        if self.max_events is not None and self.max_events < 1:
            raise ValueError("max_events must be >= 1")


@dataclass
class ReplaySessionState:
    """Domain replay session model used by services and repository."""

    session_id: str
    config: ReplayConfig
    status: ReplayStatus = ReplayStatus.CREATED
    total_events: int = 0
    replayed_events: int = 0
    failed_events: int = 0
    skipped_events: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_event_at: datetime | None = None
    errors: list[ReplayError] = field(default_factory=list)
    replay_id: str = field(default_factory=lambda: str(uuid4()))
    created_by: str | None = None
    target_service: str | None = None
    dry_run: bool = False
    triggered_executions: list[str] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        raw: Any = self.config
        if isinstance(raw, dict):
            self.config = ReplayConfig(**raw)
        raw_errors: Any = self.errors
        self.errors = [ReplayError(**e) if isinstance(e, dict) else e for e in raw_errors]


@dataclass
class ReplayOperationResult:
    session_id: str
    status: ReplayStatus
    message: str


@dataclass
class CleanupResult:
    removed_sessions: int
    message: str
