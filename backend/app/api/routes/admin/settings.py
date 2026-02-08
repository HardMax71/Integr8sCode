from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends

from app.api.dependencies import admin_user
from app.domain.admin import SystemSettings as DomainSystemSettings
from app.domain.user import User
from app.schemas_pydantic.admin_settings import SystemSettings
from app.schemas_pydantic.common import ErrorResponse
from app.services.admin import AdminSettingsService

router = APIRouter(
    prefix="/admin/settings", tags=["admin", "settings"], route_class=DishkaRoute, dependencies=[Depends(admin_user)]
)


@router.get(
    "/",
    response_model=SystemSettings,
    responses={500: {"model": ErrorResponse, "description": "Failed to load system settings"}},
)
async def get_system_settings(
    admin: Annotated[User, Depends(admin_user)],
    service: FromDishka[AdminSettingsService],
) -> SystemSettings:
    """Get the current system-wide settings."""
    domain_settings = await service.get_system_settings(admin.username)
    return SystemSettings.model_validate(domain_settings, from_attributes=True)


@router.put(
    "/",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid settings values"},
        422: {"model": ErrorResponse, "description": "Settings validation failed"},
        500: {"model": ErrorResponse, "description": "Failed to save settings"},
    },
)
async def update_system_settings(
    admin: Annotated[User, Depends(admin_user)],
    settings: SystemSettings,
    service: FromDishka[AdminSettingsService],
) -> SystemSettings:
    """Replace system-wide settings."""
    domain_settings = DomainSystemSettings(**settings.model_dump())
    updated = await service.update_system_settings(
        domain_settings,
        updated_by=admin.username,
        user_id=admin.user_id,
    )
    return SystemSettings.model_validate(updated, from_attributes=True)


@router.post(
    "/reset",
    response_model=SystemSettings,
    responses={500: {"model": ErrorResponse, "description": "Failed to reset settings"}},
)
async def reset_system_settings(
    admin: Annotated[User, Depends(admin_user)],
    service: FromDishka[AdminSettingsService],
) -> SystemSettings:
    """Reset system-wide settings to defaults."""
    reset = await service.reset_system_settings(admin.username, admin.user_id)
    return SystemSettings.model_validate(reset, from_attributes=True)
