from fastapi import APIRouter, Depends, HTTPException, Request
from typing import List
from app.core.security import security_service
from app.models.user import UserInDB
from app.schemas.saved_script import (
    SavedScriptCreateRequest,
    SavedScriptResponse
)
from app.services.saved_script_service import SavedScriptService, get_saved_script_service
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.logging import logger

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/scripts", response_model=SavedScriptResponse)
@limiter.limit("20/minute")
async def create_saved_script(
        request: Request,
        saved_script: SavedScriptCreateRequest,
        current_user: UserInDB = Depends(security_service.get_current_user),
        saved_script_service: SavedScriptService = Depends(get_saved_script_service)
):
    logger.info(
        "Creating new saved script",
        extra={
            "user_id": str(current_user.id),
            "username": current_user.username,
            "script_name": saved_script.name,
            "script_length": len(saved_script.content),
            "python_version": saved_script.python_version,
            "client_ip": get_remote_address(request),
            "endpoint": "/scripts"
        }
    )

    try:
        saved_script_in_db = await saved_script_service.create_saved_script(saved_script, current_user.id)
        logger.info(
            "Successfully created saved script",
            extra={
                "script_id": str(saved_script_in_db.id),
                "user_id": str(current_user.id),
                "script_name": saved_script_in_db.name
            }
        )
        return SavedScriptResponse(**saved_script_in_db.dict())
    except Exception as e:
        logger.error(
            "Failed to create saved script",
            extra={
                "user_id": str(current_user.id),
                "script_name": saved_script.name,
                "error_type": type(e).__name__,
                "error_detail": str(e)
            }
        )
        raise HTTPException(status_code=500, detail="Failed to create script")


@router.get("/scripts", response_model=List[SavedScriptResponse])
@limiter.limit("20/minute")
async def list_saved_scripts(
        request: Request,
        current_user: UserInDB = Depends(security_service.get_current_user),
        saved_script_service: SavedScriptService = Depends(get_saved_script_service)
):
    logger.info(
        "Listing saved scripts",
        extra={
            "user_id": str(current_user.id),
            "username": current_user.username,
            "client_ip": get_remote_address(request),
            "endpoint": "/scripts"
        }
    )

    try:
        scripts_in_db = await saved_script_service.list_saved_scripts(current_user.id)
        logger.info(
            "Successfully retrieved saved scripts",
            extra={
                "user_id": str(current_user.id),
                "script_count": len(scripts_in_db)
            }
        )
        return [SavedScriptResponse(**script.dict()) for script in scripts_in_db]
    except Exception as e:
        logger.error(
            "Failed to list saved scripts",
            extra={
                "user_id": str(current_user.id),
                "error_type": type(e).__name__,
                "error_detail": str(e)
            }
        )
        raise HTTPException(status_code=500, detail="Failed to list scripts")


@router.get("/scripts/{script_id}", response_model=SavedScriptResponse)
@limiter.limit("20/minute")
async def get_saved_script(
        request: Request,
        script_id: str,
        current_user: UserInDB = Depends(security_service.get_current_user),
        saved_script_service: SavedScriptService = Depends(get_saved_script_service)
):
    logger.info(
        "Retrieving saved script",
        extra={
            "user_id": str(current_user.id),
            "script_id": script_id,
            "client_ip": get_remote_address(request),
            "endpoint": f"/scripts/{script_id}"
        }
    )

    script_in_db = await saved_script_service.get_saved_script(script_id, current_user.id)
    if not script_in_db:
        logger.warning(
            "Script not found",
            extra={
                "user_id": str(current_user.id),
                "script_id": script_id
            }
        )
        raise HTTPException(status_code=404, detail="Script not found")

    logger.info(
        "Successfully retrieved script",
        extra={
            "script_id": script_id,
            "script_name": script_in_db.name
        }
    )
    return SavedScriptResponse(**script_in_db.dict())


@router.put("/scripts/{script_id}", response_model=SavedScriptResponse)
@limiter.limit("20/minute")
async def update_saved_script(
        request: Request,
        script_id: str,
        script_update: SavedScriptCreateRequest,
        current_user: UserInDB = Depends(security_service.get_current_user),
        saved_script_service: SavedScriptService = Depends(get_saved_script_service)
):
    logger.info(
        "Updating saved script",
        extra={
            "user_id": str(current_user.id),
            "script_id": script_id,
            "script_name": script_update.name,
            "script_length": len(script_update.content),
            "client_ip": get_remote_address(request),
            "endpoint": f"/scripts/{script_id}"
        }
    )

    script_in_db = await saved_script_service.get_saved_script(script_id, current_user.id)
    if not script_in_db:
        logger.warning(
            "Script not found for update",
            extra={
                "user_id": str(current_user.id),
                "script_id": script_id
            }
        )
        raise HTTPException(status_code=404, detail="Script not found")

    try:
        await saved_script_service.update_saved_script(script_id, current_user.id, script_update)
        updated_script = await saved_script_service.get_saved_script(script_id, current_user.id)
        logger.info(
            "Successfully updated script",
            extra={
                "script_id": script_id,
                "script_name": updated_script.name
            }
        )
        return SavedScriptResponse(**updated_script.dict())
    except Exception as e:
        logger.error(
            "Failed to update script",
            extra={
                "script_id": script_id,
                "user_id": str(current_user.id),
                "error_type": type(e).__name__,
                "error_detail": str(e)
            }
        )
        raise HTTPException(status_code=500, detail="Failed to update script")


@router.delete("/scripts/{script_id}", status_code=204)
@limiter.limit("20/minute")
async def delete_saved_script(
        request: Request,
        script_id: str,
        current_user: UserInDB = Depends(security_service.get_current_user),
        saved_script_service: SavedScriptService = Depends(get_saved_script_service)
):
    logger.info(
        "Deleting saved script",
        extra={
            "user_id": str(current_user.id),
            "script_id": script_id,
            "client_ip": get_remote_address(request),
            "endpoint": f"/scripts/{script_id}"
        }
    )

    script_in_db = await saved_script_service.get_saved_script(script_id, current_user.id)
    if not script_in_db:
        logger.warning(
            "Script not found for deletion",
            extra={
                "user_id": str(current_user.id),
                "script_id": script_id
            }
        )
        raise HTTPException(status_code=404, detail="Script not found")

    try:
        await saved_script_service.delete_saved_script(script_id, current_user.id)
        logger.info(
            "Successfully deleted script",
            extra={
                "script_id": script_id,
                "user_id": str(current_user.id)
            }
        )
        return
    except Exception as e:
        logger.error(
            "Failed to delete script",
            extra={
                "script_id": script_id,
                "user_id": str(current_user.id),
                "error_type": type(e).__name__,
                "error_detail": str(e)
            }
        )
        raise HTTPException(status_code=500, detail="Failed to delete script")