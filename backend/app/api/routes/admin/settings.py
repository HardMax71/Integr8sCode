from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from app.api.dependencies import AuthService, require_admin_guard
from app.core.logging import logger
from app.core.service_dependencies import AdminSettingsRepositoryDep
from app.infrastructure.mappers.admin_mapper import SettingsMapper
from app.schemas_pydantic.admin_settings import SystemSettings

router = APIRouter(
    prefix="/admin/settings",
    tags=["admin", "settings"],
    route_class=DishkaRoute,
    dependencies=[Depends(require_admin_guard)]
)


@router.get("/", response_model=SystemSettings)
async def get_system_settings(
        repository: AdminSettingsRepositoryDep,

        request: Request, auth_service: FromDishka[AuthService],
) -> SystemSettings:
    current_user = await auth_service.require_admin(request)
    logger.info(
        "Admin retrieving system settings",
        extra={"admin_username": current_user.username}
    )

    try:
        domain_settings = await repository.get_system_settings()
        # Convert domain model to pydantic schema
        settings_mapper = SettingsMapper()
        return SystemSettings(**settings_mapper.system_settings_to_pydantic_dict(domain_settings))

    except Exception as e:
        logger.error(f"Failed to retrieve system settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve settings")


@router.put("/", response_model=SystemSettings)
async def update_system_settings(
        settings: SystemSettings,
        repository: AdminSettingsRepositoryDep,

        request: Request, auth_service: FromDishka[AuthService],
) -> SystemSettings:
    current_user = await auth_service.require_admin(request)
    # Validate settings completeness
    try:
        settings_dict = settings.model_dump()
        if not settings_dict:
            raise ValueError("Empty settings payload")
    except Exception as e:
        logger.warning(f"Invalid settings payload from {current_user.username}: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid settings payload")

    logger.info(
        "Admin updating system settings",
        extra={
            "admin_username": current_user.username,
            "settings": settings_dict
        }
    )

    # Validate and convert to domain model
    try:
        settings_mapper = SettingsMapper()
        domain_settings = settings_mapper.system_settings_from_pydantic(settings_dict)
    except (ValueError, ValidationError, KeyError) as e:
        logger.warning(
            f"Settings validation failed for {current_user.username}: {str(e)}",
            extra={"settings": settings_dict}
        )
        raise HTTPException(
            status_code=422,
            detail=f"Invalid settings: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error during settings validation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid settings format")

    # Perform the update
    try:
        updated_domain_settings = await repository.update_system_settings(
            settings=domain_settings,
            updated_by=current_user.username,
            user_id=current_user.user_id
        )

        logger.info("System settings updated successfully")
        # Convert back to pydantic schema for response
        settings_mapper = SettingsMapper()
        return SystemSettings(**settings_mapper.system_settings_to_pydantic_dict(updated_domain_settings))

    except Exception as e:
        logger.error(f"Failed to update system settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update settings")


@router.post("/reset", response_model=SystemSettings)
async def reset_system_settings(
        repository: AdminSettingsRepositoryDep,

        request: Request, auth_service: FromDishka[AuthService],
) -> SystemSettings:
    current_user = await auth_service.require_admin(request)
    logger.info(
        "Admin resetting system settings to defaults",
        extra={"admin_username": current_user.username}
    )

    try:
        reset_domain_settings = await repository.reset_system_settings(
            username=current_user.username,
            user_id=current_user.user_id
        )

        logger.info("System settings reset to defaults")
        settings_mapper = SettingsMapper()
        return SystemSettings(**settings_mapper.system_settings_to_pydantic_dict(reset_domain_settings))

    except Exception as e:
        logger.error(f"Failed to reset system settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reset settings")
