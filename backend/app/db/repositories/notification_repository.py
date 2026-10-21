from collections.abc import Mapping
from datetime import UTC, datetime

import structlog
from beanie.odm.enums import SortDirection
from beanie.operators import ElemMatch, In, NotIn

from app.db.docs import NotificationDocument
from app.domain.enums import NotificationStatus
from app.domain.notification import NotificationChanges


class NotificationRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger):
        self.logger = logger

    async def create_notification(self, notification: NotificationDocument) -> None:
        await notification.insert()

    async def update_notification(self, notification_id: str, user_id: str, changes: NotificationChanges) -> bool:
        doc = await NotificationDocument.find_one(
            NotificationDocument.notification_id == notification_id,
            NotificationDocument.user_id == user_id,
        )
        if not doc:
            return False
        await doc.update({"$set": changes})
        return True

    def _list_conditions(
        self,
        user_id: str,
        status: NotificationStatus | None,
        include_tags: list[str] | None,
        exclude_tags: list[str] | None,
        tag_prefix: str | None,
    ) -> list[Mapping[str, object] | bool]:
        conditions: list[Mapping[str, object] | bool] = [NotificationDocument.user_id == user_id]
        if status:
            conditions.append(NotificationDocument.status == status)
        if include_tags:
            conditions.append(In(NotificationDocument.tags, include_tags))
        if exclude_tags:
            conditions.append(NotIn(NotificationDocument.tags, exclude_tags))
        if tag_prefix:
            conditions.append(ElemMatch(NotificationDocument.tags, {"$regex": f"^{tag_prefix}"}))
        return conditions

    async def mark_as_read(self, notification_id: str, user_id: str) -> bool:
        doc = await NotificationDocument.find_one(
            NotificationDocument.notification_id == notification_id,
            NotificationDocument.user_id == user_id,
        )
        if not doc:
            return False
        await doc.set({"status": NotificationStatus.READ, "read_at": datetime.now(UTC)})
        return True

    async def mark_all_as_read(self, user_id: str) -> int:
        result = await NotificationDocument.find(
            NotificationDocument.user_id == user_id,
            NotificationDocument.status != NotificationStatus.READ,
            NotificationDocument.status != NotificationStatus.CLICKED,
        ).update_many({"$set": {"status": NotificationStatus.READ, "read_at": datetime.now(UTC)}})
        return result.modified_count if result and hasattr(result, "modified_count") else 0

    async def delete_notification(self, notification_id: str, user_id: str) -> bool:
        doc = await NotificationDocument.find_one(
            NotificationDocument.notification_id == notification_id,
            NotificationDocument.user_id == user_id,
        )
        if not doc:
            return False
        await doc.delete()
        return True

    async def list_notifications(
        self,
        user_id: str,
        status: NotificationStatus | None = None,
        skip: int = 0,
        limit: int = 20,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        tag_prefix: str | None = None,
    ) -> list[NotificationDocument]:
        conditions = self._list_conditions(user_id, status, include_tags, exclude_tags, tag_prefix)
        return (
            await NotificationDocument.find(*conditions)
            .sort([("created_at", SortDirection.DESCENDING)])
            .skip(skip)
            .limit(limit)
            .to_list()
        )

    async def count_notifications(
        self,
        user_id: str,
        status: NotificationStatus | None = None,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        tag_prefix: str | None = None,
    ) -> int:
        conditions = self._list_conditions(user_id, status, include_tags, exclude_tags, tag_prefix)
        return await NotificationDocument.find(*conditions).count()

    async def get_unread_count(self, user_id: str) -> int:
        return await NotificationDocument.find(
            NotificationDocument.user_id == user_id,
            In(NotificationDocument.status, [NotificationStatus.DELIVERED]),
        ).count()

    async def try_claim_pending(self, notification_id: str) -> bool:
        now = datetime.now(UTC)
        result = await NotificationDocument.find_one(
            NotificationDocument.notification_id == notification_id,
            NotificationDocument.status == NotificationStatus.PENDING,
        ).update({"$set": {"status": NotificationStatus.SENDING, "sent_at": now}})
        return bool(result and getattr(result, "modified_count", 0) > 0)
