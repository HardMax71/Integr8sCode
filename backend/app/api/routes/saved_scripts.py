from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends

from app.api.dependencies import current_user
from app.domain.saved_script import DomainSavedScriptCreate, DomainSavedScriptUpdate
from app.domain.user import User
from app.schemas_pydantic.common import ErrorResponse
from app.schemas_pydantic.saved_script import (
    SavedScriptCreateRequest,
    SavedScriptListResponse,
    SavedScriptResponse,
    SavedScriptUpdate,
)
from app.services.saved_script_service import SavedScriptService

router = APIRouter(route_class=DishkaRoute, tags=["scripts"])


@router.post("/scripts", response_model=SavedScriptResponse)
async def create_saved_script(
    user: Annotated[User, Depends(current_user)],
    saved_script: SavedScriptCreateRequest,
    saved_script_service: FromDishka[SavedScriptService],
) -> SavedScriptResponse:
    """Save a new script to the user's collection."""
    create = DomainSavedScriptCreate.model_validate(saved_script)
    domain = await saved_script_service.create_saved_script(create, user.user_id)
    return SavedScriptResponse.model_validate(domain)


@router.get("/scripts", response_model=SavedScriptListResponse)
async def list_saved_scripts(
    user: Annotated[User, Depends(current_user)],
    saved_script_service: FromDishka[SavedScriptService],
) -> SavedScriptListResponse:
    """List all saved scripts for the authenticated user."""
    result = await saved_script_service.list_saved_scripts(user.user_id)
    return SavedScriptListResponse.model_validate(result)


@router.get(
    "/scripts/{script_id}",
    response_model=SavedScriptResponse,
    responses={404: {"model": ErrorResponse, "description": "Script not found"}},
)
async def get_saved_script(
    script_id: str,
    user: Annotated[User, Depends(current_user)],
    saved_script_service: FromDishka[SavedScriptService],
) -> SavedScriptResponse:
    """Get a saved script by ID."""
    domain = await saved_script_service.get_saved_script(script_id, user.user_id)
    return SavedScriptResponse.model_validate(domain)


@router.put(
    "/scripts/{script_id}",
    response_model=SavedScriptResponse,
    responses={404: {"model": ErrorResponse, "description": "Script not found"}},
)
async def update_saved_script(
    script_id: str,
    script_update: SavedScriptUpdate,
    user: Annotated[User, Depends(current_user)],
    saved_script_service: FromDishka[SavedScriptService],
) -> SavedScriptResponse:
    """Update an existing saved script."""
    update_data = DomainSavedScriptUpdate.model_validate(script_update)
    domain = await saved_script_service.update_saved_script(script_id, user.user_id, update_data)
    return SavedScriptResponse.model_validate(domain)


@router.delete(
    "/scripts/{script_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse, "description": "Script not found"}},
)
async def delete_saved_script(
    script_id: str,
    user: Annotated[User, Depends(current_user)],
    saved_script_service: FromDishka[SavedScriptService],
) -> None:
    """Delete a saved script."""
    await saved_script_service.delete_saved_script(script_id, user.user_id)
