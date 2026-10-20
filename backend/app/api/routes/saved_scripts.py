from typing import Annotated, Any

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError
from pydantic import TypeAdapter, ValidationError

from app.api.dependencies import current_user
from app.domain.saved_script import SavedScriptChanges
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

_RUNTIME_NOT_OFFERED: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "Language version is not offered, or invalid request body",
}

_saved_script_changes = TypeAdapter(SavedScriptChanges)


@router.post("/scripts", response_model=SavedScriptResponse, responses={422: _RUNTIME_NOT_OFFERED})
async def create_saved_script(
    user: Annotated[User, Depends(current_user)],
    saved_script: SavedScriptCreateRequest,
    saved_script_service: FromDishka[SavedScriptService],
) -> SavedScriptResponse:
    """Save a new script to the user's collection."""
    script = await saved_script_service.create_saved_script(
        user_id=user.user_id,
        name=saved_script.name,
        script=saved_script.script,
        lang=saved_script.lang,
        lang_version=saved_script.lang_version,
        description=saved_script.description,
    )
    return SavedScriptResponse.model_validate(script)


@router.get("/scripts", response_model=SavedScriptListResponse)
async def list_saved_scripts(
    user: Annotated[User, Depends(current_user)],
    saved_script_service: FromDishka[SavedScriptService],
) -> SavedScriptListResponse:
    """List all saved scripts for the authenticated user."""
    scripts = await saved_script_service.list_saved_scripts(user.user_id)
    return SavedScriptListResponse(scripts=[SavedScriptResponse.model_validate(script) for script in scripts])


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
    responses={404: {"model": ErrorResponse, "description": "Script not found"}, 422: _RUNTIME_NOT_OFFERED},
)
async def update_saved_script(
    script_id: str,
    script_update: SavedScriptUpdate,
    user: Annotated[User, Depends(current_user)],
    saved_script_service: FromDishka[SavedScriptService],
) -> SavedScriptResponse:
    """Update an existing saved script."""
    try:
        changes = _saved_script_changes.validate_python(script_update.model_dump(exclude_unset=True))
    except ValidationError as e:
        raise RequestValidationError(e.errors()) from e
    script = await saved_script_service.update_saved_script(script_id, user.user_id, changes)
    return SavedScriptResponse.model_validate(script)


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
