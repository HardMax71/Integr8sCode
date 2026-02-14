from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends

from app.api.dependencies import admin_user
from app.domain.admin import SystemSettings
from app.domain.user import User
from app.schemas_pydantic.admin_settings import SystemSettingsSchema
from app.schemas_pydantic.common import ErrorResponse
from app.services.admin import AdminSettingsService

router = APIRouter(
    prefix="/admin/settings", tags=["admin", "settings"], route_class=DishkaRoute, dependencies=[Depends(admin_user)]
)


@router.get(
    "/",
    response_model=SystemSettingsSchema,
    responses={500: {"model": ErrorResponse, "description": "Failed to load system settings"}},
)
async def get_system_settings(
    admin: Annotated[User, Depends(admin_user)],
    service: FromDishka[AdminSettingsService],
) -> SystemSettingsSchema:
    """Get the current system-wide settings."""
    result = await service.get_system_settings(admin.user_id)
    return SystemSettingsSchema.model_validate(result, from_attributes=True)


@router.put(
    "/",
    response_model=SystemSettingsSchema,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid settings values"},
        422: {"model": ErrorResponse, "description": "Settings validation failed"},
        500: {"model": ErrorResponse, "description": "Failed to save settings"},
    },
)
async def update_system_settings(
    admin: Annotated[User, Depends(admin_user)],
    settings: SystemSettingsSchema,
    service: FromDishka[AdminSettingsService],
) -> SystemSettingsSchema:
    """Replace system-wide settings."""
    result = await service.update_system_settings(SystemSettings(**settings.model_dump()), admin.user_id)
    return SystemSettingsSchema.model_validate(result, from_attributes=True)


@router.post(
    "/reset",
    response_model=SystemSettingsSchema,
    responses={500: {"model": ErrorResponse, "description": "Failed to reset settings"}},
)
async def reset_system_settings(
    admin: Annotated[User, Depends(admin_user)],
    service: FromDishka[AdminSettingsService],
) -> SystemSettingsSchema:
    """Reset system-wide settings to defaults."""
    result = await service.reset_system_settings(admin.user_id)
    return SystemSettingsSchema.model_validate(result, from_attributes=True)
