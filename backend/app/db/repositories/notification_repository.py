from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.logging import logger
from app.schemas_pydantic.notification import (
    Notification,
    NotificationChannel,
    NotificationRule,
    NotificationStatus,
    NotificationSubscription,
    NotificationTemplate,
    NotificationType,
)


class NotificationRepository:
    """Repository handling all notification-related database operations."""

    def __init__(self, database: AsyncIOMotorDatabase):
        self.db: AsyncIOMotorDatabase = database

        # Collections
        self.notifications_collection: AsyncIOMotorCollection = self.db.notifications
        self.templates_collection: AsyncIOMotorCollection = self.db.notification_templates
        self.subscriptions_collection: AsyncIOMotorCollection = self.db.notification_subscriptions
        self.rules_collection: AsyncIOMotorCollection = self.db.notification_rules
        self.user_settings_collection: AsyncIOMotorCollection = self.db.user_settings_snapshots

    async def create_indexes(self) -> None:
        """Create database indexes for notifications."""
        try:
            # Notifications indexes
            await self.notifications_collection.create_indexes([
                IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
                IndexModel([("status", ASCENDING), ("scheduled_for", ASCENDING)]),
                IndexModel([("created_at", ASCENDING)]),  # For cleanup
                IndexModel([("notification_id", ASCENDING)], unique=True)
            ])

            # Rules indexes
            await self.rules_collection.create_indexes([
                IndexModel([("event_types", ASCENDING)]),
                IndexModel([("enabled", ASCENDING)])
            ])

            # Subscriptions indexes
            await self.subscriptions_collection.create_indexes([
                IndexModel([("user_id", ASCENDING), ("channel", ASCENDING)], unique=True),
                IndexModel([("enabled", ASCENDING)])
            ])

            logger.info("Notification indexes created successfully")
        except Exception as e:
            logger.error(f"Error creating notification indexes: {e}")
            raise

    # Template operations

    async def upsert_template(self, template: NotificationTemplate) -> None:
        """Insert or update a notification template."""
        await self.templates_collection.update_one(
            {"notification_type": template.notification_type},
            {"$set": template.model_dump()},
            upsert=True
        )

    async def bulk_upsert_templates(self, templates: list[NotificationTemplate]) -> None:
        """Bulk upsert notification templates."""
        if not templates:
            return

        for template in templates:
            await self.templates_collection.update_one(
                {"notification_type": template.notification_type},
                {"$set": template.model_dump()},
                upsert=True
            )

        logger.info(f"Bulk upserted {len(templates)} templates")

    async def get_template(self, notification_type: NotificationType) -> NotificationTemplate | None:
        """Get a notification template by type."""
        template_data = await self.templates_collection.find_one({
            "notification_type": notification_type
        })

        if template_data:
            return NotificationTemplate(**template_data)
        return None

    # Notification operations

    async def create_notification(self, notification: Notification) -> str:
        """Create a new notification."""
        result = await self.notifications_collection.insert_one(notification.model_dump())
        return str(result.inserted_id)

    async def update_notification(self, notification: Notification) -> bool:
        """Update an existing notification."""
        result = await self.notifications_collection.update_one(
            {"notification_id": str(notification.notification_id)},
            {"$set": notification.model_dump()}
        )
        return result.modified_count > 0

    async def get_notification(self, notification_id: str, user_id: str) -> Notification | None:
        """Get a notification by ID and user."""
        data = await self.notifications_collection.find_one({
            "notification_id": notification_id,
            "user_id": user_id
        })

        if data:
            return Notification(**data)
        return None

    async def mark_as_read(self, notification_id: str, user_id: str) -> bool:
        """Mark a notification as read."""
        result = await self.notifications_collection.update_one(
            {"notification_id": notification_id, "user_id": user_id},
            {
                "$set": {
                    "status": NotificationStatus.READ,
                    "read_at": datetime.now(UTC)
                }
            }
        )
        return result.modified_count > 0

    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user."""
        result = await self.notifications_collection.update_many(
            {
                "user_id": user_id,
                "status": {"$in": [NotificationStatus.SENT, NotificationStatus.DELIVERED]}
            },
            {
                "$set": {
                    "status": NotificationStatus.READ,
                    "read_at": datetime.now(UTC)
                }
            }
        )
        return result.modified_count

    async def delete_notification(self, notification_id: str, user_id: str) -> bool:
        """Delete a notification."""
        result = await self.notifications_collection.delete_one({
            "notification_id": notification_id,
            "user_id": user_id
        })
        return result.deleted_count > 0

    async def list_notifications(
            self,
            user_id: str,
            status: NotificationStatus | None = None,
            skip: int = 0,
            limit: int = 20
    ) -> list[Notification]:
        """List notifications for a user."""
        query = {"user_id": user_id}
        if status:
            query["status"] = status

        cursor = self.notifications_collection.find(query).sort(
            "created_at", DESCENDING
        ).skip(skip).limit(limit)

        notifications = []
        async for doc in cursor:
            notifications.append(Notification(**doc))

        return notifications

    async def count_notifications(self,
                                  user_id: str,
                                  query: dict[str, object] | None = None) -> int:
        """Count notifications matching query."""
        if query is None:
            query = {}
        query["user_id"] = user_id
        return await self.notifications_collection.count_documents(query)

    async def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications."""
        return await self.notifications_collection.count_documents({
            "user_id": user_id,
            "status": {"$in": [NotificationStatus.SENT, NotificationStatus.DELIVERED]}
        })

    async def find_pending_notifications(
            self,
            batch_size: int = 10
    ) -> list[Notification]:
        """Find pending notifications for processing."""
        cursor = self.notifications_collection.find({
            "status": NotificationStatus.PENDING,
            "$or": [
                {"scheduled_for": None},
                {"scheduled_for": {"$lte": datetime.now(UTC)}}
            ]
        }).limit(batch_size)

        notifications = []
        async for doc in cursor:
            notifications.append(Notification(**doc))

        return notifications

    async def find_scheduled_notifications(
            self,
            batch_size: int = 10
    ) -> list[Notification]:
        """Find due scheduled notifications."""
        cursor = self.notifications_collection.find({
            "status": NotificationStatus.PENDING,
            "scheduled_for": {
                "$lte": datetime.now(UTC),
                "$ne": None
            }
        }).limit(batch_size)

        notifications = []
        async for doc in cursor:
            notifications.append(Notification(**doc))

        return notifications

    async def cleanup_old_notifications(self, days: int = 30) -> int:
        """Delete notifications older than specified days."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await self.notifications_collection.delete_many({
            "created_at": {"$lt": cutoff}
        })
        return result.deleted_count

    # Subscription operations

    async def get_subscription(
            self,
            user_id: str,
            channel: NotificationChannel
    ) -> NotificationSubscription | None:
        """Get user's subscription for a channel."""
        sub_data = await self.subscriptions_collection.find_one({
            "user_id": user_id,
            "channel": channel
        })

        if sub_data:
            return NotificationSubscription(**sub_data)
        return None

    async def upsert_subscription(
            self,
            user_id: str,
            channel: NotificationChannel,
            subscription: NotificationSubscription
    ) -> None:
        """Create or update a subscription."""
        subscription.user_id = user_id
        subscription.channel = channel
        subscription.updated_at = datetime.now(UTC)

        await self.subscriptions_collection.replace_one(
            {"user_id": user_id, "channel": channel},
            subscription.model_dump(),
            upsert=True
        )

    async def get_all_subscriptions(self, user_id: str) -> dict[str, NotificationSubscription]:
        """Get all subscriptions for a user."""
        subscriptions = {}

        for channel in NotificationChannel:
            sub_data = await self.subscriptions_collection.find_one({
                "user_id": user_id,
                "channel": channel
            })

            if sub_data:
                subscriptions[str(channel)] = NotificationSubscription(**sub_data)
            else:
                # Return default if not found
                subscriptions[str(channel)] = NotificationSubscription(
                    user_id=user_id,
                    channel=channel,
                    enabled=True,
                    notification_types=[],
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC)
                )

        return subscriptions

    # User settings operations

    async def get_user_settings(self, user_id: str) -> dict[str, object] | None:
        """Get user notification settings."""
        settings = await self.user_settings_collection.find_one({
            "user_id": user_id
        })
        return settings

    # Rule operations

    async def create_rule(self, rule: NotificationRule) -> str:
        """Create a notification rule."""
        result = await self.rules_collection.insert_one(rule.model_dump())
        return str(result.inserted_id)

    async def get_rules_for_event(self, event_type: str) -> list[NotificationRule]:
        """Get active rules that match an event type."""
        cursor = self.rules_collection.find({
            "event_types": event_type,
            "enabled": True
        })

        rules = []
        async for doc in cursor:
            rules.append(NotificationRule(**doc))

        return rules

    async def update_rule(self, rule_id: str, rule: NotificationRule) -> bool:
        """Update a notification rule."""
        result = await self.rules_collection.update_one(
            {"rule_id": rule_id},
            {"$set": rule.model_dump()}
        )
        return result.modified_count > 0

    async def delete_rule(self, rule_id: str) -> bool:
        """Delete a notification rule."""
        result = await self.rules_collection.delete_one({"rule_id": rule_id})
        return result.deleted_count > 0

    # User query operations for system notifications

    async def get_users_by_roles(self, roles: list[str]) -> list[str]:
        """Get user IDs that have any of the specified roles.
        
        Args:
            roles: List of role names to filter by
            
        Returns:
            List of user IDs
        """
        # Query the users collection for users with matching roles
        users_collection = self.db.users
        cursor = users_collection.find(
            {
                "roles": {"$in": roles},
                "is_active": True  # Only get active users
            },
            {"user_id": 1}  # Only return user_id field
        )
        
        user_ids = []
        async for user in cursor:
            if user.get("user_id"):
                user_ids.append(user["user_id"])
        
        logger.info(f"Found {len(user_ids)} users with roles {roles}")
        return user_ids

    async def get_active_users(self, days: int = 30) -> list[str]:
        """Get user IDs of users who have been active within the specified days.
        
        Args:
            days: Number of days to look back for activity
            
        Returns:
            List of active user IDs
        """
        # Calculate cutoff date
        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        
        # Query users who have logged in recently or have recent executions
        users_collection = self.db.users
        
        # First, get users with recent login activity
        cursor = users_collection.find(
            {
                "$or": [
                    {"last_login": {"$gte": cutoff_date}},
                    {"last_activity": {"$gte": cutoff_date}},
                    {"updated_at": {"$gte": cutoff_date}}
                ],
                "is_active": True
            },
            {"user_id": 1}
        )
        
        user_ids = set()
        async for user in cursor:
            if user.get("user_id"):
                user_ids.add(user["user_id"])
        
        # Also check executions collection for recent activity
        executions_collection = self.db.executions
        exec_cursor = executions_collection.find(
            {
                "created_at": {"$gte": cutoff_date}
            },
            {"user_id": 1}
        ).limit(1000)  # Limit to prevent memory issues
        
        async for execution in exec_cursor:
            if execution.get("user_id"):
                user_ids.add(execution["user_id"])
        
        user_ids_list = list(user_ids)
        logger.info(f"Found {len(user_ids_list)} active users in the last {days} days")
        return user_ids_list
