from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypedDict

from app.domain.enums import EventType, ReplayStatus, ReplayTarget, ReplayType


@dataclass
class ReplayOperationResult:
    """Domain result for replay session operations."""

    session_id: str
    status: ReplayStatus
    message: str


@dataclass
class CleanupResult:
    """Domain result for cleanup operations."""

    removed_sessions: int
    message: str


# --8<-- [start:ReplayError]
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


# --8<-- [end:ReplayError]


# --8<-- [start:ReplayFilter]
@dataclass
class ReplayFilter:
    # Event selection filters
    event_ids: list[str] | None = None
    execution_id: str | None = None
    aggregate_id: str | None = None
    event_types: list[EventType] | None = None
    exclude_event_types: list[EventType] | None = None

    # Time range
    start_time: datetime | None = None
    end_time: datetime | None = None

    # Metadata filters
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


# --8<-- [end:ReplayFilter]


@dataclass
class ReplayConfig:
    replay_type: ReplayType
    target: ReplayTarget = ReplayTarget.KAFKA
    filter: ReplayFilter = field(default_factory=ReplayFilter)

    speed_multiplier: float = 1.0
    preserve_timestamps: bool = False
    batch_size: int = 100
    max_events: int | None = None

    target_file_path: str | None = None

    skip_errors: bool = True
    retry_failed: bool = False
    retry_attempts: int = 3

    enable_progress_tracking: bool = True


class ReplaySessionChanges(TypedDict, total=False):
    """Fields an update sets on a replay session; a missing key keeps the stored value."""

    status: ReplayStatus
    total_events: int
    replayed_events: int
    failed_events: int
    skipped_events: int
    replay_id: str
    completed_at: datetime | None
