from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums.notification import NotificationChannel, NotificationSeverity, NotificationStatus
from app.schemas_pydantic.notification import (
    Notification,
    NotificationBatch,
    NotificationListResponse,
    NotificationResponse,
    NotificationStats,
    NotificationSubscription,
    SubscriptionUpdate,
)


def test_notification_scheduled_for_future_validation():
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


def test_notification_batch_validation_limits():
    n1 = Notification(user_id="u1", channel=NotificationChannel.IN_APP, subject="a", body="b")
    ok = NotificationBatch(notifications=[n1])
    assert ok.processed_count == 0

    with pytest.raises(ValueError):
        NotificationBatch(notifications=[])

    # Upper bound: >1000 should fail
    many = [n1.copy() for _ in range(1001)]
    with pytest.raises(ValueError):
        NotificationBatch(notifications=many)


def test_notification_response_and_list():
    n = Notification(user_id="u1", channel=NotificationChannel.IN_APP, subject="s", body="b")
    resp = NotificationResponse(
        notification_id=n.notification_id,
        channel=n.channel,
        status=n.status,
        subject=n.subject,
        body=n.body,
        action_url=None,
        created_at=n.created_at,
        read_at=None,
        severity=n.severity,
        tags=[],
    )
    lst = NotificationListResponse(notifications=[resp], total=1, unread_count=1)
    assert lst.unread_count == 1


def test_subscription_models_and_stats():
    sub = NotificationSubscription(user_id="u1", channel=NotificationChannel.IN_APP)
    upd = SubscriptionUpdate(enabled=True)
    assert sub.enabled is True and upd.enabled is True

    now = datetime.now(UTC)
    stats = NotificationStats(start_date=now - timedelta(days=1), end_date=now)
    assert stats.total_sent == 0 and stats.delivery_rate == 0.0
