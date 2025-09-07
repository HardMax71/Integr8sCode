import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, UTC, timedelta

from motor.motor_asyncio import AsyncIOMotorCollection

from app.db.repositories.notification_repository import NotificationRepository
from app.domain.enums.notification import NotificationChannel, NotificationStatus, NotificationType
from app.domain.enums.user import UserRole
from app.domain.notification.models import (
    DomainNotification,
    DomainNotificationRule,
    DomainNotificationSubscription,
    DomainNotificationTemplate,
)
from app.domain.admin.user_models import UserFields


pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(mock_db) -> NotificationRepository:
    return NotificationRepository(mock_db)


@pytest.mark.asyncio
async def test_create_indexes_creates_when_absent(repo: NotificationRepository, mock_db: AsyncMock) -> None:
    # Simulate only _id index existing
    for coll in (mock_db.notifications, mock_db.notification_rules, mock_db.notification_subscriptions):
        coll.list_indexes.return_value = AsyncMock()
        coll.list_indexes.return_value.to_list = AsyncMock(return_value=[{"name": "_id_"}])
        coll.create_indexes = AsyncMock()

    await repo.create_indexes()

    assert mock_db.notifications.create_indexes.await_count == 1
    assert mock_db.notification_rules.create_indexes.await_count == 1
    assert mock_db.notification_subscriptions.create_indexes.await_count == 1


@pytest.mark.asyncio
async def test_template_upsert_get(repo: NotificationRepository, mock_db: AsyncMock) -> None:
    t = DomainNotificationTemplate(
        notification_type=NotificationType.EXECUTION_COMPLETED,
        channels=[NotificationChannel.IN_APP],
        subject_template="s",
        body_template="b",
    )
    mock_db.notification_templates.update_one = AsyncMock()
    await repo.upsert_template(t)
    mock_db.notification_templates.update_one.assert_called_once()

    mock_db.notification_templates.find_one = AsyncMock(return_value={
        "notification_type": t.notification_type,
        "channels": t.channels,
        "subject_template": t.subject_template,
        "body_template": t.body_template,
        "priority": t.priority,
    })
    got = await repo.get_template(NotificationType.EXECUTION_COMPLETED)
    assert got and got.notification_type == t.notification_type

    # bulk upsert
    mock_db.notification_templates.update_one = AsyncMock()
    await repo.bulk_upsert_templates([t])
    mock_db.notification_templates.update_one.assert_awaited()


@pytest.mark.asyncio
async def test_create_update_get_delete_notification(repo: NotificationRepository, mock_db: AsyncMock) -> None:
    n = DomainNotification(
        user_id="u1",
        notification_type=NotificationType.EXECUTION_COMPLETED,
        channel=NotificationChannel.IN_APP,
        subject="sub",
        body="body",
    )
    mock_db.notifications.insert_one = AsyncMock(return_value=MagicMock(inserted_id="oid"))
    _id = await repo.create_notification(n)
    assert _id == "oid"

    mock_db.notifications.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    assert await repo.update_notification(n) is True

    mock_db.notifications.find_one = AsyncMock(return_value={
        "notification_id": n.notification_id,
        "user_id": n.user_id,
        "notification_type": n.notification_type,
        "channel": n.channel,
        "subject": n.subject,
        "body": n.body,
        "status": n.status,
    })
    got = await repo.get_notification(n.notification_id, n.user_id)
    assert got and got.notification_id == n.notification_id

    mock_db.notifications.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    assert await repo.mark_as_read(n.notification_id, n.user_id) is True

    mock_db.notifications.update_many = AsyncMock(return_value=MagicMock(modified_count=2))
    assert await repo.mark_all_as_read(n.user_id) == 2

    mock_db.notifications.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    assert await repo.delete_notification(n.notification_id, n.user_id) is True


