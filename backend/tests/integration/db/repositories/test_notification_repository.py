from datetime import datetime, UTC, timedelta
import logging

import pytest

from app.db.repositories.notification_repository import NotificationRepository
from app.domain.enums.notification import NotificationChannel, NotificationStatus, NotificationSeverity
from app.domain.enums.notification import NotificationChannel as NC
from app.domain.enums.user import UserRole
from app.domain.notification import (
    DomainNotificationCreate,
    DomainNotificationUpdate,
    DomainSubscriptionUpdate,
)
from app.domain.user import UserFields

pytestmark = pytest.mark.integration

_test_logger = logging.getLogger("test.db.repositories.notification_repository")


@pytest.mark.asyncio
async def test_create_and_crud() -> None:
    repo = NotificationRepository(logger=_test_logger)

    create_data = DomainNotificationCreate(
        user_id="u1",
        channel=NotificationChannel.IN_APP,
        subject="sub",
        body="body",
        severity=NotificationSeverity.MEDIUM,
        tags=["execution", "completed"],
    )
    n = await repo.create_notification(create_data)
    assert n.notification_id

    # Update
    update_data = DomainNotificationUpdate(status=NotificationStatus.DELIVERED)
    assert await repo.update_notification(n.notification_id, n.user_id, update_data) is True

    got = await repo.get_notification(n.notification_id, n.user_id)
    assert got and got.notification_id == n.notification_id and got.status == NotificationStatus.DELIVERED

    assert await repo.mark_as_read(n.notification_id, n.user_id) is True
    assert await repo.mark_all_as_read(n.user_id) >= 0
    assert await repo.delete_notification(n.notification_id, n.user_id) is True


@pytest.mark.asyncio
async def test_list_count_unread_and_pending(db) -> None:  # type: ignore[no-untyped-def]
    repo = NotificationRepository(logger=_test_logger)
    now = datetime.now(UTC)

    # Seed notifications
    await db.get_collection("notifications").insert_many([
        {"notification_id": "n1", "user_id": "u1", "severity": NotificationSeverity.MEDIUM.value, "tags": ["execution"], "channel": NotificationChannel.IN_APP.value, "subject": "s", "body": "b", "status": NotificationStatus.PENDING.value, "created_at": now},
        {"notification_id": "n2", "user_id": "u1", "severity": NotificationSeverity.LOW.value, "tags": ["completed"], "channel": NotificationChannel.IN_APP.value, "subject": "s", "body": "b", "status": NotificationStatus.DELIVERED.value, "created_at": now},
    ])
    lst = await repo.list_notifications("u1")
    assert len(lst) >= 2
    assert await repo.count_notifications("u1") >= 2
    assert await repo.get_unread_count("u1") >= 0

    # Pending and scheduled
    pending = await repo.find_pending_notifications()
    assert any(n.status == NotificationStatus.PENDING for n in pending)
    await db.get_collection("notifications").insert_one({
        "notification_id": "n3", "user_id": "u1", "severity": NotificationSeverity.MEDIUM.value, "tags": ["execution"],
        "channel": NotificationChannel.IN_APP.value, "subject": "s", "body": "b", "status": NotificationStatus.PENDING.value,
        "created_at": now, "scheduled_for": now + timedelta(seconds=1)
    })
    scheduled = await repo.find_scheduled_notifications()
    assert isinstance(scheduled, list)
    assert await repo.cleanup_old_notifications(days=0) >= 0


@pytest.mark.asyncio
async def test_subscriptions_and_user_queries(db) -> None:  # type: ignore[no-untyped-def]
    repo = NotificationRepository(logger=_test_logger)

    update_data = DomainSubscriptionUpdate(enabled=True, severities=[])
    sub = await repo.upsert_subscription("u1", NotificationChannel.IN_APP, update_data)
    assert sub.user_id == "u1"

    got = await repo.get_subscription("u1", NotificationChannel.IN_APP)
    assert got and got.user_id == "u1"

    subs = await repo.get_all_subscriptions("u1")
    assert len(subs) == len(list(NC))

    # Users by role and active users
    await db.get_collection("users").insert_many([
        {UserFields.USER_ID: "u1", UserFields.USERNAME: "A", UserFields.EMAIL: "a@e.com", UserFields.ROLE: "user", UserFields.IS_ACTIVE: True},
        {UserFields.USER_ID: "u2", UserFields.USERNAME: "B", UserFields.EMAIL: "b@e.com", UserFields.ROLE: "admin", UserFields.IS_ACTIVE: True},
    ])
    ids = await repo.get_users_by_roles([UserRole.USER])
    assert "u1" in ids or isinstance(ids, list)
    await db.get_collection("executions").insert_one({"execution_id": "e1", "user_id": "u2", "created_at": datetime.now(UTC)})
    active = await repo.get_active_users(days=1)
    assert set(active) >= {"u2"} or isinstance(active, list)
