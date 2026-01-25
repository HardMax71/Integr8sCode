from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from app.domain.enums.events import EventType
from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType


class ReplayError(BaseModel):
    """Error details for replay operations."""

    model_config = ConfigDict(from_attributes=True)

    timestamp: str
    error: str
    type: str | None = None  # Present for session-level errors
    event_id: str | None = None  # Present for event-level errors


class ReplayFilter(BaseModel):
    # Event selection filters
    event_ids: List[str] | None = None
    execution_id: str | None = None
    correlation_id: str | None = None
    aggregate_id: str | None = None
    event_types: List[EventType] | None = None
    exclude_event_types: List[EventType] | None = None

    # Time range
    start_time: datetime | None = None
    end_time: datetime | None = None

    # Metadata filters
    user_id: str | None = None
    service_name: str | None = None

    # Escape hatch for complex queries
    custom_query: Dict[str, Any] | None = None

    def is_empty(self) -> bool:
        return not any(
            [
                self.event_ids,
                self.execution_id,
                self.correlation_id,
                self.aggregate_id,
                self.event_types,
                self.start_time,
                self.end_time,
                self.user_id,
                self.service_name,
                self.custom_query,
            ]
        )

    def to_mongo_query(self) -> Dict[str, Any]:
        query: Dict[str, Any] = {}

        if self.event_ids:
            query["event_id"] = {"$in": self.event_ids}

        if self.execution_id:
            query["execution_id"] = str(self.execution_id)

        if self.correlation_id:
            query["metadata.correlation_id"] = self.correlation_id

        if self.aggregate_id:
            query["aggregate_id"] = self.aggregate_id

        if self.event_types:
            query["event_type"] = {"$in": [str(et) for et in self.event_types]}

        if self.exclude_event_types:
            if "event_type" in query:
                query["event_type"]["$nin"] = [str(et) for et in self.exclude_event_types]
            else:
                query["event_type"] = {"$nin": [str(et) for et in self.exclude_event_types]}

        if self.start_time or self.end_time:
            time_query: Dict[str, Any] = {}
            if self.start_time:
                time_query["$gte"] = self.start_time
            if self.end_time:
                time_query["$lte"] = self.end_time
            query["timestamp"] = time_query

        if self.user_id:
            query["metadata.user_id"] = self.user_id

        if self.service_name:
            query["metadata.service_name"] = self.service_name

        if self.custom_query:
            query.update(self.custom_query)

        return query


class ReplayConfig(BaseModel):
    replay_type: ReplayType
    target: ReplayTarget = ReplayTarget.KAFKA
    filter: ReplayFilter = Field(default_factory=ReplayFilter)

    speed_multiplier: float = Field(default=1.0, ge=0.1, le=100.0)
    preserve_timestamps: bool = False
    batch_size: int = Field(default=100, ge=1, le=1000)
    max_events: int | None = Field(default=None, ge=1)

    target_topics: Dict[EventType, str] | None = None
    target_file_path: str | None = None

    skip_errors: bool = True
    retry_failed: bool = False
    retry_attempts: int = 3

    enable_progress_tracking: bool = True
    # Use PrivateAttr to avoid including callables in schema and serialization
    _progress_callback: Any = PrivateAttr(default=None)

    def set_progress_callback(self, cb: Any) -> None:
        self._progress_callback = cb

    def get_progress_callback(self) -> Any:
        return self._progress_callback


class ReplaySessionState(BaseModel):
    """Domain replay session model used by services and repository."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    config: ReplayConfig
    status: ReplayStatus = ReplayStatus.CREATED

    total_events: int = 0
    replayed_events: int = 0
    failed_events: int = 0
    skipped_events: int = 0

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_event_at: datetime | None = None

    errors: list[ReplayError] = Field(default_factory=list)

    # Tracking and admin fields
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    created_by: str | None = None
    target_service: str | None = None
    dry_run: bool = False
    triggered_executions: list[str] = Field(default_factory=list)
    error: str | None = None


class ReplayOperationResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    status: ReplayStatus
    message: str


class CleanupResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    removed_sessions: int
    message: str
