from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay.models import ReplayConfig as DomainReplayConfig
from app.domain.replay.models import ReplayFilter as DomainReplayFilter


class ReplayFilterSchema(BaseModel):
    execution_id: str | None = None
    event_types: List[str] | None = None
    start_time: float | None = None
    end_time: float | None = None
    user_id: str | None = None
    service_name: str | None = None
    custom_query: Dict[str, Any] | None = None
    exclude_event_types: List[str] | None = None

    @classmethod
    def from_domain(cls, f: DomainReplayFilter) -> "ReplayFilterSchema":
        return cls(
            execution_id=f.execution_id,
            event_types=[str(et) for et in (f.event_types or [])] or None,
            start_time=f.start_time,
            end_time=f.end_time,
            user_id=f.user_id,
            service_name=f.service_name,
            custom_query=f.custom_query,
            exclude_event_types=[str(et) for et in (f.exclude_event_types or [])] or None,
        )


class ReplayConfigSchema(BaseModel):
    replay_type: ReplayType
    target: ReplayTarget = ReplayTarget.KAFKA
    filter: ReplayFilterSchema

    speed_multiplier: float = Field(default=1.0, ge=0.1, le=100.0)
    preserve_timestamps: bool = False
    batch_size: int = Field(default=100, ge=1, le=1000)
    max_events: int | None = Field(default=None, ge=1)

    # Use string keys for event types for clean JSON
    target_topics: Dict[str, str] | None = None
    target_file_path: str | None = None

    skip_errors: bool = True
    retry_failed: bool = False
    retry_attempts: int = 3

    enable_progress_tracking: bool = True

    @field_validator("filter", mode="before")
    @classmethod
    def _coerce_filter(cls, v: Any) -> Any:  # noqa: ANN001
        if isinstance(v, DomainReplayFilter):
            return ReplayFilterSchema.from_domain(v).model_dump()
        return v

    @model_validator(mode="before")
    @classmethod
    def _from_domain(cls, data: Any) -> Any:  # noqa: ANN001
        if isinstance(data, DomainReplayConfig):
            # Convert DomainReplayConfig to dict compatible with this schema
            d = data.model_dump()
            # Convert filter
            filt = data.filter
            d["filter"] = ReplayFilterSchema.from_domain(filt).model_dump()
            # Convert target_topics keys to strings if present
            if d.get("target_topics"):
                d["target_topics"] = {str(k): v for k, v in d["target_topics"].items()}
            return d
        return data


class ReplaySession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    config: ReplayConfigSchema
    status: ReplayStatus = ReplayStatus.CREATED

    total_events: int = 0
    replayed_events: int = 0
    failed_events: int = 0
    skipped_events: int = 0

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_event_at: datetime | None = None

    errors: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("config", mode="before")
    @classmethod
    def _coerce_config(cls, v: Any) -> Any:  # noqa: ANN001
        if isinstance(v, DomainReplayConfig):
            return ReplayConfigSchema.model_validate(v).model_dump()
        if isinstance(v, dict):
            return v
        return v
