from datetime import datetime, timezone
from typing import Any

from app.domain.enums import Theme
from app.domain.enums.events import EventType
from app.domain.enums.notification import NotificationChannel
from app.domain.user.settings_models import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainSettingsEvent,
    DomainUserSettings,
)


class UserSettingsMapper:
    """Map user settings snapshot/event documents to domain and back."""

    @staticmethod
    def from_snapshot_document(doc: dict[str, Any]) -> DomainUserSettings:
        notifications = doc.get("notifications", {})
        editor = doc.get("editor", {})
        theme = Theme(doc.get("theme", Theme.AUTO))

        # Coerce channels to NotificationChannel list
        channels_raw = notifications.get("channels", [])
        channels: list[NotificationChannel] = [NotificationChannel(c) for c in channels_raw]

        return DomainUserSettings(
            user_id=str(doc.get("user_id")),
            theme=theme,
            timezone=doc.get("timezone", "UTC"),
            date_format=doc.get("date_format", "YYYY-MM-DD"),
            time_format=doc.get("time_format", "24h"),
            notifications=DomainNotificationSettings(
                execution_completed=notifications.get("execution_completed", True),
                execution_failed=notifications.get("execution_failed", True),
                system_updates=notifications.get("system_updates", True),
                security_alerts=notifications.get("security_alerts", True),
                channels=channels,
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

    @staticmethod
    def to_snapshot_document(settings: DomainUserSettings) -> dict[str, Any]:
        return {
            "user_id": settings.user_id,
            "theme": str(settings.theme),
            "timezone": settings.timezone,
            "date_format": settings.date_format,
            "time_format": settings.time_format,
            "notifications": {
                "execution_completed": settings.notifications.execution_completed,
                "execution_failed": settings.notifications.execution_failed,
                "system_updates": settings.notifications.system_updates,
                "security_alerts": settings.notifications.security_alerts,
                "channels": [str(c) for c in settings.notifications.channels],
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

    @staticmethod
    def event_from_mongo_document(doc: dict[str, Any]) -> DomainSettingsEvent:
        et_parsed: EventType = EventType(str(doc.get("event_type")))

        return DomainSettingsEvent(
            event_type=et_parsed,
            timestamp=doc.get("timestamp"),  # type: ignore[arg-type]
            payload=doc.get("payload", {}),
            correlation_id=(doc.get("metadata", {}) or {}).get("correlation_id"),
        )
