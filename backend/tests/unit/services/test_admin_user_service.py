import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.user import UserRole
from app.schemas_pydantic.user import UserResponse
from app.services.admin_user_service import AdminUserService


class FakeUserRepo:
    def __init__(self, user=None):  # noqa: ANN001
        self._user = user
    async def get_user_by_id(self, user_id):  # noqa: ANN001
        return self._user


class FakeEventService:
    async def get_event_statistics(self, **kwargs):  # noqa: ANN001
        from app.domain.events.event_models import EventStatistics
        # Return a proper EventStatistics instance for the mapper
        return EventStatistics(
            total_events=5,
            events_by_type={"execution.requested": 2},
            events_by_service={"svc": 5},
            events_by_hour=[],
            top_users=[],
            error_rate=0.0,
            avg_processing_time=0.0,
        )
    async def get_user_events_paginated(self, **kwargs):  # noqa: ANN001
        class R:
            def __init__(self):
                self.events = []
        return R()


class FakeExecutionService:
    def __init__(self, by_status):  # noqa: ANN001
        self._bs = by_status
    async def get_execution_stats(self, **kwargs):  # noqa: ANN001
        return {"by_status": self._bs}


class RL:
    def __init__(self, bypass, mult, rules):  # noqa: ANN001
        self.bypass_rate_limit = bypass
        self.global_multiplier = mult
        self.rules = rules


class FakeRateLimitService:
    def __init__(self, rl):  # noqa: ANN001
        self._rl = rl
    async def get_user_rate_limit(self, user_id):  # noqa: ANN001
        return self._rl


def make_user():
    # Minimal fields for UserResponse mapping
    return SimpleNamespace(
        user_id="u1", username="bob", email="b@b.com", role=UserRole.USER, is_active=True, is_superuser=False,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
    )


@pytest.mark.asyncio
async def test_get_user_overview_success():
    user = make_user()
    svc = AdminUserService(
        user_repository=FakeUserRepo(user),
        event_service=FakeEventService(),
        execution_service=FakeExecutionService(by_status={
            ExecutionStatus.COMPLETED.value: 3,
            ExecutionStatus.FAILED.value: 1,
            ExecutionStatus.TIMEOUT.value: 1,
            ExecutionStatus.CANCELLED.value: 0,
        }),
        rate_limit_service=FakeRateLimitService(RL(True, 2.0, {"r": 1}))
    )

    overview = await svc.get_user_overview("u1", hours=1)
    assert overview.user.username == user.username
    assert overview.derived_counts.succeeded == 3
    assert overview.rate_limit_summary.bypass_rate_limit is True
    assert overview.rate_limit_summary.global_multiplier == 2.0
    assert overview.rate_limit_summary.has_custom_limits is True


@pytest.mark.asyncio
async def test_get_user_overview_user_not_found():
    svc = AdminUserService(
        user_repository=FakeUserRepo(None),
        event_service=FakeEventService(),
        execution_service=FakeExecutionService(by_status={}),
        rate_limit_service=FakeRateLimitService(None)
    )
    with pytest.raises(ValueError):
        await svc.get_user_overview("missing")
