from typing import List

from app.core.logging import logger
from app.core.security import security_service
from app.schemas.saved_script import SavedScriptCreateRequest, SavedScriptResponse, SavedScriptUpdate
from app.schemas.user import UserInDB
from app.services.saved_script_service import (
    SavedScriptService,
    get_saved_script_service,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/scripts", response_model=SavedScriptResponse)
@limiter.limit("20/minute")
async def create_saved_script(
        request: Request,
        saved_script: SavedScriptCreateRequest,
        current_user: UserInDB = Depends(security_service.get_current_user),
        saved_script_service: SavedScriptService = Depends(get_saved_script_service),
) -> SavedScriptResponse:
    logger.info(
        "Creating new saved script",
        extra={
            "user_id": str(current_user.id),
            "username": current_user.username,
            "script_name": saved_script.name,
            "script_length": len(saved_script.script),
            "client_ip": get_remote_address(request),
            "endpoint": "/scripts",
        },
    )

    try:
        # Type adaptation handled within service
        user_id = str(current_user.id) if current_user.id is not None else ""

        saved_script_in_db = await saved_script_service.create_saved_script(
            saved_script, user_id  # type: ignore
        )
        logger.info(
            "Successfully created saved script",
            extra={
                "script_id": str(saved_script_in_db.id),
                "user_id": str(current_user.id),
                "script_name": saved_script_in_db.name,
            },
        )
        return SavedScriptResponse(**saved_script_in_db.dict())
    except Exception as e:
        logger.error(
            "Failed to create saved script",
            extra={
                "user_id": str(current_user.id),
                "script_name": saved_script.name,
                "error_type": type(e).__name__,
                "error_detail": str(e),
            },
        )
        raise HTTPException(status_code=500, detail="Failed to create script") from e


@router.get("/scripts", response_model=List[SavedScriptResponse])
@limiter.limit("20/minute")
async def list_saved_scripts(
        request: Request,
        current_user: UserInDB = Depends(security_service.get_current_user),
        saved_script_service: SavedScriptService = Depends(get_saved_script_service),
) -> List[SavedScriptResponse]:
    logger.info(
        "Listing saved scripts",
        extra={
            "user_id": str(current_user.id),
            "username": current_user.username,
            "client_ip": get_remote_address(request),
            "endpoint": "/scripts",
        },
    )

    if not current_user.id:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        user_id = str(current_user.id)

        scripts_in_db = await saved_script_service.list_saved_scripts(user_id)  # type: ignore
        logger.info(
            "Successfully retrieved saved scripts",
            extra={"user_id": str(current_user.id), "script_count": len(scripts_in_db)},
        )
        return [SavedScriptResponse(**script.dict()) for script in scripts_in_db]
    except Exception as e:
        logger.error(
            "Failed to list saved scripts",
            extra={
                "user_id": str(current_user.id),
                "error_type": type(e).__name__,
                "error_detail": str(e),
            },
        )
        raise HTTPException(status_code=500, detail="Failed to list scripts") from e


@router.get("/scripts/{script_id}", response_model=SavedScriptResponse)
@limiter.limit("20/minute")
async def get_saved_script(
        request: Request,
        script_id: str,
        current_user: UserInDB = Depends(security_service.get_current_user),
        saved_script_service: SavedScriptService = Depends(get_saved_script_service),
) -> SavedScriptResponse:
    logger.info(
        "Retrieving saved script",
        extra={
            "user_id": str(current_user.id),
            "script_id": script_id,
            "client_ip": get_remote_address(request),
            "endpoint": f"/scripts/{script_id}",
        },
    )
    if not current_user.id:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = str(current_user.id)

    script_in_db = await saved_script_service.get_saved_script(
        script_id, user_id
    )
    if not script_in_db:
        logger.warning(
            "Script not found",
            extra={"user_id": str(current_user.id), "script_id": script_id},
        )
        raise HTTPException(status_code=404, detail="Script not found")

    logger.info(
        "Successfully retrieved script",
        extra={"script_id": script_id, "script_name": script_in_db.name},
    )
    return SavedScriptResponse(**script_in_db.dict())


@router.put("/scripts/{script_id}", response_model=SavedScriptResponse)
@limiter.limit("20/minute")
async def update_saved_script(
        request: Request,
        script_id: str,
        script_update: SavedScriptCreateRequest,
        current_user: UserInDB = Depends(security_service.get_current_user),
        saved_script_service: SavedScriptService = Depends(get_saved_script_service),
) -> SavedScriptResponse:
    logger.info(
        "Updating saved script",
        extra={
            "user_id": str(current_user.id),
            "script_id": script_id,
            "script_name": script_update.name,
            "script_length": len(script_update.script),
            "client_ip": get_remote_address(request),
            "endpoint": f"/scripts/{script_id}",
        },
    )

    if not current_user.id:
        raise HTTPException(status_code=404, detail="User not found")
    user_id = str(current_user.id)

    script_in_db = await saved_script_service.get_saved_script(
        script_id, user_id  # type: ignore
    )
    if not script_in_db:
        logger.warning(
            "Script not found for update",
            extra={"user_id": str(current_user.id), "script_id": script_id},
        )
        raise HTTPException(status_code=404, detail="Script not found")

    try:
        update_data = SavedScriptUpdate(
            name=script_update.name,
            script=script_update.script,
            description=script_update.description,
        )
        await saved_script_service.update_saved_script(
            script_id, user_id, update_data
        )
        updated_script = await saved_script_service.get_saved_script(
            script_id, user_id
        )
        if not updated_script:
            raise Exception("Failed to update saved script (Updated_script = None)")
        logger.info(
            "Successfully updated script",
            extra={"script_id": script_id, "script_name": updated_script.name},
        )
        return SavedScriptResponse(**updated_script.dict())
    except Exception as e:
        logger.error(
            "Failed to update script",
            extra={
                "script_id": script_id,
                "user_id": str(current_user.id),
                "error_type": type(e).__name__,
                "error_detail": str(e),
            },
        )
        raise HTTPException(status_code=500, detail="Failed to update script") from e


@router.delete("/scripts/{script_id}", status_code=204)
@limiter.limit("20/minute")
async def delete_saved_script(
        request: Request,
        script_id: str,
        current_user: UserInDB = Depends(security_service.get_current_user),
        saved_script_service: SavedScriptService = Depends(get_saved_script_service),
) -> None:
    logger.info(
        "Deleting saved script",
        extra={
            "user_id": str(current_user.id),
            "script_id": script_id,
            "client_ip": get_remote_address(request),
            "endpoint": f"/scripts/{script_id}",
        },
    )
    if not current_user.id:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = str(current_user.id)

    script_in_db = await saved_script_service.get_saved_script(
        script_id, user_id  # type: ignore
    )
    if not script_in_db:
        logger.warning(
            "Script not found for deletion",
            extra={"user_id": str(current_user.id), "script_id": script_id},
        )
        raise HTTPException(status_code=404, detail="Script not found")

    try:
        await saved_script_service.delete_saved_script(script_id, user_id)  # type: ignore
        logger.info(
            "Successfully deleted script",
            extra={"script_id": script_id, "user_id": str(current_user.id)},
        )
        return None
    except Exception as e:
        logger.error(
            "Failed to delete script",
            extra={
                "script_id": script_id,
                "user_id": str(current_user.id),
                "error_type": type(e).__name__,
                "error_detail": str(e),
            },
        )
        raise HTTPException(status_code=500, detail="Failed to delete script") from e
