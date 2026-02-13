from datetime import UTC, datetime, timedelta

import structlog
from beanie.odm.enums import SortDirection
from beanie.operators import GTE, LTE, ElemMatch, In, NotIn, Or

from app.db.docs import NotificationDocument, NotificationSubscriptionDocument, UserDocument
from app.domain.enums import NotificationChannel, NotificationStatus, UserRole
from app.domain.notification import (
    DomainNotification,
    DomainNotificationCreate,
    DomainNotificationSubscription,
    DomainNotificationUpdate,
    DomainSubscriptionUpdate,
)


class NotificationRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger):
        self.logger = logger

    async def create_notification(self, create_data: DomainNotificationCreate) -> DomainNotification:
        doc = NotificationDocument(**create_data.model_dump())
        await doc.insert()
        return DomainNotification.model_validate(doc)

    async def update_notification(
        self, notification_id: str, user_id: str, update_data: DomainNotificationUpdate
    ) -> bool:
        doc = await NotificationDocument.find_one(
            NotificationDocument.notification_id == notification_id,
            NotificationDocument.user_id == user_id,
        )
        if not doc:
            return False
        update_dict = update_data.model_dump(exclude_none=True)
        if update_dict:
            await doc.set(update_dict)
        return True

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
            NotificationDocument.status == NotificationStatus.DELIVERED,
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
    ) -> list[DomainNotification]:
        conditions = [
            NotificationDocument.user_id == user_id,
            NotificationDocument.status == status if status else None,
            In(NotificationDocument.tags, include_tags) if include_tags else None,
            NotIn(NotificationDocument.tags, exclude_tags) if exclude_tags else None,
            ElemMatch(NotificationDocument.tags, {"$regex": f"^{tag_prefix}"}) if tag_prefix else None,
        ]
        conditions = [c for c in conditions if c is not None]
        docs = (
            await NotificationDocument.find(*conditions)
            .sort([("created_at", SortDirection.DESCENDING)])
            .skip(skip)
            .limit(limit)
            .to_list()
        )
        return [DomainNotification.model_validate(doc) for doc in docs]

    async def count_notifications(
        self,
        user_id: str,
        status: NotificationStatus | None = None,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        tag_prefix: str | None = None,
    ) -> int:
        conditions = [
            NotificationDocument.user_id == user_id,
            NotificationDocument.status == status if status else None,
            In(NotificationDocument.tags, include_tags) if include_tags else None,
            NotIn(NotificationDocument.tags, exclude_tags) if exclude_tags else None,
            ElemMatch(NotificationDocument.tags, {"$regex": f"^{tag_prefix}"}) if tag_prefix else None,
        ]
        conditions = [c for c in conditions if c is not None]
        return await NotificationDocument.find(*conditions).count()

    async def get_unread_count(self, user_id: str) -> int:
        return await NotificationDocument.find(
            NotificationDocument.user_id == user_id,
            In(NotificationDocument.status, [NotificationStatus.DELIVERED]),
        ).count()

    async def find_due_notifications(self, limit: int = 50) -> list[DomainNotification]:
        """Find PENDING notifications whose scheduled_for time has passed."""
        now = datetime.now(UTC)
        docs = (
            await NotificationDocument.find(
                NotificationDocument.status == NotificationStatus.PENDING,
                NotificationDocument.scheduled_for != None,  # noqa: E711
                LTE(NotificationDocument.scheduled_for, now),
            )
            .sort([("scheduled_for", SortDirection.ASCENDING)])
            .limit(limit)
            .to_list()
        )
        return [DomainNotification.model_validate(doc) for doc in docs]

    async def try_claim_pending(self, notification_id: str) -> bool:
        now = datetime.now(UTC)
        doc = await NotificationDocument.find_one(
            NotificationDocument.notification_id == notification_id,
            NotificationDocument.status == NotificationStatus.PENDING,
            Or(
                NotificationDocument.scheduled_for == None,  # noqa: E711
                LTE(NotificationDocument.scheduled_for, now),
            ),
        )
        if not doc:
            return False
        await doc.set({"status": NotificationStatus.SENDING, "sent_at": now})
        return True

    # Subscriptions
    async def get_subscription(
        self, user_id: str, channel: NotificationChannel
    ) -> DomainNotificationSubscription:
        """Get subscription for user/channel, returning default enabled subscription if none exists."""
        doc = await NotificationSubscriptionDocument.find_one(
            NotificationSubscriptionDocument.user_id == user_id,
            NotificationSubscriptionDocument.channel == channel,
        )
        if not doc:
            # Default: enabled=True for new users (consistent with get_all_subscriptions)
            return DomainNotificationSubscription(user_id=user_id, channel=channel, enabled=True)
        return DomainNotificationSubscription.model_validate(doc)

    async def upsert_subscription(
        self, user_id: str, channel: NotificationChannel, update_data: DomainSubscriptionUpdate
    ) -> DomainNotificationSubscription:
        existing = await NotificationSubscriptionDocument.find_one(
            NotificationSubscriptionDocument.user_id == user_id,
            NotificationSubscriptionDocument.channel == channel,
        )
        update_dict = update_data.model_dump(exclude_none=True)
        update_dict["updated_at"] = datetime.now(UTC)

        if existing:
            await existing.set(update_dict)
            return DomainNotificationSubscription.model_validate(existing)
        else:
            doc = NotificationSubscriptionDocument(
                user_id=user_id,
                channel=channel,
                **update_dict,
            )
            await doc.insert()
            return DomainNotificationSubscription.model_validate(doc)

    async def get_all_subscriptions(self, user_id: str) -> list[DomainNotificationSubscription]:
        subs: list[DomainNotificationSubscription] = []
        for channel in NotificationChannel:
            doc = await NotificationSubscriptionDocument.find_one(
                NotificationSubscriptionDocument.user_id == user_id,
                NotificationSubscriptionDocument.channel == channel,
            )
            if doc:
                subs.append(DomainNotificationSubscription.model_validate(doc))
            else:
                subs.append(DomainNotificationSubscription(user_id=user_id, channel=channel, enabled=True))
        return subs

    # User query operations
    async def get_users_by_roles(self, roles: list[UserRole]) -> list[str]:
        docs = await UserDocument.find(
            In(UserDocument.role, roles),
            UserDocument.is_active == True,  # noqa: E712
        ).to_list()
        user_ids = [doc.user_id for doc in docs if doc.user_id]
        self.logger.info(f"Found {len(user_ids)} users with roles {roles}")
        return user_ids

    async def get_active_users(self, days: int = 30) -> list[str]:
        from app.db.docs import ExecutionDocument

        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        user_ids: set[str] = set()

        # From users collection
        docs = await UserDocument.find(
            Or(
                GTE(UserDocument.last_login, cutoff_date),
                GTE(UserDocument.last_activity, cutoff_date),
                GTE(UserDocument.updated_at, cutoff_date),
            ),
            UserDocument.is_active == True,  # noqa: E712
        ).to_list()
        for doc in docs:
            if doc.user_id:
                user_ids.add(doc.user_id)

        # From executions
        exec_docs = (
            await ExecutionDocument.find(
                GTE(ExecutionDocument.created_at, cutoff_date),
            )
            .limit(1000)
            .to_list()
        )
        for doc in exec_docs:
            if doc.user_id:
                user_ids.add(doc.user_id)

        return list(user_ids)
