from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict

from app.domain.events.typed import DomainEvent
from app.schemas_pydantic.events import EventStatistics
from app.schemas_pydantic.user import UserResponse


class DerivedCounts(BaseModel):
    succeeded: int = 0
    failed: int = 0
    timeout: int = 0
    cancelled: int = 0
    terminal_total: int = 0

    model_config = ConfigDict(from_attributes=True)


class RateLimitSummary(BaseModel):
    bypass_rate_limit: bool | None = None
    global_multiplier: float | None = None
    has_custom_limits: bool | None = None

    model_config = ConfigDict(from_attributes=True)


class AdminUserOverview(BaseModel):
    user: UserResponse
    stats: EventStatistics
    derived_counts: DerivedCounts
    rate_limit_summary: RateLimitSummary
    recent_events: List[DomainEvent] = []

    model_config = ConfigDict(from_attributes=True)
