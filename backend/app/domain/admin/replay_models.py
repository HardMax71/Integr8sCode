"""Domain models for event replay functionality.

This module provides strongly-typed models for replay sessions and related operations.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Optional

from app.domain.admin.event_models import EventSummary, ReplaySessionStatus


class ReplaySessionFields(StrEnum):
    """Database field names for replay sessions."""
    SESSION_ID = "session_id"
    TYPE = "type"
    STATUS = "status"
    TOTAL_EVENTS = "total_events"
    REPLAYED_EVENTS = "replayed_events"
    FAILED_EVENTS = "failed_events"
    SKIPPED_EVENTS = "skipped_events"
    CORRELATION_ID = "correlation_id"
    CREATED_AT = "created_at"
    STARTED_AT = "started_at"
    COMPLETED_AT = "completed_at"
    ERROR = "error"
    CREATED_BY = "created_by"
    TARGET_SERVICE = "target_service"
    DRY_RUN = "dry_run"


@dataclass
class ReplaySession:
    """Replay session domain model."""
    session_id: str
    status: ReplaySessionStatus
    total_events: int
    correlation_id: str
    created_at: datetime
    type: str = "replay_session"
    replayed_events: int = 0
    failed_events: int = 0
    skipped_events: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    created_by: Optional[str] = None
    target_service: Optional[str] = None
    dry_run: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB."""
        doc: Dict[str, Any] = {
            ReplaySessionFields.SESSION_ID.value: self.session_id,
            ReplaySessionFields.TYPE.value: self.type,
            ReplaySessionFields.STATUS.value: self.status.value,
            ReplaySessionFields.TOTAL_EVENTS.value: self.total_events,
            ReplaySessionFields.REPLAYED_EVENTS.value: self.replayed_events,
            ReplaySessionFields.FAILED_EVENTS.value: self.failed_events,
            ReplaySessionFields.SKIPPED_EVENTS.value: self.skipped_events,
            ReplaySessionFields.CORRELATION_ID.value: self.correlation_id,
            ReplaySessionFields.CREATED_AT.value: self.created_at,
            ReplaySessionFields.DRY_RUN.value: self.dry_run
        }

        # Add optional fields
        if self.started_at:
            doc[ReplaySessionFields.STARTED_AT.value] = self.started_at
        if self.completed_at:
            doc[ReplaySessionFields.COMPLETED_AT.value] = self.completed_at
        if self.error:
            doc[ReplaySessionFields.ERROR.value] = self.error
        if self.created_by:
            doc[ReplaySessionFields.CREATED_BY.value] = self.created_by
        if self.target_service:
            doc[ReplaySessionFields.TARGET_SERVICE.value] = self.target_service

        return doc

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplaySession":
        """Create from MongoDB document."""
        return cls(
            session_id=data.get(ReplaySessionFields.SESSION_ID.value, ""),
            type=data.get(ReplaySessionFields.TYPE.value, "replay_session"),
            status=ReplaySessionStatus(data.get(ReplaySessionFields.STATUS.value, ReplaySessionStatus.SCHEDULED)),
            total_events=data.get(ReplaySessionFields.TOTAL_EVENTS.value, 0),
            replayed_events=data.get(ReplaySessionFields.REPLAYED_EVENTS.value, 0),
            failed_events=data.get(ReplaySessionFields.FAILED_EVENTS.value, 0),
            skipped_events=data.get(ReplaySessionFields.SKIPPED_EVENTS.value, 0),
            correlation_id=data.get(ReplaySessionFields.CORRELATION_ID.value, ""),
            created_at=data.get(ReplaySessionFields.CREATED_AT.value, datetime.now()),
            started_at=data.get(ReplaySessionFields.STARTED_AT.value),
            completed_at=data.get(ReplaySessionFields.COMPLETED_AT.value),
            error=data.get(ReplaySessionFields.ERROR.value),
            created_by=data.get(ReplaySessionFields.CREATED_BY.value),
            target_service=data.get(ReplaySessionFields.TARGET_SERVICE.value),
            dry_run=data.get(ReplaySessionFields.DRY_RUN.value, False)
        )

    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage."""
        if self.total_events == 0:
            return 0.0
        return round((self.replayed_events / self.total_events) * 100, 2)

    @property
    def is_completed(self) -> bool:
        """Check if session is completed."""
        return self.status in [ReplaySessionStatus.COMPLETED, ReplaySessionStatus.FAILED, ReplaySessionStatus.CANCELLED]

    @property
    def is_running(self) -> bool:
        """Check if session is running."""
        return self.status == ReplaySessionStatus.RUNNING

    def update_progress(self, replayed: int, failed: int = 0, skipped: int = 0) -> None:
        """Update progress counters."""
        self.replayed_events = replayed
        self.failed_events = failed
        self.skipped_events = skipped

        # Check if completed
        if self.replayed_events >= self.total_events:
            self.status = ReplaySessionStatus.COMPLETED
            self.completed_at = datetime.now()


@dataclass
class ReplaySessionStatusDetail:
    """Extended replay session status with progress."""
    session: ReplaySession
    estimated_completion: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        result = {
            "session_id": self.session.session_id,
            "status": self.session.status.value,
            "total_events": self.session.total_events,
            "replayed_events": self.session.replayed_events,
            "failed_events": self.session.failed_events,
            "skipped_events": self.session.skipped_events,
            "correlation_id": self.session.correlation_id,
            "created_at": self.session.created_at,
            "started_at": self.session.started_at,
            "completed_at": self.session.completed_at,
            "error": self.session.error,
            "progress_percentage": self.session.progress_percentage
        }

        if self.estimated_completion:
            result["estimated_completion"] = self.estimated_completion

        return result


@dataclass
class ReplayQuery:
    """Query for replay events."""
    event_ids: Optional[List[str]] = None
    correlation_id: Optional[str] = None
    aggregate_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    def to_mongodb_query(self) -> Dict[str, Any]:
        """Convert to MongoDB query."""
        from app.domain.admin.event_models import EventFields

        query: Dict[str, Any] = {}

        # Handle event_ids
        if self.event_ids:
            or_conditions = [{EventFields.EVENT_ID: eid} for eid in self.event_ids]
            if or_conditions:
                query["$or"] = or_conditions

        # Handle correlation_id
        if self.correlation_id:
            query[EventFields.CORRELATION_ID] = self.correlation_id

        # Handle aggregate_id
        if self.aggregate_id:
            query[EventFields.AGGREGATE_ID] = self.aggregate_id

        # Handle time range
        if self.start_time or self.end_time:
            time_query = {}
            if self.start_time:
                time_query["$gte"] = self.start_time
            if self.end_time:
                time_query["$lte"] = self.end_time
            query[EventFields.TIMESTAMP] = time_query

        return query

    def is_empty(self) -> bool:
        """Check if query has no criteria."""
        return not any([
            self.event_ids,
            self.correlation_id,
            self.aggregate_id,
            self.start_time,
            self.end_time
        ])


@dataclass
class ReplaySessionData:
    """Unified replay session data for both preview and actual replay."""
    total_events: int
    replay_correlation_id: str
    dry_run: bool
    query: Dict[str, Any]
    events_preview: List[EventSummary] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        result = {
            "dry_run": self.dry_run,
            "total_events": self.total_events,
            "replay_correlation_id": self.replay_correlation_id,
            "query": self.query
        }

        # Only include events_preview if it's a dry run
        if self.dry_run and self.events_preview:
            result["events_preview"] = [e.to_dict() for e in self.events_preview]

        return result
