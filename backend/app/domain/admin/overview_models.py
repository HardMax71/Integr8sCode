from __future__ import annotations

from dataclasses import field

from pydantic.dataclasses import dataclass

from app.domain.events import DomainEvent
from app.domain.user import User as DomainAdminUser
from app.schemas_pydantic.events import EventStatistics


@dataclass
class DerivedCountsDomain:
    succeeded: int = 0
    failed: int = 0
    timeout: int = 0
    cancelled: int = 0
    terminal_total: int = 0


@dataclass
class RateLimitSummaryDomain:
    bypass_rate_limit: bool | None = None
    global_multiplier: float | None = None
    has_custom_limits: bool | None = None


@dataclass
class AdminUserOverviewDomain:
    user: DomainAdminUser
    stats: EventStatistics
    derived_counts: DerivedCountsDomain
    rate_limit_summary: RateLimitSummaryDomain
    recent_events: list[DomainEvent] = field(default_factory=list)
