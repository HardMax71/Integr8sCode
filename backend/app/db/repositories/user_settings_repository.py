from datetime import datetime, timezone
from typing import Any, Dict, List

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.logging import logger
from app.domain.enums import Theme
from app.domain.enums.events import EventType
from app.domain.user.settings_models import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainSettingsEvent,
    DomainUserSettings,
)


class UserSettingsRepository:
    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self.db = database

    async def create_indexes(self) -> None:
        try:
            # Create indexes for settings snapshots
            await self.db.user_settings_snapshots.create_indexes([
                IndexModel([("user_id", ASCENDING)], unique=True),
                IndexModel([("updated_at", DESCENDING)]),
            ])

            # Create indexes for settings events
            await self.db.events.create_indexes([
                IndexModel([("event_type", ASCENDING), ("aggregate_id", ASCENDING)]),
                IndexModel([("aggregate_id", ASCENDING), ("timestamp", ASCENDING)]),
            ])

            logger.info("User settings repository indexes created successfully")
        except Exception as e:
            logger.error(f"Error creating user settings indexes: {e}")
            raise

    async def get_snapshot(self, user_id: str) -> DomainUserSettings | None:
        doc = await self.db.user_settings_snapshots.find_one({"user_id": user_id})
        if not doc:
            return None
        # Map DB -> domain with defaults
        notifications = doc.get("notifications", {})
        editor = doc.get("editor", {})
        theme_val = doc.get("theme")
        return DomainUserSettings(
            user_id=str(doc.get("user_id")),
            theme=Theme(theme_val),
            timezone=doc.get("timezone", "UTC"),
            date_format=doc.get("date_format", "YYYY-MM-DD"),
            time_format=doc.get("time_format", "24h"),
            notifications=DomainNotificationSettings(
                execution_completed=notifications.get("execution_completed", True),
                execution_failed=notifications.get("execution_failed", True),
                system_updates=notifications.get("system_updates", True),
                security_alerts=notifications.get("security_alerts", True),
                channels=notifications.get("channels", []),
            ),
            editor=DomainEditorSettings(
                theme=editor.get("theme", "one-dark"),
                font_size=editor.get("font_size", 14),
                tab_size=editor.get("tab_size", 4),
                use_tabs=editor.get("use_tabs", False),
                word_wrap=editor.get("word_wrap", True),
                show_line_numbers=editor.get("show_line_numbers", True),
            ),
            custom_settings=doc.get("custom_settings", {}),
            version=doc.get("version", 1),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
            updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
        )

    async def create_snapshot(self, settings: DomainUserSettings) -> None:
        doc = {
            "user_id": settings.user_id,
            "theme": settings.theme,
            "timezone": settings.timezone,
            "date_format": settings.date_format,
            "time_format": settings.time_format,
            "notifications": {
                "execution_completed": settings.notifications.execution_completed,
                "execution_failed": settings.notifications.execution_failed,
                "system_updates": settings.notifications.system_updates,
                "security_alerts": settings.notifications.security_alerts,
                "channels": settings.notifications.channels,
            },
            "editor": {
                "theme": settings.editor.theme,
                "font_size": settings.editor.font_size,
                "tab_size": settings.editor.tab_size,
                "use_tabs": settings.editor.use_tabs,
                "word_wrap": settings.editor.word_wrap,
                "show_line_numbers": settings.editor.show_line_numbers,
            },
            "custom_settings": settings.custom_settings,
            "version": settings.version,
            "created_at": settings.created_at,
            "updated_at": settings.updated_at,
        }
        await self.db.user_settings_snapshots.replace_one(
            {"user_id": settings.user_id},
            doc,
            upsert=True
        )
        logger.info(f"Created settings snapshot for user {settings.user_id}")

    async def get_settings_events(
            self,
            user_id: str,
            event_types: List[EventType],
            since: datetime | None = None,
            until: datetime | None = None,
            limit: int | None = None
    ) -> List[DomainSettingsEvent]:
        query = {
            "aggregate_id": f"user_settings_{user_id}",
            "event_type": {"$in": [str(et) for et in event_types]}
        }

        if since or until:
            timestamp_query: Dict[str, Any] = {}
            if since:
                timestamp_query["$gt"] = since
            if until:
                timestamp_query["$lte"] = until
            query["timestamp"] = timestamp_query

        cursor = self.db.events.find(query).sort("timestamp", ASCENDING)
        
        if limit:
            cursor = cursor.limit(limit)

        docs = await cursor.to_list(None)
        events: List[DomainSettingsEvent] = []
        for d in docs:
            et = d.get("event_type")
            try:
                et_parsed: EventType = EventType(et)
            except Exception:
                # Fallback to generic settings-updated when type is unknown
                et_parsed = EventType.USER_SETTINGS_UPDATED
            events.append(DomainSettingsEvent(
                event_type=et_parsed,
                timestamp=d.get("timestamp"),
                payload=d.get("payload", {}),
                correlation_id=d.get("correlation_id")
            ))
        return events

    async def count_events_since_snapshot(self, user_id: str) -> int:
        snapshot = await self.get_snapshot(user_id)
        
        if not snapshot:
            return await self.db.events.count_documents({
                "aggregate_id": f"user_settings_{user_id}"
            })

        return await self.db.events.count_documents({
            "aggregate_id": f"user_settings_{user_id}",
            "timestamp": {"$gt": snapshot.updated_at}
        })

    async def count_events_for_user(self, user_id: str) -> int:
        return await self.db.events.count_documents({
            "aggregate_id": f"user_settings_{user_id}"
        })
