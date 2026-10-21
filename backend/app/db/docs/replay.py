import dataclasses
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import ConfigDict, Field
from pymongo import IndexModel

from app.domain.enums import ReplayStatus
from app.domain.replay import ReplayConfig, ReplayError, ReplayFilter


class ReplaySessionDocument(Document):
    """A replay session: the API stores it as scheduled, and the worker runs it and records its progress."""

    session_id: Annotated[str, Indexed(unique=True)] = Field(default_factory=lambda: str(uuid4()))
    config: ReplayConfig
    status: ReplayStatus = ReplayStatus.SCHEDULED  # Indexed via Settings.indexes

    total_events: int = 0
    replayed_events: int = 0
    failed_events: int = 0
    skipped_events: int = 0

    created_at: Annotated[datetime, Indexed()] = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    errors: list[ReplayError] = Field(default_factory=list)

    replay_id: str = Field(default_factory=lambda: str(uuid4()))

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "replay_sessions"
        use_state_management = True
        bson_encoders = {
            ReplayConfig: dataclasses.asdict,
            ReplayFilter: dataclasses.asdict,
            ReplayError: dataclasses.asdict,
        }
        indexes = [
            IndexModel([("status", 1)]),
            IndexModel([("replay_id", 1)]),
            IndexModel([("completed_at", 1)], expireAfterSeconds=48 * 3600),
        ]
