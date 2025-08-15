from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import require_admin
from app.core.logging import logger
from app.core.service_dependencies import AdminSettingsRepositoryDep
from app.domain.admin.settings_models import SystemSettings as DomainSystemSettings
from app.schemas_pydantic.admin_settings import SystemSettings
from app.schemas_pydantic.user import UserResponse

router = APIRouter(prefix="/admin/settings", tags=["admin", "settings"])


@router.get("/", response_model=SystemSettings)
async def get_system_settings(
        repository: AdminSettingsRepositoryDep,
        current_user: UserResponse = Depends(require_admin),
) -> SystemSettings:
    logger.info(
        "Admin retrieving system settings",
        extra={"admin_username": current_user.username}
    )

    try:
        domain_settings = await repository.get_system_settings()
        # Convert domain model to pydantic schema
        return SystemSettings(**domain_settings.to_pydantic_dict())

    except Exception as e:
        logger.error(f"Failed to retrieve system settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve settings")


@router.put("/", response_model=SystemSettings)
async def update_system_settings(
        settings: SystemSettings,
        repository: AdminSettingsRepositoryDep,
        current_user: UserResponse = Depends(require_admin),
) -> SystemSettings:
    logger.info(
        "Admin updating system settings",
        extra={
            "admin_username": current_user.username,
            "settings": settings.model_dump()
        }
    )

    try:
        # Convert pydantic schema to domain model
        domain_settings = DomainSystemSettings.from_pydantic(settings.model_dump())
        
        updated_domain_settings = await repository.update_system_settings(
            settings=domain_settings,
            updated_by=current_user.username,
            user_id=current_user.user_id
        )

        logger.info("System settings updated successfully")
        # Convert back to pydantic schema for response
        return SystemSettings(**updated_domain_settings.to_pydantic_dict())

    except Exception as e:
        logger.error(f"Failed to update system settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update settings")


@router.post("/reset", response_model=SystemSettings)
async def reset_system_settings(
        repository: AdminSettingsRepositoryDep,
        current_user: UserResponse = Depends(require_admin),
) -> SystemSettings:
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
        # Convert domain model to pydantic schema
        return SystemSettings(**reset_domain_settings.to_pydantic_dict())

    except Exception as e:
        logger.error(f"Failed to reset system settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reset settings")
