from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query

from app.api.dependencies import current_user
from app.domain.user import User
from app.domain.user.settings_models import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainUserSettingsUpdate,
)
from app.schemas_pydantic.user_settings import (
    EditorSettings,
    NotificationSettings,
    RestoreSettingsRequest,
    SettingsHistoryEntry,
    SettingsHistoryResponse,
    ThemeUpdateRequest,
    UserSettings,
    UserSettingsUpdate,
)
from app.services.user_settings_service import UserSettingsService

router = APIRouter(prefix="/user/settings", tags=["user-settings"], route_class=DishkaRoute)


@router.get("/", response_model=UserSettings)
async def get_user_settings(
    current_user: Annotated[User, Depends(current_user)],
    settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    """Get the authenticated user's settings."""
    domain = await settings_service.get_user_settings(current_user.user_id)
    return UserSettings.model_validate(domain)


@router.put("/", response_model=UserSettings)
async def update_user_settings(
    current_user: Annotated[User, Depends(current_user)],
    updates: UserSettingsUpdate,
    settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    """Update the authenticated user's settings."""
    domain_updates = DomainUserSettingsUpdate(
        theme=updates.theme,
        timezone=updates.timezone,
        date_format=updates.date_format,
        time_format=updates.time_format,
        notifications=(
            DomainNotificationSettings(**updates.notifications.model_dump()) if updates.notifications else None
        ),
        editor=DomainEditorSettings(**updates.editor.model_dump()) if updates.editor else None,
        custom_settings=updates.custom_settings,
    )
    domain = await settings_service.update_user_settings(current_user.user_id, domain_updates)
    return UserSettings.model_validate(domain)


@router.put("/theme", response_model=UserSettings)
async def update_theme(
    current_user: Annotated[User, Depends(current_user)],
    update_request: ThemeUpdateRequest,
    settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    """Update the user's theme preference."""
    domain = await settings_service.update_theme(current_user.user_id, update_request.theme)
    return UserSettings.model_validate(domain)


@router.put("/notifications", response_model=UserSettings)
async def update_notification_settings(
    current_user: Annotated[User, Depends(current_user)],
    notifications: NotificationSettings,
    settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    """Update notification preferences."""
    domain = await settings_service.update_notification_settings(
        current_user.user_id,
        DomainNotificationSettings(**notifications.model_dump()),
    )
    return UserSettings.model_validate(domain)


@router.put("/editor", response_model=UserSettings)
async def update_editor_settings(
    current_user: Annotated[User, Depends(current_user)],
    editor: EditorSettings,
    settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    """Update code editor preferences."""
    domain = await settings_service.update_editor_settings(
        current_user.user_id,
        DomainEditorSettings(**editor.model_dump()),
    )
    return UserSettings.model_validate(domain)


@router.get("/history", response_model=SettingsHistoryResponse)
async def get_settings_history(
    current_user: Annotated[User, Depends(current_user)],
    settings_service: FromDishka[UserSettingsService],
    limit: Annotated[int, Query(ge=1, le=200, description="Maximum number of history entries")] = 50,
) -> SettingsHistoryResponse:
    """Get the change history for the user's settings."""
    history = await settings_service.get_settings_history(current_user.user_id, limit=limit)
    entries = [SettingsHistoryEntry.model_validate(entry) for entry in history]
    return SettingsHistoryResponse(history=entries, limit=limit)


@router.post("/restore", response_model=UserSettings)
async def restore_settings(
    current_user: Annotated[User, Depends(current_user)],
    restore_request: RestoreSettingsRequest,
    settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    """Restore settings to a previous point in time."""
    domain = await settings_service.restore_settings_to_point(current_user.user_id, restore_request.timestamp)
    return UserSettings.model_validate(domain)


@router.put("/custom/{key}")
async def update_custom_setting(
    current_user: Annotated[User, Depends(current_user)],
    key: str,
    value: dict[str, object],
    settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    """Set or update a single custom setting by key."""
    domain = await settings_service.update_custom_setting(current_user.user_id, key, value)
    return UserSettings.model_validate(domain)
