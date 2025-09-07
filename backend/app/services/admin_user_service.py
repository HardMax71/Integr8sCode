from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.repositories.admin.admin_user_repository import AdminUserRepository
from app.domain.admin.overview_models import (
    AdminUserOverviewDomain,
    DerivedCountsDomain,
    RateLimitSummaryDomain,
)
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.user import UserRole
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService
from app.services.rate_limit_service import RateLimitService


class AdminUserService:
    def __init__(
            self,
            user_repository: AdminUserRepository,
            event_service: EventService,
            execution_service: ExecutionService,
            rate_limit_service: RateLimitService,
    ) -> None:
        self._users = user_repository
        self._events = event_service
        self._executions = execution_service
        self._rate_limits = rate_limit_service
        # Service operates purely on domain types

    async def get_user_overview(self, user_id: str, hours: int = 24) -> AdminUserOverviewDomain:
        user = await self._users.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=hours)
        stats_domain = await self._events.get_event_statistics(
            user_id=user_id,
            user_role=UserRole.ADMIN,
            start_time=start,
            end_time=now,
            include_all_users=False,
        )
        exec_stats = await self._executions.get_execution_stats(
            user_id=user_id,
            time_range=(start, now)
        )
        by_status = exec_stats.get("by_status", {}) or {}

        def _count(status: ExecutionStatus) -> int:
            return int(by_status.get(status, 0) or by_status.get(status.value, 0) or 0)

        succeeded = _count(ExecutionStatus.COMPLETED)
        failed = _count(ExecutionStatus.FAILED)
        timeout = _count(ExecutionStatus.TIMEOUT)
        cancelled = _count(ExecutionStatus.CANCELLED)
        derived = DerivedCountsDomain(
            succeeded=succeeded,
            failed=failed,
            timeout=timeout,
            cancelled=cancelled,
            terminal_total=succeeded + failed + timeout + cancelled,
        )

        # Rate limit summary (must reflect current state; let errors bubble)
        rl = await self._rate_limits.get_user_rate_limit(user_id)
        rl_summary = RateLimitSummaryDomain(
            bypass_rate_limit=rl.bypass_rate_limit if rl else False,
            global_multiplier=rl.global_multiplier if rl else 1.0,
            has_custom_limits=bool(rl.rules) if rl else False,
        )

        # Recent execution-related events (last 10)
        event_types = [
            EventType.EXECUTION_REQUESTED,
            EventType.EXECUTION_STARTED,
            EventType.EXECUTION_COMPLETED,
            EventType.EXECUTION_FAILED,
            EventType.EXECUTION_TIMEOUT,
            EventType.EXECUTION_CANCELLED,
        ]
        recent_result = await self._events.get_user_events_paginated(
            user_id=user_id,
            event_types=[str(et) for et in event_types],
            start_time=start,
            end_time=now,
            limit=10,
            skip=0,
            sort_order="desc",
        )
        recent_events = recent_result.events

        return AdminUserOverviewDomain(
            user=user,
            stats=stats_domain,
            derived_counts=derived,
            rate_limit_summary=rl_summary,
            recent_events=recent_events,
        )
