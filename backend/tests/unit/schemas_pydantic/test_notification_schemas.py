from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums.notification import NotificationChannel, NotificationSeverity, NotificationStatus
from app.schemas_pydantic.notification import Notification, NotificationBatch


def test_notification_scheduled_for_must_be_future() -> None:
    n = Notification(
        user_id="u1",
        channel=NotificationChannel.IN_APP,
        severity=NotificationSeverity.MEDIUM,
        status=NotificationStatus.PENDING,
        subject="Hello",
        body="World",
        scheduled_for=datetime.now(UTC) + timedelta(seconds=1),
    )
    assert n.scheduled_for is not None

    with pytest.raises(ValueError):
        Notification(
            user_id="u1",
            channel=NotificationChannel.IN_APP,
            subject="x",
            body="y",
            scheduled_for=datetime.now(UTC) - timedelta(seconds=1),
        )


def test_notification_batch_validation_limits() -> None:
    n1 = Notification(user_id="u1", channel=NotificationChannel.IN_APP, subject="a", body="b")
    ok = NotificationBatch(notifications=[n1])
    assert ok.processed_count == 0

    with pytest.raises(ValueError):
        NotificationBatch(notifications=[])

    many = [n1.model_copy() for _ in range(1001)]
    with pytest.raises(ValueError):
        NotificationBatch(notifications=many)
