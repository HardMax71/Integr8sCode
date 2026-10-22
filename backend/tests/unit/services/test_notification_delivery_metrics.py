from typing import Any
from unittest.mock import AsyncMock

import pytest
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from tenacity import wait_none

from app.db import NotificationRepository
from app.db.docs import NotificationDocument
from app.events import UnifiedProducer
from app.services.notification_service import NotificationService
from app.services.sse import SSERedisBus
from app.services.user_settings_service import UserSettingsService
from app.settings import Settings

pytestmark = pytest.mark.unit


def _service(test_settings: Settings, tracer: trace.Tracer, bus: SSERedisBus) -> NotificationService:
    repo = AsyncMock(spec=NotificationRepository)
    repo.try_claim_pending.return_value = True
    return NotificationService(
        notification_repository=repo,
        producer=AsyncMock(spec=UnifiedProducer),
        sse_bus=bus,
        user_settings=AsyncMock(spec=UserSettingsService),
        settings=test_settings,
        logger=structlog.get_logger("test.notification_delivery_metrics"),
        tracer=tracer,
        retry_wait=wait_none(),
    )


def _spans(exporter: InMemorySpanExporter) -> list[tuple[str, dict[str, Any]]]:
    return [(span.name, dict(span.attributes or {})) for span in exporter.get_finished_spans()]


async def test_retried_delivery_counts_the_retry(
    test_settings: Settings, tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    bus = AsyncMock(spec=SSERedisBus)
    bus.publish_notification.side_effect = [ConnectionError("redis down"), None]
    svc = _service(test_settings, tracer, bus)

    delivered = await svc._deliver_notification(
        NotificationDocument(
            user_id="u1",
            subject="s",
            body="b",
            tags=["execution"],
            max_retries=2,
        )
    )

    assert delivered is True
    (retry_name, retry), (deliver_name, deliver) = _spans(span_exporter)
    assert (retry_name, retry) == (
        "notification.retry",
        {"notification.category": "execution"},
    )
    assert deliver_name == "notification.deliver"
    assert deliver.pop("notification.delivery_seconds") >= 0
    assert deliver == {
        "notification.category": "execution",
        "notification.severity": "medium",
        "notification.result": "delivered",
    }


async def test_failed_delivery_labels_the_error_by_type(
    test_settings: Settings, tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    bus = AsyncMock(spec=SSERedisBus)
    bus.publish_notification.side_effect = ConnectionError("redis down at 10.0.0.1:6379")
    svc = _service(test_settings, tracer, bus)

    delivered = await svc._deliver_notification(
        NotificationDocument(
            user_id="u1",
            subject="s",
            body="b",
            tags=["execution"],
            max_retries=1,
        )
    )

    assert delivered is False
    [(name, attributes)] = _spans(span_exporter)
    assert name == "notification.deliver"
    assert (attributes["notification.result"], attributes["notification.error"]) == ("failed", "ConnectionError")
