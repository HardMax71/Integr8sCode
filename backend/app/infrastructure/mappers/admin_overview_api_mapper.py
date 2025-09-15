from __future__ import annotations

from typing import Any, Dict, List

from app.domain.admin import AdminUserOverviewDomain
from app.schemas_pydantic.admin_user_overview import (
    AdminUserOverview,
    DerivedCounts,
    RateLimitSummary,
)
from app.schemas_pydantic.events import EventStatistics as EventStatisticsSchema
from app.schemas_pydantic.user import UserResponse

from .admin_mapper import UserMapper
from .event_mapper import EventMapper, EventStatisticsMapper


class AdminOverviewApiMapper:
    def __init__(self) -> None:
        self._user_mapper = UserMapper()
        self._event_mapper = EventMapper()
        self._stats_mapper = EventStatisticsMapper()

    def to_response(self, d: AdminUserOverviewDomain) -> AdminUserOverview:
        user_resp = UserResponse(**self._user_mapper.to_response_dict(d.user))
        stats_dict = self._stats_mapper.to_dict(d.stats)
        stats_schema = EventStatisticsSchema(**stats_dict)
        derived = DerivedCounts(
            succeeded=d.derived_counts.succeeded,
            failed=d.derived_counts.failed,
            timeout=d.derived_counts.timeout,
            cancelled=d.derived_counts.cancelled,
            terminal_total=d.derived_counts.terminal_total,
        )
        rl = RateLimitSummary(
            bypass_rate_limit=d.rate_limit_summary.bypass_rate_limit,
            global_multiplier=d.rate_limit_summary.global_multiplier,
            has_custom_limits=d.rate_limit_summary.has_custom_limits,
        )
        recent_events: List[Dict[str, Any]] = [self._event_mapper.to_dict(e) for e in d.recent_events]
        return AdminUserOverview(
            user=user_resp,
            stats=stats_schema,
            derived_counts=derived,
            rate_limit_summary=rl,
            recent_events=recent_events,
        )
