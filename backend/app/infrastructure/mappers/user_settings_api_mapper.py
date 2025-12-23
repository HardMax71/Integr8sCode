from __future__ import annotations

from typing import List

from app.domain.user.settings_models import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainSettingsHistoryEntry,
    DomainUserSettings,
    DomainUserSettingsUpdate,
)
from app.schemas_pydantic.user_settings import (
    EditorSettings,
    NotificationSettings,
    SettingsHistoryEntry,
    SettingsHistoryResponse,
    UserSettings,
    UserSettingsUpdate,
)


class UserSettingsApiMapper:
    @staticmethod
    def to_domain_update(upd: UserSettingsUpdate) -> DomainUserSettingsUpdate:
        notifications = (
            UserSettingsApiMapper._to_domain_notifications(upd.notifications) if upd.notifications is not None else None
        )
        return DomainUserSettingsUpdate(
            theme=upd.theme,
            timezone=upd.timezone,
            date_format=upd.date_format,
            time_format=upd.time_format,
            notifications=notifications,
            editor=UserSettingsApiMapper._to_domain_editor(upd.editor) if upd.editor is not None else None,
            custom_settings=upd.custom_settings,
        )

    @staticmethod
    def _to_domain_notifications(n: NotificationSettings) -> DomainNotificationSettings:
        return DomainNotificationSettings(
            execution_completed=n.execution_completed,
            execution_failed=n.execution_failed,
            system_updates=n.system_updates,
            security_alerts=n.security_alerts,
            channels=list(n.channels) if n.channels is not None else [],
        )

    @staticmethod
    def _to_domain_editor(e: EditorSettings) -> DomainEditorSettings:
        return DomainEditorSettings(
            theme=e.theme,
            font_size=e.font_size,
            tab_size=e.tab_size,
            use_tabs=e.use_tabs,
            word_wrap=e.word_wrap,
            show_line_numbers=e.show_line_numbers,
        )

    @staticmethod
    def to_api_settings(s: DomainUserSettings) -> UserSettings:
        return UserSettings(
            user_id=s.user_id,
            theme=s.theme,
            timezone=s.timezone,
            date_format=s.date_format,
            time_format=s.time_format,
            notifications=NotificationSettings(
                execution_completed=s.notifications.execution_completed,
                execution_failed=s.notifications.execution_failed,
                system_updates=s.notifications.system_updates,
                security_alerts=s.notifications.security_alerts,
                channels=s.notifications.channels,
            ),
            editor=EditorSettings(
                theme=s.editor.theme,
                font_size=s.editor.font_size,
                tab_size=s.editor.tab_size,
                use_tabs=s.editor.use_tabs,
                word_wrap=s.editor.word_wrap,
                show_line_numbers=s.editor.show_line_numbers,
            ),
            custom_settings=s.custom_settings,
            version=s.version,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )

    @staticmethod
    def history_to_api(items: List[DomainSettingsHistoryEntry]) -> SettingsHistoryResponse:
        entries = [
            SettingsHistoryEntry(
                timestamp=i.timestamp,
                event_type=i.event_type,
                field=i.field,
                old_value=i.old_value,
                new_value=i.new_value,
                reason=i.reason,
                correlation_id=i.correlation_id,
            )
            for i in items
        ]
        return SettingsHistoryResponse(history=entries, total=len(entries))
