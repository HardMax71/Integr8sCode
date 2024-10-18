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
    saved_script_in_db = await saved_script_service.create_saved_script(saved_script, current_user.id)
    return SavedScriptResponse(**saved_script_in_db.dict())

@router.get("/scripts", response_model=List[SavedScriptResponse])
@limiter.limit("20/minute")
async def list_saved_scripts(
    request: Request,
    current_user: UserInDB = Depends(security_service.get_current_user),
    saved_script_service: SavedScriptService = Depends(get_saved_script_service)
):
    scripts_in_db = await saved_script_service.list_saved_scripts(current_user.id)
    return [SavedScriptResponse(**script.dict()) for script in scripts_in_db]

@router.get("/scripts/{script_id}", response_model=SavedScriptResponse)
@limiter.limit("20/minute")
async def get_saved_script(
    request: Request,
    script_id: str,
    current_user: UserInDB = Depends(security_service.get_current_user),
    saved_script_service: SavedScriptService = Depends(get_saved_script_service)
):
    script_in_db = await saved_script_service.get_saved_script(script_id, current_user.id)
    if not script_in_db:
        raise HTTPException(status_code=404, detail="Script not found")
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
    script_in_db = await saved_script_service.get_saved_script(script_id, current_user.id)
    if not script_in_db:
        raise HTTPException(status_code=404, detail="Script not found")
    await saved_script_service.update_saved_script(script_id, current_user.id, script_update)
    updated_script = await saved_script_service.get_saved_script(script_id, current_user.id)
    return SavedScriptResponse(**updated_script.dict())

@router.delete("/scripts/{script_id}", status_code=204)
@limiter.limit("20/minute")
async def delete_saved_script(
    request: Request,
    script_id: str,
    current_user: UserInDB = Depends(security_service.get_current_user),
    saved_script_service: SavedScriptService = Depends(get_saved_script_service)
):
    script_in_db = await saved_script_service.get_saved_script(script_id, current_user.id)
    if not script_in_db:
        raise HTTPException(status_code=404, detail="Script not found")
    await saved_script_service.delete_saved_script(script_id, current_user.id)
    return
