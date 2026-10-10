from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from app.core.metrics import SecurityMetrics
from app.core.security import SecurityService
from app.db import UserRepository
from app.domain.exceptions import AccountLockedError
from app.events import UnifiedProducer
from app.services.auth_service import AuthService
from app.services.login_lockout import LoginLockoutService
from app.services.runtime_settings import RuntimeSettingsLoader
from app.settings import Settings

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_login_on_locked_account_counts_a_blocked_attempt(test_settings: Settings) -> None:
    metrics = MagicMock(spec=SecurityMetrics)
    lockout = AsyncMock(spec=LoginLockoutService)
    lockout.check_locked.return_value = True
    user_repo = AsyncMock(spec=UserRepository)
    service = AuthService(
        user_repo=user_repo,
        security_service=MagicMock(spec=SecurityService),
        security_metrics=metrics,
        logger=structlog.get_logger("test.auth_service_metrics"),
        lockout_service=lockout,
        runtime_settings=AsyncMock(spec=RuntimeSettingsLoader),
        producer=AsyncMock(spec=UnifiedProducer),
        settings=test_settings,
    )

    with pytest.raises(AccountLockedError):
        await service.login("alice", "secret", ip_address="10.0.0.1", user_agent=None)

    metrics.record_brute_force_attempt.assert_called_once_with()
    metrics.track_authentication.assert_not_called()
    user_repo.get_user.assert_not_awaited()