@pytest.mark.asyncio
async def test_list_and_count_and_unread(repo: NotificationRepository, mock_db: AsyncMock) -> None:
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *_a, **_k):
            return self
        def skip(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    n = DomainNotification(
        user_id="u1",
        notification_type=NotificationType.EXECUTION_COMPLETED,
        channel=NotificationChannel.IN_APP,
        subject="s",
        body="b",
    )
    mock_db.notifications.find.return_value = Cursor([
        {
            "notification_id": n.notification_id,
            "user_id": n.user_id,
            "notification_type": n.notification_type,
            "channel": n.channel,
            "subject": n.subject,
            "body": n.body,
            "status": n.status,
        }
    ])
    lst = await repo.list_notifications("u1")
    assert len(lst) == 1 and lst[0].user_id == "u1"

    mock_db.notifications.count_documents = AsyncMock(return_value=3)
    assert await repo.count_notifications("u1") == 3

    mock_db.notifications.count_documents = AsyncMock(return_value=2)
    assert await repo.get_unread_count("u1") == 2


@pytest.mark.asyncio
async def test_find_pending_and_scheduled(repo: NotificationRepository, mock_db: AsyncMock) -> None:
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def limit(self, *_a, **_k):
            return self
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    now = datetime.now(UTC)
    base = {
        "notification_id": "n1",
        "user_id": "u1",
        "notification_type": NotificationType.EXECUTION_COMPLETED,
        "channel": NotificationChannel.IN_APP,
        "subject": "s",
        "body": "b",
        "status": NotificationStatus.PENDING,
        "created_at": now,
    }
    mock_db.notifications.find.return_value = Cursor([base])
    pending = await repo.find_pending_notifications()
    assert len(pending) == 1 and pending[0].status == NotificationStatus.PENDING

    base2 = base | {"scheduled_for": now + timedelta(seconds=1)}
    mock_db.notifications.find.return_value = Cursor([base2])
    scheduled = await repo.find_scheduled_notifications()
    assert len(scheduled) == 1 and scheduled[0].scheduled_for >= datetime.now(UTC)


@pytest.mark.asyncio
async def test_cleanup_old_notifications(repo: NotificationRepository, mock_db: AsyncMock) -> None:
    mock_db.notifications.delete_many = AsyncMock(return_value=MagicMock(deleted_count=5))
    assert await repo.cleanup_old_notifications(days=1) == 5


@pytest.mark.asyncio
async def test_subscriptions(repo: NotificationRepository, mock_db: AsyncMock) -> None:
    sub = DomainNotificationSubscription(user_id="u1", channel=NotificationChannel.IN_APP, notification_types=[])
    mock_db.notification_subscriptions.replace_one = AsyncMock()
    await repo.upsert_subscription("u1", NotificationChannel.IN_APP, sub)
    mock_db.notification_subscriptions.replace_one.assert_called_once()

    mock_db.notification_subscriptions.find_one = AsyncMock(return_value={
        "user_id": sub.user_id,
        "channel": sub.channel,
        "enabled": sub.enabled,
        "notification_types": sub.notification_types,
    })
    got = await repo.get_subscription("u1", NotificationChannel.IN_APP)
    assert got and got.user_id == "u1"

    # get_all_subscriptions returns defaults for missing
    mock_db.notification_subscriptions.find_one = AsyncMock(return_value=None)
    subs = await repo.get_all_subscriptions("u1")
    assert isinstance(subs, dict)
    # one entry for each channel
    from app.domain.enums.notification import NotificationChannel as NC
    assert len(subs) == len(list(NC))


@pytest.mark.asyncio
async def test_rules_crud(repo: NotificationRepository, mock_db: AsyncMock) -> None:
    rule = DomainNotificationRule(name="r", event_types=["X"], notification_type=NotificationType.EXECUTION_COMPLETED, channels=[NotificationChannel.IN_APP])
    mock_db.notification_rules.insert_one = AsyncMock(return_value=MagicMock(inserted_id="oid"))
    rid = await repo.create_rule(rule)
    assert rid == "oid"

    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    mock_db.notification_rules.find.return_value = Cursor([
        {
            "rule_id": rule.rule_id,
            "name": rule.name,
            "event_types": rule.event_types,
            "notification_type": rule.notification_type,
            "channels": rule.channels,
            "enabled": rule.enabled,
        }
    ])
    rules = await repo.get_rules_for_event("X")
    assert len(rules) == 1 and rules[0].name == "r"

    mock_db.notification_rules.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    assert await repo.update_rule("rid", rule) is True
    mock_db.notification_rules.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    assert await repo.delete_rule("rid") is True


@pytest.mark.asyncio
async def test_get_users_by_roles_and_active(repo: NotificationRepository, mock_db: AsyncMock) -> None:
    # users by roles
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    mock_db.users.find.return_value = Cursor([{UserFields.USER_ID: "u1"}, {UserFields.USER_ID: "u2"}])
    ids = await repo.get_users_by_roles([UserRole.USER])
    assert set(ids) == {"u1", "u2"}

    # active users: combine user logins and executions
    class CursorWithLimit(Cursor):
        def limit(self, *_a, **_k):
            return self
    mock_db.users.find.return_value = Cursor([{UserFields.USER_ID: "u1"}])
    mock_db.executions.find.return_value = CursorWithLimit([{UserFields.USER_ID: "u2"}])
    active = await repo.get_active_users(days=1)
    assert set(active) == {"u1", "u2"}


@pytest.mark.asyncio
async def test_create_indexes_exception(repo: NotificationRepository, mock_db) -> None:
    # Make list_indexes().to_list raise to exercise except path
    li = AsyncMock()
    li.to_list = AsyncMock(side_effect=Exception("boom"))
    mock_db.notifications.list_indexes = AsyncMock(return_value=li)
    with pytest.raises(Exception):
        await repo.create_indexes()
