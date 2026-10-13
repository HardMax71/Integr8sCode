from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from tenacity import wait_none

from app.core.metrics import NotificationMetrics
from app.db import NotificationRepository
from app.domain.enums import NotificationChannel
from app.domain.notification import DomainNotification, DomainNotificationSubscription
from app.events import UnifiedProducer
from app.services.notification_service import NotificationService
from app.services.sse import SSERedisBus
from app.settings import Settings

pytestmark = pytest.mark.unit


def _service(test_settings: Settings, metrics: NotificationMetrics, bus: SSERedisBus) -> NotificationService:
    repo = AsyncMock(spec=NotificationRepository)
    repo.try_claim_pending.return_value = True
    repo.get_subscription.return_value = DomainNotificationSubscription(
        user_id="u1", channel=NotificationChannel.IN_APP
    )
    return NotificationService(
        notification_repository=repo,
        producer=AsyncMock(spec=UnifiedProducer),
        sse_bus=bus,
        settings=test_settings,
        logger=structlog.get_logger("test.notification_delivery_metrics"),
        notification_metrics=metrics,
        retry_wait=wait_none(),
    )


async def test_retried_delivery_counts_the_retry(test_settings: Settings) -> None:
    metrics = MagicMock(spec=NotificationMetrics)
    bus = AsyncMock(spec=SSERedisBus)
    bus.publish_notification.side_effect = [ConnectionError("redis down"), None]
    svc = _service(test_settings, metrics, bus)

    delivered = await svc._deliver_notification(DomainNotification(user_id="u1", tags=["execution"], max_retries=2))

    assert delivered is True
    metrics.record_notification_retry.assert_called_once_with("execution", NotificationChannel.IN_APP)
    metrics.record_notification_sent.assert_called_once()
    metrics.record_notification_failed.assert_not_called()


async def test_failed_delivery_labels_the_error_by_type(test_settings: Settings) -> None:
    metrics = MagicMock(spec=NotificationMetrics)
    bus = AsyncMock(spec=SSERedisBus)
    bus.publish_notification.side_effect = ConnectionError("redis down at 10.0.0.1:6379")
    svc = _service(test_settings, metrics, bus)

    delivered = await svc._deliver_notification(DomainNotification(user_id="u1", tags=["execution"], max_retries=1))

    assert delivered is False
    metrics.record_notification_retry.assert_not_called()
    metrics.record_notification_failed.assert_called_once_with(
        "execution", "ConnectionError", channel=NotificationChannel.IN_APP
    )
