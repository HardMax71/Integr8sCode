from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.security import SecurityService
from app.db import UserRepository
from app.domain.exceptions import AccountLockedError
from app.domain.user import InvalidCredentialsError
from app.events import UnifiedProducer
from app.services.auth_service import AuthService
from app.services.login_lockout import LoginLockoutService
from app.services.runtime_settings import RuntimeSettingsLoader
from app.settings import Settings

pytestmark = pytest.mark.unit


def _service(test_settings: Settings, tracer: trace.Tracer, lockout: AsyncMock, user_repo: AsyncMock) -> AuthService:
    return AuthService(
        user_repo=user_repo,
        security_service=MagicMock(spec=SecurityService),
        tracer=tracer,
        logger=structlog.get_logger("test.auth_service_metrics"),
        lockout_service=lockout,
        runtime_settings=AsyncMock(spec=RuntimeSettingsLoader),
        producer=AsyncMock(spec=UnifiedProducer),
        settings=test_settings,
    )


async def test_login_on_locked_account_counts_a_blocked_attempt(
    test_settings: Settings, tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    lockout = AsyncMock(spec=LoginLockoutService)
    lockout.check_locked.return_value = True
    user_repo = AsyncMock(spec=UserRepository)
    service = _service(test_settings, tracer, lockout, user_repo)

    with pytest.raises(AccountLockedError):
        await service.login("alice", "secret", ip_address="10.0.0.1", user_agent=None)

    assert [span.name for span in span_exporter.get_finished_spans()] == ["auth.locked_login"]
    user_repo.get_user.assert_not_awaited()


async def test_failed_login_reports_an_unsuccessful_attempt(
    test_settings: Settings, tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    lockout = AsyncMock(spec=LoginLockoutService)
    lockout.check_locked.return_value = False
    lockout.record_failed_attempt.return_value = False
    user_repo = AsyncMock(spec=UserRepository)
    user_repo.get_user.return_value = None
    service = _service(test_settings, tracer, lockout, user_repo)

    with pytest.raises(InvalidCredentialsError):
        await service.login("alice", "secret", ip_address="10.0.0.1", user_agent=None)

    [span] = span_exporter.get_finished_spans()
    assert (span.name, span.attributes) == ("auth.login", {"auth.method": "login", "auth.success": False})
