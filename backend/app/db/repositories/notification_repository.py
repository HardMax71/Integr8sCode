from datetime import UTC, datetime, timedelta

from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.database_context import Collection, Database
from app.core.logging import logger
from app.domain.enums.notification import (
    NotificationChannel,
    NotificationStatus,
)
from app.domain.enums.user import UserRole
from app.domain.events.event_models import CollectionNames
from app.domain.notification import DomainNotification, DomainNotificationSubscription
from app.domain.user import UserFields
from app.infrastructure.mappers import NotificationMapper


class NotificationRepository:
    def __init__(self, database: Database):
        self.db: Database = database

        self.notifications_collection: Collection = self.db.get_collection(CollectionNames.NOTIFICATIONS)
        self.subscriptions_collection: Collection = self.db.get_collection(
            CollectionNames.NOTIFICATION_SUBSCRIPTIONS)
        self.mapper = NotificationMapper()

    async def create_indexes(self) -> None:
        # Create indexes if only _id exists
        notif_indexes = await self.notifications_collection.list_indexes().to_list(None)
        if len(notif_indexes) <= 1:
            await self.notifications_collection.create_indexes([
                IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
                IndexModel([("status", ASCENDING), ("scheduled_for", ASCENDING)]),
                IndexModel([("created_at", ASCENDING)]),
                IndexModel([("notification_id", ASCENDING)], unique=True),
                # Multikey index to speed up tag queries (include/exclude/prefix)
                IndexModel([("tags", ASCENDING)]),
            ])

        subs_indexes = await self.subscriptions_collection.list_indexes().to_list(None)
        if len(subs_indexes) <= 1:
            await self.subscriptions_collection.create_indexes([
                IndexModel([("user_id", ASCENDING), ("channel", ASCENDING)], unique=True),
                IndexModel([("enabled", ASCENDING)]),
                IndexModel([("include_tags", ASCENDING)]),
                IndexModel([("severities", ASCENDING)]),
            ])

    # Notifications
    async def create_notification(self, notification: DomainNotification) -> str:
        doc = self.mapper.to_mongo_document(notification)
        result = await self.notifications_collection.insert_one(doc)
        return str(result.inserted_id)

    async def update_notification(self, notification: DomainNotification) -> bool:
        update = self.mapper.to_update_dict(notification)
        result = await self.notifications_collection.update_one(
            {"notification_id": str(notification.notification_id)}, {"$set": update}
        )
        return result.modified_count > 0

    async def get_notification(self, notification_id: str, user_id: str) -> DomainNotification | None:
        doc = await self.notifications_collection.find_one(
            {"notification_id": notification_id, "user_id": user_id}
        )
        if not doc:
            return None
        return self.mapper.from_mongo_document(doc)

    async def mark_as_read(self, notification_id: str, user_id: str) -> bool:
        result = await self.notifications_collection.update_one(
            {"notification_id": notification_id, "user_id": user_id},
            {"$set": {"status": NotificationStatus.READ, "read_at": datetime.now(UTC)}},
        )
        return result.modified_count > 0

    async def mark_all_as_read(self, user_id: str) -> int:
        result = await self.notifications_collection.update_many(
            {"user_id": user_id, "status": {"$in": [NotificationStatus.DELIVERED]}},
            {"$set": {"status": NotificationStatus.READ, "read_at": datetime.now(UTC)}},
        )
        return result.modified_count

    async def delete_notification(self, notification_id: str, user_id: str) -> bool:
        result = await self.notifications_collection.delete_one(
            {"notification_id": notification_id, "user_id": user_id}
        )
        return result.deleted_count > 0

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
        base: dict[str, object] = {"user_id": user_id}
        if status:
            base["status"] = status
        query: dict[str, object] | None = base
        tag_filters: list[dict[str, object]] = []
        if include_tags:
            tag_filters.append({"tags": {"$in": include_tags}})
        if exclude_tags:
            tag_filters.append({"tags": {"$nin": exclude_tags}})
        if tag_prefix:
            tag_filters.append({"tags": {"$elemMatch": {"$regex": f"^{tag_prefix}"}}})
        if tag_filters:
            query = {"$and": [base] + tag_filters}

        cursor = (
            self.notifications_collection.find(query or base)
            .sort("created_at", DESCENDING)
            .skip(skip)
            .limit(limit)
        )

        items: list[DomainNotification] = []
        async for doc in cursor:
            items.append(self.mapper.from_mongo_document(doc))
        return items

    async def list_notifications_by_tag(
            self,
            user_id: str,
            tag: str,
            skip: int = 0,
            limit: int = 20,
    ) -> list[DomainNotification]:
        """Convenience helper to list notifications filtered by a single exact tag."""
        return await self.list_notifications(
            user_id=user_id,
            skip=skip,
            limit=limit,
            include_tags=[tag],
        )

    async def count_notifications(
            self, user_id: str, additional_filters: dict[str, object] | None = None
    ) -> int:
        query: dict[str, object] = {"user_id": user_id}
        if additional_filters:
            query.update(additional_filters)
        return await self.notifications_collection.count_documents(query)

    async def get_unread_count(self, user_id: str) -> int:
        return await self.notifications_collection.count_documents(
            {
                "user_id": user_id,
                "status": {"$in": [NotificationStatus.DELIVERED]},
            }
        )

    async def try_claim_pending(self, notification_id: str) -> bool:
        """Atomically claim a pending notification for delivery.

        Transitions PENDING -> SENDING when scheduled_for is None or due.
        Returns True if the document was claimed by this caller.
        """
        now = datetime.now(UTC)
        result = await self.notifications_collection.update_one(
            {
                "notification_id": notification_id,
                "status": NotificationStatus.PENDING,
                "$or": [{"scheduled_for": None}, {"scheduled_for": {"$lte": now}}],
            },
            {"$set": {"status": NotificationStatus.SENDING, "sent_at": now}},
        )
        return result.modified_count > 0

    async def find_pending_notifications(self, batch_size: int = 10) -> list[DomainNotification]:
        cursor = self.notifications_collection.find(
            {
                "status": NotificationStatus.PENDING,
                "$or": [{"scheduled_for": None}, {"scheduled_for": {"$lte": datetime.now(UTC)}}],
            }
        ).limit(batch_size)

        items: list[DomainNotification] = []
        async for doc in cursor:
            items.append(self.mapper.from_mongo_document(doc))
        return items

    async def find_scheduled_notifications(self, batch_size: int = 10) -> list[DomainNotification]:
        cursor = self.notifications_collection.find(
            {
                "status": NotificationStatus.PENDING,
                "scheduled_for": {"$lte": datetime.now(UTC), "$ne": None},
            }
        ).limit(batch_size)

        items: list[DomainNotification] = []
        async for doc in cursor:
            items.append(self.mapper.from_mongo_document(doc))
        return items

    async def cleanup_old_notifications(self, days: int = 30) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await self.notifications_collection.delete_many({"created_at": {"$lt": cutoff}})
        return result.deleted_count

    # Subscriptions
    async def get_subscription(
            self, user_id: str, channel: NotificationChannel
    ) -> DomainNotificationSubscription | None:
        doc = await self.subscriptions_collection.find_one(
            {"user_id": user_id, "channel": channel}
        )
        if not doc:
            return None
        return self.mapper.subscription_from_mongo_document(doc)

    async def upsert_subscription(
            self,
            user_id: str,
            channel: NotificationChannel,
            subscription: DomainNotificationSubscription,
    ) -> None:
        subscription.user_id = user_id
        subscription.channel = channel
        subscription.updated_at = datetime.now(UTC)
        doc = self.mapper.subscription_to_mongo_document(subscription)
        await self.subscriptions_collection.replace_one(
            {"user_id": user_id, "channel": channel}, doc, upsert=True
        )

    async def get_all_subscriptions(
            self, user_id: str
    ) -> dict[str, DomainNotificationSubscription]:
        subs: dict[str, DomainNotificationSubscription] = {}
        for channel in NotificationChannel:
            doc = await self.subscriptions_collection.find_one(
                {"user_id": user_id, "channel": channel}
            )
            if doc:
                subs[channel] = self.mapper.subscription_from_mongo_document(doc)
            else:
                subs[channel] = DomainNotificationSubscription(
                    user_id=user_id, channel=channel, enabled=True
                )
        return subs

    # User query operations for system notifications
    async def get_users_by_roles(self, roles: list[UserRole]) -> list[str]:
        users_collection = self.db.users
        role_values = [role.value for role in roles]
        cursor = users_collection.find(
            {UserFields.ROLE: {"$in": role_values}, UserFields.IS_ACTIVE: True},
            {UserFields.USER_ID: 1},
        )

        user_ids: list[str] = []
        async for user in cursor:
            if user.get("user_id"):
                user_ids.append(user["user_id"])

        logger.info(f"Found {len(user_ids)} users with roles {role_values}")
        return user_ids

    async def get_active_users(self, days: int = 30) -> list[str]:
        cutoff_date = datetime.now(UTC) - timedelta(days=days)

        users_collection = self.db.users
        cursor = users_collection.find(
            {
                "$or": [
                    {"last_login": {"$gte": cutoff_date}},
                    {"last_activity": {"$gte": cutoff_date}},
                    {"updated_at": {"$gte": cutoff_date}},
                ],
                "is_active": True,
            },
            {"user_id": 1},
        )

        user_ids = set()
        async for user in cursor:
            if user.get("user_id"):
                user_ids.add(user["user_id"])

        executions_collection = self.db.executions
        exec_cursor = executions_collection.find(
            {"created_at": {"$gte": cutoff_date}}, {"user_id": 1}
        ).limit(1000)

        async for execution in exec_cursor:
            if execution.get("user_id"):
                user_ids.add(execution["user_id"])

        return list(user_ids)
