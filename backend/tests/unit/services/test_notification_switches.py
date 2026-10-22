from unittest.mock import AsyncMock

import pytest
import structlog
from opentelemetry import trace

from app.db import NotificationRepository
from app.db.docs import UserSettingsDocument
from app.domain.enums import ExecutionErrorType
from app.domain.events import (
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    ResourceUsageDomain,
)
from app.domain.user import DomainNotificationSettings
from app.events import UnifiedProducer
from app.services.notification_service import NotificationService
from app.services.sse import SSERedisBus
from app.services.user_settings_service import UserSettingsService
from app.settings import Settings

pytestmark = pytest.mark.unit

_METADATA = EventMetadata(service_name="tests", service_version="1.0.0", user_id="u1")
_COMPLETED = ExecutionCompletedEvent(
    execution_id="e1", exit_code=0, resource_usage=ResourceUsageDomain(), metadata=_METADATA
)
_FAILED = ExecutionFailedEvent(execution_id="e1", error_type=ExecutionErrorType.SCRIPT_ERROR, metadata=_METADATA)
_TIMEOUT = ExecutionTimeoutEvent(
    execution_id="e1", timeout_seconds=5, resource_usage=ResourceUsageDomain(), metadata=_METADATA
)


def _service(
    test_settings: Settings, tracer: trace.Tracer, switches: DomainNotificationSettings
) -> tuple[NotificationService, AsyncMock]:
    """A service for user u1 with these switches, and its repository mock."""
    user_settings = AsyncMock(spec=UserSettingsService)
    user_settings.get_user_settings.return_value = UserSettingsDocument(user_id="u1", notifications=switches)
    repository = AsyncMock(spec=NotificationRepository)
    service = NotificationService(
        notification_repository=repository,
        producer=AsyncMock(spec=UnifiedProducer),
        sse_bus=AsyncMock(spec=SSERedisBus),
        user_settings=user_settings,
        settings=test_settings,
        logger=structlog.get_logger("test.notification_switches"),
        tracer=tracer,
    )
    return service, repository


@pytest.mark.parametrize(
    ("switches", "event", "sent"),
    [
        (DomainNotificationSettings(execution_completed=False), _COMPLETED, False),
        (DomainNotificationSettings(execution_failed=False), _COMPLETED, True),
        (DomainNotificationSettings(execution_failed=False), _FAILED, False),
        (DomainNotificationSettings(execution_failed=False), _TIMEOUT, False),
        (DomainNotificationSettings(execution_completed=False), _FAILED, True),
    ],
)
async def test_an_execution_notifies_only_when_its_switch_is_on(
    test_settings: Settings,
    tracer: trace.Tracer,
    switches: DomainNotificationSettings,
    event: ExecutionCompletedEvent | ExecutionFailedEvent | ExecutionTimeoutEvent,
    sent: bool,
) -> None:
    service, repository = _service(test_settings, tracer, switches)

    match event:
        case ExecutionCompletedEvent():
            await service.handle_execution_completed(event)
        case ExecutionFailedEvent():
            await service.handle_execution_failed(event)
        case ExecutionTimeoutEvent():
            await service.handle_execution_timeout(event)

    assert repository.create_notification.await_count == (1 if sent else 0)
