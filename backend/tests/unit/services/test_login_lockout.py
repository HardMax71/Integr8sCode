import structlog
from unittest.mock import AsyncMock

import pytest
from app.domain.admin import SystemSettings
from app.services.login_lockout import LoginLockoutService

pytestmark = pytest.mark.unit

_logger = structlog.get_logger("test.services.login_lockout")


def _make_service(
    *,
    max_login_attempts: int = 5,
    lockout_duration_minutes: int = 15,
) -> tuple[LoginLockoutService, AsyncMock]:
    redis_mock = AsyncMock()
    redis_mock.exists.return_value = 0
    redis_mock.incr.return_value = 1

    runtime = AsyncMock()
    runtime.get_effective_settings.return_value = SystemSettings(
        max_login_attempts=max_login_attempts,
        lockout_duration_minutes=lockout_duration_minutes,
    )
    service = LoginLockoutService(redis_client=redis_mock, runtime_settings=runtime, logger=_logger)
    return service, redis_mock


@pytest.mark.asyncio
async def test_check_locked_returns_false_when_not_locked() -> None:
    service, redis_mock = _make_service()
    redis_mock.exists.return_value = 0

    assert await service.check_locked("alice") is False
    redis_mock.exists.assert_called_once_with("login_lockout:locked:alice")


@pytest.mark.asyncio
async def test_check_locked_returns_true_when_locked() -> None:
    service, redis_mock = _make_service()
    redis_mock.exists.return_value = 1

    assert await service.check_locked("alice") is True


@pytest.mark.asyncio
async def test_record_first_attempt_sets_ttl() -> None:
    service, redis_mock = _make_service(lockout_duration_minutes=10)
    redis_mock.incr.return_value = 1

    locked = await service.record_failed_attempt("alice")

    assert locked is False
    redis_mock.incr.assert_called_once_with("login_lockout:attempts:alice")
    redis_mock.expire.assert_called_once_with("login_lockout:attempts:alice", 600)


@pytest.mark.asyncio
async def test_subsequent_attempt_refreshes_ttl() -> None:
    service, redis_mock = _make_service(lockout_duration_minutes=15)
    redis_mock.incr.return_value = 3

    await service.record_failed_attempt("alice")

    redis_mock.expire.assert_called_once_with("login_lockout:attempts:alice", 900)


@pytest.mark.asyncio
async def test_locks_account_at_max_attempts() -> None:
    service, redis_mock = _make_service(max_login_attempts=3, lockout_duration_minutes=10)
    redis_mock.incr.return_value = 3

    locked = await service.record_failed_attempt("alice")

    assert locked is True
    redis_mock.set.assert_called_once_with("login_lockout:locked:alice", "1", ex=600)


@pytest.mark.asyncio
async def test_locks_account_when_exceeding_max_attempts() -> None:
    service, redis_mock = _make_service(max_login_attempts=3)
    redis_mock.incr.return_value = 5

    locked = await service.record_failed_attempt("alice")

    assert locked is True


@pytest.mark.asyncio
async def test_does_not_lock_below_max_attempts() -> None:
    service, redis_mock = _make_service(max_login_attempts=5)
    redis_mock.incr.return_value = 4

    locked = await service.record_failed_attempt("alice")

    assert locked is False
    redis_mock.set.assert_not_called()


@pytest.mark.asyncio
async def test_clear_attempts_deletes_both_keys() -> None:
    service, redis_mock = _make_service()

    await service.clear_attempts("alice")

    redis_mock.delete.assert_called_once_with(
        "login_lockout:attempts:alice",
        "login_lockout:locked:alice",
    )


@pytest.mark.asyncio
async def test_unlock_user_delegates_to_clear_attempts() -> None:
    service, redis_mock = _make_service()

    await service.unlock_user("alice")

    redis_mock.delete.assert_called_once_with(
        "login_lockout:attempts:alice",
        "login_lockout:locked:alice",
    )


@pytest.mark.asyncio
async def test_lockout_ttl_derived_from_runtime_settings() -> None:
    service, redis_mock = _make_service(lockout_duration_minutes=30, max_login_attempts=3)
    redis_mock.incr.return_value = 3

    await service.record_failed_attempt("bob")

    redis_mock.set.assert_called_once_with("login_lockout:locked:bob", "1", ex=1800)
