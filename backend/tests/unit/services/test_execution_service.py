from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from app.core.exceptions.handlers import _map_to_status_code
from app.core.metrics import ExecutionMetrics
from app.db import ExecutionRepository
from app.domain.admin import SystemSettings
from app.domain.enums import ExecutionStatus, UserRole
from app.domain.execution import RuntimeNotSupportedError
from app.domain.user import User
from app.events import UnifiedProducer
from app.services.execution_service import ExecutionService
from app.services.idempotency import IdempotencyManager
from app.services.runtime_settings import RuntimeSettingsLoader
from app.settings import Settings

from tests.unit.conftest import make_domain_execution

pytestmark = pytest.mark.unit


def _user(user_id: str) -> User:
    now = datetime.now(timezone.utc)
    return User(
        user_id=user_id,
        username=user_id,
        email=f"{user_id}@example.com",
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
        hashed_password="unused",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def repo() -> AsyncMock:
    return AsyncMock(spec=ExecutionRepository)


@pytest.fixture
def producer() -> AsyncMock:
    return AsyncMock(spec=UnifiedProducer)


@pytest.fixture
def service(repo: AsyncMock, producer: AsyncMock, test_settings: Settings) -> ExecutionService:
    runtime_settings = AsyncMock(spec=RuntimeSettingsLoader)
    runtime_settings.get_effective_settings.return_value = SystemSettings()
    return ExecutionService(
        execution_repo=repo,
        producer=producer,
        settings=test_settings,
        logger=structlog.get_logger("test"),
        execution_metrics=MagicMock(spec=ExecutionMetrics),
        idempotency_manager=AsyncMock(spec=IdempotencyManager),
        runtime_settings=runtime_settings,
    )


@pytest.mark.parametrize(("lang", "lang_version"), [("python", "3.7"), ("go", "1.22"), ("cobol", "1.0")])
async def test_retry_of_an_unoffered_runtime_is_rejected(
    service: ExecutionService, repo: AsyncMock, producer: AsyncMock, lang: str, lang_version: str
) -> None:
    repo.get_execution.return_value = make_domain_execution(
        status=ExecutionStatus.COMPLETED, lang=lang, lang_version=lang_version, user_id="owner"
    )

    with pytest.raises(RuntimeNotSupportedError, match=f"Runtime not supported: {lang} {lang_version}") as exc:
        await service.retry_execution("e1", _user("owner"))

    assert _map_to_status_code(exc.value) == 422
    repo.create_execution.assert_not_awaited()
    producer.produce.assert_not_awaited()
