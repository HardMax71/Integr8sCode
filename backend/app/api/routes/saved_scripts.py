from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Request

from app.domain.saved_script import DomainSavedScriptCreate, DomainSavedScriptUpdate
from app.schemas_pydantic.common import ErrorResponse
from app.schemas_pydantic.saved_script import (
    SavedScriptCreateRequest,
    SavedScriptResponse,
    SavedScriptUpdate,
)
from app.services.auth_service import AuthService
from app.services.saved_script_service import SavedScriptService

router = APIRouter(route_class=DishkaRoute, tags=["scripts"])


@router.post("/scripts", response_model=SavedScriptResponse)
async def create_saved_script(
    request: Request,
    saved_script: SavedScriptCreateRequest,
    saved_script_service: FromDishka[SavedScriptService],
    auth_service: FromDishka[AuthService],
) -> SavedScriptResponse:
    """Save a new script to the user's collection."""
    current_user = await auth_service.get_current_user(request)
    create = DomainSavedScriptCreate(**saved_script.model_dump())
    domain = await saved_script_service.create_saved_script(create, current_user.user_id)
    return SavedScriptResponse.model_validate(domain)


@router.get("/scripts", response_model=list[SavedScriptResponse])
async def list_saved_scripts(
    request: Request,
    saved_script_service: FromDishka[SavedScriptService],
    auth_service: FromDishka[AuthService],
) -> list[SavedScriptResponse]:
    """List all saved scripts for the authenticated user."""
    current_user = await auth_service.get_current_user(request)
    items = await saved_script_service.list_saved_scripts(current_user.user_id)
    return [SavedScriptResponse.model_validate(item) for item in items]


@router.get("/scripts/{script_id}", response_model=SavedScriptResponse, responses={404: {"model": ErrorResponse}})
async def get_saved_script(
    request: Request,
    script_id: str,
    saved_script_service: FromDishka[SavedScriptService],
    auth_service: FromDishka[AuthService],
) -> SavedScriptResponse:
    """Get a saved script by ID."""
    current_user = await auth_service.get_current_user(request)

    domain = await saved_script_service.get_saved_script(script_id, current_user.user_id)
    return SavedScriptResponse.model_validate(domain)


@router.put("/scripts/{script_id}", response_model=SavedScriptResponse, responses={404: {"model": ErrorResponse}})
async def update_saved_script(
    request: Request,
    script_id: str,
    script_update: SavedScriptUpdate,
    saved_script_service: FromDishka[SavedScriptService],
    auth_service: FromDishka[AuthService],
) -> SavedScriptResponse:
    """Update an existing saved script."""
    current_user = await auth_service.get_current_user(request)

    update_data = DomainSavedScriptUpdate(**script_update.model_dump())
    domain = await saved_script_service.update_saved_script(script_id, current_user.user_id, update_data)
    return SavedScriptResponse.model_validate(domain)


@router.delete("/scripts/{script_id}", status_code=204, responses={404: {"model": ErrorResponse}})
async def delete_saved_script(
    request: Request,
    script_id: str,
    saved_script_service: FromDishka[SavedScriptService],
    auth_service: FromDishka[AuthService],
) -> None:
    """Delete a saved script."""
    current_user = await auth_service.get_current_user(request)

    await saved_script_service.delete_saved_script(script_id, current_user.user_id)
    return None
