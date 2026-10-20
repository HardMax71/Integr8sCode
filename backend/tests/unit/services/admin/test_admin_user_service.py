from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from app.db import UserRepository
from app.db.repositories.user_repository import UserListResult
from app.domain.rate_limit import UserRateLimitSummary
from app.services.admin import AdminUserService
from app.services.rate_limit_service import RateLimitService

pytestmark = pytest.mark.unit

# Only users with an override can differ from the defaults
OVERRIDES = [
    UserRateLimitSummary(
        user_id="bypass", has_custom_limits=True, bypass_rate_limit=True, global_multiplier=1.0, rules_count=0
    ),
    UserRateLimitSummary(
        user_id="doubled", has_custom_limits=True, bypass_rate_limit=False, global_multiplier=2.0, rules_count=0
    ),
    UserRateLimitSummary(
        user_id="rules", has_custom_limits=True, bypass_rate_limit=False, global_multiplier=1.0, rules_count=2
    ),
]


@pytest.fixture
def users() -> AsyncMock:
    repo = AsyncMock(spec=UserRepository)
    repo.list_users = AsyncMock(return_value=UserListResult(users=[], total=0, offset=0, limit=10))
    return repo


@pytest.fixture
def rate_limits() -> AsyncMock:
    service = AsyncMock(spec=RateLimitService)
    service.get_override_summaries = AsyncMock(return_value=OVERRIDES)
    service.get_user_rate_limit_summaries = AsyncMock(return_value={})
    return service


@pytest.fixture
def service(users: AsyncMock, rate_limits: AsyncMock) -> AdminUserService:
    return AdminUserService(
        users, MagicMock(), MagicMock(), rate_limits, MagicMock(), MagicMock(), structlog.get_logger("test")
    )


async def list_with(service: AdminUserService, **filters: Any) -> None:
    await service.list_users(admin_user_id="admin", limit=10, offset=0, search=None, role=None, **filters)


async def test_no_rate_limit_filter_skips_the_config(
    service: AdminUserService, users: AsyncMock, rate_limits: AsyncMock
) -> None:
    await list_with(service, is_active=False)

    rate_limits.get_override_summaries.assert_not_awaited()
    users.list_users.assert_awaited_once_with(
        limit=10, offset=0, search=None, role=None, is_active=False, user_ids=None, excluded_user_ids=set()
    )


@pytest.mark.parametrize(
    ("filters", "user_ids", "excluded_user_ids"),
    [
        ({"bypass_rate_limit": True}, {"bypass"}, set()),
        ({"bypass_rate_limit": False}, None, {"bypass"}),
        ({"custom_multiplier": True}, {"doubled"}, set()),
        ({"custom_multiplier": False}, None, {"doubled"}),
        ({"has_custom_limits": True}, {"bypass", "doubled", "rules"}, set()),
        ({"has_custom_limits": False}, None, {"bypass", "doubled", "rules"}),
        ({"has_custom_limits": True, "custom_multiplier": True}, {"doubled"}, set()),
        ({"has_custom_limits": True, "bypass_rate_limit": False}, {"bypass", "doubled", "rules"}, {"bypass"}),
    ],
)
async def test_rate_limit_filters_become_user_ids(
    service: AdminUserService,
    users: AsyncMock,
    filters: dict[str, bool],
    user_ids: set[str] | None,
    excluded_user_ids: set[str],
) -> None:
    await list_with(service, **filters)

    kwargs = users.list_users.await_args.kwargs
    assert kwargs["user_ids"] == user_ids
    assert kwargs["excluded_user_ids"] == excluded_user_ids
