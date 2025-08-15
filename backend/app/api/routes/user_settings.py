from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_current_user
from app.core.logging import logger
from app.core.service_dependencies import UserSettingsServiceDep
from app.schemas_pydantic.user import User
from app.schemas_pydantic.user_settings import (
    EditorSettings,
    NotificationSettings,
    RestoreSettingsRequest,
    SettingsHistoryResponse,
    ThemeUpdateRequest,
    UserSettings,
    UserSettingsUpdate,
)

router = APIRouter(prefix="/user/settings", tags=["user-settings"])


@router.get("/", response_model=UserSettings)
async def get_user_settings(
        settings_service: UserSettingsServiceDep,
        current_user: User = Depends(get_current_user)
) -> UserSettings:
    try:
        return await settings_service.get_user_settings(current_user.user_id)
    except Exception as e:
        logger.error(f"Error getting user settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to get settings") from e


@router.put("/", response_model=UserSettings)
async def update_user_settings(
        updates: UserSettingsUpdate,
        settings_service: UserSettingsServiceDep,
        current_user: User = Depends(get_current_user)
) -> UserSettings:
    try:
        return await settings_service.update_user_settings(current_user, updates)
    except Exception as e:
        logger.error(f"Error updating user settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to update settings") from e


@router.put("/theme", response_model=UserSettings)
async def update_theme(
        request: ThemeUpdateRequest,
        settings_service: UserSettingsServiceDep,
        current_user: User = Depends(get_current_user)
) -> UserSettings:
    try:
        return await settings_service.update_theme(current_user, request.theme)
    except Exception as e:
        logger.error(f"Error updating theme: {e}")
        raise HTTPException(status_code=500, detail="Failed to update theme") from e


@router.put("/notifications", response_model=UserSettings)
async def update_notification_settings(
        notifications: NotificationSettings,
        settings_service: UserSettingsServiceDep,
        current_user: User = Depends(get_current_user),
) -> UserSettings:
    try:
        return await settings_service.update_notification_settings(current_user, notifications)
    except Exception as e:
        logger.error(f"Error updating notification settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to update notifications") from e


@router.put("/editor", response_model=UserSettings)
async def update_editor_settings(
        editor: EditorSettings,
        settings_service: UserSettingsServiceDep,
        current_user: User = Depends(get_current_user)
) -> UserSettings:
    try:
        return await settings_service.update_editor_settings(current_user, editor)
    except Exception as e:
        logger.error(f"Error updating editor settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to update editor settings") from e


@router.get("/history", response_model=SettingsHistoryResponse)
async def get_settings_history(
        settings_service: UserSettingsServiceDep,
        limit: int = 50,
        current_user: User = Depends(get_current_user)
) -> SettingsHistoryResponse:
    try:
        history = await settings_service.get_settings_history(current_user.user_id, limit=limit)
        return SettingsHistoryResponse(history=history, total=len(history))
    except Exception as e:
        logger.error(f"Error getting settings history: {e}")
        raise HTTPException(status_code=500, detail="Failed to get history") from e


@router.post("/restore", response_model=UserSettings)
async def restore_settings(
        request: RestoreSettingsRequest,
        settings_service: UserSettingsServiceDep,
        current_user: User = Depends(get_current_user)
) -> UserSettings:
    try:
        return await settings_service.restore_settings_to_point(current_user, request.timestamp)
    except Exception as e:
        logger.error(f"Error restoring settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to restore settings") from e


@router.put("/custom/{key}")
async def update_custom_setting(
        key: str,
        value: dict[str, object],
        settings_service: UserSettingsServiceDep,
        current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        settings = await settings_service.update_custom_setting(current_user, key, value)
        return {"key": key, "value": settings.custom_settings.get(key)}
    except Exception as e:
        logger.error(f"Error updating custom setting: {e}")
        raise HTTPException(status_code=500, detail="Failed to update custom setting") from e
