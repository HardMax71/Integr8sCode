from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.logging import logger
from app.domain.admin.user_models import UserFields
from app.domain.enums.notification import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.domain.enums.user import UserRole
from app.domain.notification.models import (
    DomainNotification,
    DomainNotificationRule,
    DomainNotificationSubscription,
    DomainNotificationTemplate,
)


class NotificationRepository:
    def __init__(self, database: AsyncIOMotorDatabase):
        self.db: AsyncIOMotorDatabase = database

        # Collections
        self.notifications_collection: AsyncIOMotorCollection = self.db.notifications
        self.templates_collection: AsyncIOMotorCollection = self.db.notification_templates
        self.subscriptions_collection: AsyncIOMotorCollection = self.db.notification_subscriptions
        self.rules_collection: AsyncIOMotorCollection = self.db.notification_rules

    async def create_indexes(self) -> None:
        try:
            # Create indexes if only _id exists
            notif_indexes = await self.notifications_collection.list_indexes().to_list(None)
            if len(notif_indexes) <= 1:
                await self.notifications_collection.create_indexes([
                    IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
                    IndexModel([("status", ASCENDING), ("scheduled_for", ASCENDING)]),
                    IndexModel([("created_at", ASCENDING)]),
                    IndexModel([("notification_id", ASCENDING)], unique=True),
                ])

            rules_indexes = await self.rules_collection.list_indexes().to_list(None)
            if len(rules_indexes) <= 1:
                await self.rules_collection.create_indexes([
                    IndexModel([("event_types", ASCENDING)]),
                    IndexModel([("enabled", ASCENDING)]),
                ])

            subs_indexes = await self.subscriptions_collection.list_indexes().to_list(None)
            if len(subs_indexes) <= 1:
                await self.subscriptions_collection.create_indexes([
                    IndexModel([("user_id", ASCENDING), ("channel", ASCENDING)], unique=True),
                    IndexModel([("enabled", ASCENDING)]),
                ])
        except Exception as e:
            logger.error(f"Error creating notification indexes: {e}")
            raise

    # Templates
    async def upsert_template(self, template: DomainNotificationTemplate) -> None:
        await self.templates_collection.update_one(
            {"notification_type": template.notification_type},
            {"$set": {
                "notification_type": template.notification_type,
                "channels": template.channels,
                "priority": template.priority,
                "subject_template": template.subject_template,
                "body_template": template.body_template,
                "action_url_template": template.action_url_template,
                "metadata": template.metadata,
            }},
            upsert=True,
        )

    async def bulk_upsert_templates(self, templates: list[DomainNotificationTemplate]) -> None:
        for t in templates:
            await self.upsert_template(t)
        logger.info(f"Bulk upserted {len(templates)} templates")

    async def get_template(self, notification_type: NotificationType) -> DomainNotificationTemplate | None:
        doc = await self.templates_collection.find_one({"notification_type": notification_type})
        if not doc:
            return None
        return DomainNotificationTemplate(
            notification_type=doc.get("notification_type"),
            channels=doc.get("channels", []),
            priority=doc.get("priority"),
            subject_template=doc.get("subject_template", ""),
            body_template=doc.get("body_template", ""),
            action_url_template=doc.get("action_url_template"),
            metadata=doc.get("metadata", {}),
        )

    # Notifications
    async def create_notification(self, notification: DomainNotification) -> str:
        result = await self.notifications_collection.insert_one({
            "notification_id": notification.notification_id,
            "user_id": notification.user_id,
            "notification_type": notification.notification_type,
            "channel": notification.channel,
            "priority": notification.priority,
            "status": notification.status,
            "subject": notification.subject,
            "body": notification.body,
            "action_url": notification.action_url,
            "created_at": notification.created_at,
            "scheduled_for": notification.scheduled_for,
            "sent_at": notification.sent_at,
            "delivered_at": notification.delivered_at,
            "read_at": notification.read_at,
            "clicked_at": notification.clicked_at,
            "failed_at": notification.failed_at,
            "retry_count": notification.retry_count,
            "max_retries": notification.max_retries,
            "error_message": notification.error_message,
            "correlation_id": notification.correlation_id,
            "related_entity_id": notification.related_entity_id,
            "related_entity_type": notification.related_entity_type,
            "metadata": notification.metadata,
            "webhook_url": notification.webhook_url,
            "webhook_headers": notification.webhook_headers,
        })
        return str(result.inserted_id)

    async def update_notification(self, notification: DomainNotification) -> bool:
        update = {
            "user_id": notification.user_id,
            "notification_type": notification.notification_type,
            "channel": notification.channel,
            "priority": notification.priority,
            "status": notification.status,
            "subject": notification.subject,
            "body": notification.body,
            "action_url": notification.action_url,
            "created_at": notification.created_at,
            "scheduled_for": notification.scheduled_for,
            "sent_at": notification.sent_at,
            "delivered_at": notification.delivered_at,
            "read_at": notification.read_at,
            "clicked_at": notification.clicked_at,
            "failed_at": notification.failed_at,
            "retry_count": notification.retry_count,
            "max_retries": notification.max_retries,
            "error_message": notification.error_message,
            "correlation_id": notification.correlation_id,
            "related_entity_id": notification.related_entity_id,
            "related_entity_type": notification.related_entity_type,
            "metadata": notification.metadata,
            "webhook_url": notification.webhook_url,
            "webhook_headers": notification.webhook_headers,
        }
        result = await self.notifications_collection.update_one(
            {"notification_id": str(notification.notification_id)}, {"$set": update}
        )
        return result.modified_count > 0

    async def get_notification(self, notification_id: str, user_id: str) -> DomainNotification | None:
        doc = await self.notifications_collection.find_one({
            "notification_id": notification_id,
            "user_id": user_id,
        })
        if not doc:
            return None
        return DomainNotification(
            notification_id=doc.get("notification_id"),
            user_id=doc.get("user_id"),
            notification_type=doc.get("notification_type"),
            channel=doc.get("channel"),
            priority=doc.get("priority"),
            status=doc.get("status"),
            subject=doc.get("subject", ""),
            body=doc.get("body", ""),
            action_url=doc.get("action_url"),
            created_at=doc.get("created_at", datetime.now(UTC)),
            scheduled_for=doc.get("scheduled_for"),
            sent_at=doc.get("sent_at"),
            delivered_at=doc.get("delivered_at"),
            read_at=doc.get("read_at"),
            clicked_at=doc.get("clicked_at"),
            failed_at=doc.get("failed_at"),
            retry_count=doc.get("retry_count", 0),
            max_retries=doc.get("max_retries", 3),
            error_message=doc.get("error_message"),
            correlation_id=doc.get("correlation_id"),
            related_entity_id=doc.get("related_entity_id"),
            related_entity_type=doc.get("related_entity_type"),
            metadata=doc.get("metadata", {}),
            webhook_url=doc.get("webhook_url"),
            webhook_headers=doc.get("webhook_headers"),
        )

    async def mark_as_read(self, notification_id: str, user_id: str) -> bool:
        result = await self.notifications_collection.update_one(
            {"notification_id": notification_id, "user_id": user_id},
            {"$set": {"status": NotificationStatus.READ, "read_at": datetime.now(UTC)}},
        )
        return result.modified_count > 0

    async def mark_all_as_read(self, user_id: str) -> int:
        result = await self.notifications_collection.update_many(
            {"user_id": user_id, "status": {"$in": [NotificationStatus.SENT, NotificationStatus.DELIVERED]}},
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
    ) -> list[DomainNotification]:
        query: dict[str, object] = {"user_id": user_id}
        if status:
            query["status"] = status

        cursor = (
            self.notifications_collection.find(query)
            .sort("created_at", DESCENDING)
            .skip(skip)
            .limit(limit)
        )

        items: list[DomainNotification] = []
        async for doc in cursor:
            items.append(
                DomainNotification(
                    notification_id=doc.get("notification_id"),
                    user_id=doc.get("user_id"),
                    notification_type=doc.get("notification_type"),
                    channel=doc.get("channel"),
                    priority=doc.get("priority"),
                    status=doc.get("status"),
                    subject=doc.get("subject", ""),
                    body=doc.get("body", ""),
                    action_url=doc.get("action_url"),
                    created_at=doc.get("created_at", datetime.now(UTC)),
                    scheduled_for=doc.get("scheduled_for"),
                    sent_at=doc.get("sent_at"),
                    delivered_at=doc.get("delivered_at"),
                    read_at=doc.get("read_at"),
                    clicked_at=doc.get("clicked_at"),
                    failed_at=doc.get("failed_at"),
                    retry_count=doc.get("retry_count", 0),
                    max_retries=doc.get("max_retries", 3),
                    error_message=doc.get("error_message"),
                    correlation_id=doc.get("correlation_id"),
                    related_entity_id=doc.get("related_entity_id"),
                    related_entity_type=doc.get("related_entity_type"),
                    metadata=doc.get("metadata", {}),
                    webhook_url=doc.get("webhook_url"),
                    webhook_headers=doc.get("webhook_headers"),
                )
            )
        return items

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
                "status": {"$in": [NotificationStatus.SENT, NotificationStatus.DELIVERED]},
            }
        )

    async def find_pending_notifications(self, batch_size: int = 10) -> list[DomainNotification]:
        cursor = self.notifications_collection.find(
            {
                "status": NotificationStatus.PENDING,
                "$or": [{"scheduled_for": None}, {"scheduled_for": {"$lte": datetime.now(UTC)}}],
            }
        ).limit(batch_size)

        items: list[DomainNotification] = []
        async for doc in cursor:
            items.append(
                DomainNotification(
                    notification_id=doc.get("notification_id"),
                    user_id=doc.get("user_id"),
                    notification_type=doc.get("notification_type"),
                    channel=doc.get("channel"),
                    priority=doc.get("priority"),
                    status=doc.get("status"),
                    subject=doc.get("subject", ""),
                    body=doc.get("body", ""),
                    action_url=doc.get("action_url"),
                    created_at=doc.get("created_at", datetime.now(UTC)),
                    scheduled_for=doc.get("scheduled_for"),
                    sent_at=doc.get("sent_at"),
                    delivered_at=doc.get("delivered_at"),
                    read_at=doc.get("read_at"),
                    clicked_at=doc.get("clicked_at"),
                    failed_at=doc.get("failed_at"),
                    retry_count=doc.get("retry_count", 0),
                    max_retries=doc.get("max_retries", 3),
                    error_message=doc.get("error_message"),
                    correlation_id=doc.get("correlation_id"),
                    related_entity_id=doc.get("related_entity_id"),
                    related_entity_type=doc.get("related_entity_type"),
                    metadata=doc.get("metadata", {}),
                    webhook_url=doc.get("webhook_url"),
                    webhook_headers=doc.get("webhook_headers"),
                )
            )
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
            items.append(
                DomainNotification(
                    notification_id=doc.get("notification_id"),
                    user_id=doc.get("user_id"),
                    notification_type=doc.get("notification_type"),
                    channel=doc.get("channel"),
                    priority=doc.get("priority"),
                    status=doc.get("status"),
                    subject=doc.get("subject", ""),
                    body=doc.get("body", ""),
                    action_url=doc.get("action_url"),
                    created_at=doc.get("created_at", datetime.now(UTC)),
                    scheduled_for=doc.get("scheduled_for"),
                    sent_at=doc.get("sent_at"),
                    delivered_at=doc.get("delivered_at"),
                    read_at=doc.get("read_at"),
                    clicked_at=doc.get("clicked_at"),
                    failed_at=doc.get("failed_at"),
                    retry_count=doc.get("retry_count", 0),
                    max_retries=doc.get("max_retries", 3),
                    error_message=doc.get("error_message"),
                    correlation_id=doc.get("correlation_id"),
                    related_entity_id=doc.get("related_entity_id"),
                    related_entity_type=doc.get("related_entity_type"),
                    metadata=doc.get("metadata", {}),
                    webhook_url=doc.get("webhook_url"),
                    webhook_headers=doc.get("webhook_headers"),
                )
            )
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
        return DomainNotificationSubscription(
            user_id=doc.get("user_id"),
            channel=doc.get("channel"),
            enabled=doc.get("enabled", True),
            notification_types=doc.get("notification_types", []),
            webhook_url=doc.get("webhook_url"),
            slack_webhook=doc.get("slack_webhook"),
            quiet_hours_enabled=doc.get("quiet_hours_enabled", False),
            quiet_hours_start=doc.get("quiet_hours_start"),
            quiet_hours_end=doc.get("quiet_hours_end"),
            timezone=doc.get("timezone", "UTC"),
            batch_interval_minutes=doc.get("batch_interval_minutes", 60),
            created_at=doc.get("created_at", datetime.now(UTC)),
            updated_at=doc.get("updated_at", datetime.now(UTC)),
        )

    async def upsert_subscription(
        self,
        user_id: str,
        channel: NotificationChannel,
        subscription: DomainNotificationSubscription,
    ) -> None:
        subscription.user_id = user_id
        subscription.channel = channel
        subscription.updated_at = datetime.now(UTC)
        doc = {
            "user_id": subscription.user_id,
            "channel": subscription.channel,
            "enabled": subscription.enabled,
            "notification_types": subscription.notification_types,
            "webhook_url": subscription.webhook_url,
            "slack_webhook": subscription.slack_webhook,
            "quiet_hours_enabled": subscription.quiet_hours_enabled,
            "quiet_hours_start": subscription.quiet_hours_start,
            "quiet_hours_end": subscription.quiet_hours_end,
            "timezone": subscription.timezone,
            "batch_interval_minutes": subscription.batch_interval_minutes,
            "created_at": subscription.created_at,
            "updated_at": subscription.updated_at,
        }
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
                subs[str(channel)] = DomainNotificationSubscription(
                    user_id=doc.get("user_id"),
                    channel=doc.get("channel"),
                    enabled=doc.get("enabled", True),
                    notification_types=doc.get("notification_types", []),
                    webhook_url=doc.get("webhook_url"),
                    slack_webhook=doc.get("slack_webhook"),
                    quiet_hours_enabled=doc.get("quiet_hours_enabled", False),
                    quiet_hours_start=doc.get("quiet_hours_start"),
                    quiet_hours_end=doc.get("quiet_hours_end"),
                    timezone=doc.get("timezone", "UTC"),
                    batch_interval_minutes=doc.get("batch_interval_minutes", 60),
                    created_at=doc.get("created_at", datetime.now(UTC)),
                    updated_at=doc.get("updated_at", datetime.now(UTC)),
                )
            else:
                subs[str(channel)] = DomainNotificationSubscription(
                    user_id=user_id, channel=channel, enabled=True, notification_types=[]
                )
        return subs

    # Rules
    async def create_rule(self, rule: DomainNotificationRule) -> str:
        doc = {
            "rule_id": rule.rule_id,
            "name": rule.name,
            "description": rule.description,
            "enabled": rule.enabled,
            "event_types": rule.event_types,
            "conditions": rule.conditions,
            "notification_type": rule.notification_type,
            "channels": rule.channels,
            "priority": rule.priority,
            "template_id": rule.template_id,
            "throttle_minutes": rule.throttle_minutes,
            "max_per_hour": rule.max_per_hour,
            "max_per_day": rule.max_per_day,
            "created_at": rule.created_at,
            "updated_at": rule.updated_at,
            "created_by": rule.created_by,
        }
        result = await self.rules_collection.insert_one(doc)
        return str(result.inserted_id)

    async def get_rules_for_event(self, event_type: str) -> list[DomainNotificationRule]:
        cursor = self.rules_collection.find({"event_types": event_type, "enabled": True})
        rules: list[DomainNotificationRule] = []
        async for doc in cursor:
            rules.append(
                DomainNotificationRule(
                    rule_id=doc.get("rule_id"),
                    name=doc.get("name", ""),
                    description=doc.get("description"),
                    enabled=doc.get("enabled", True),
                    event_types=list(doc.get("event_types", [])),
                    conditions=dict(doc.get("conditions", {})),
                    notification_type=doc.get("notification_type"),
                    channels=list(doc.get("channels", [])),
                    priority=doc.get("priority"),
                    template_id=doc.get("template_id"),
                    throttle_minutes=doc.get("throttle_minutes"),
                    max_per_hour=doc.get("max_per_hour"),
                    max_per_day=doc.get("max_per_day"),
                    created_at=doc.get("created_at", datetime.now(UTC)),
                    updated_at=doc.get("updated_at", datetime.now(UTC)),
                    created_by=doc.get("created_by"),
                )
            )
        return rules

    async def update_rule(self, rule_id: str, rule: DomainNotificationRule) -> bool:
        update = {
            "name": rule.name,
            "description": rule.description,
            "enabled": rule.enabled,
            "event_types": rule.event_types,
            "conditions": rule.conditions,
            "notification_type": rule.notification_type,
            "channels": rule.channels,
            "priority": rule.priority,
            "template_id": rule.template_id,
            "throttle_minutes": rule.throttle_minutes,
            "max_per_hour": rule.max_per_hour,
            "max_per_day": rule.max_per_day,
            "updated_at": datetime.now(UTC),
        }
        result = await self.rules_collection.update_one(
            {"rule_id": rule_id}, {"$set": update}
        )
        return result.modified_count > 0

    async def delete_rule(self, rule_id: str) -> bool:
        result = await self.rules_collection.delete_one({"rule_id": rule_id})
        return result.deleted_count > 0

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

