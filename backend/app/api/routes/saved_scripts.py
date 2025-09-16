from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Request

from app.infrastructure.mappers import SavedScriptApiMapper
from app.schemas_pydantic.saved_script import (
    SavedScriptCreateRequest,
    SavedScriptResponse,
)
from app.services.auth_service import AuthService
from app.services.saved_script_service import SavedScriptService

router = APIRouter(route_class=DishkaRoute)


@router.post("/scripts", response_model=SavedScriptResponse)
async def create_saved_script(
        request: Request,
        saved_script: SavedScriptCreateRequest,
        saved_script_service: FromDishka[SavedScriptService],
        auth_service: FromDishka[AuthService],
) -> SavedScriptResponse:
    current_user = await auth_service.get_current_user(request)
    create = SavedScriptApiMapper.request_to_create(saved_script)
    domain = await saved_script_service.create_saved_script(
        create,
        current_user.user_id
    )
    return SavedScriptApiMapper.to_response(domain)


@router.get("/scripts", response_model=list[SavedScriptResponse])
async def list_saved_scripts(
        request: Request,
        saved_script_service: FromDishka[SavedScriptService],
        auth_service: FromDishka[AuthService],
) -> list[SavedScriptResponse]:
    current_user = await auth_service.get_current_user(request)
    items = await saved_script_service.list_saved_scripts(current_user.user_id)
    return SavedScriptApiMapper.list_to_response(items)


@router.get("/scripts/{script_id}", response_model=SavedScriptResponse)
async def get_saved_script(
        request: Request,
        script_id: str,
        saved_script_service: FromDishka[SavedScriptService],
        auth_service: FromDishka[AuthService],
) -> SavedScriptResponse:
    current_user = await auth_service.get_current_user(request)

    domain = await saved_script_service.get_saved_script(
        script_id,
        current_user.user_id
    )
    return SavedScriptApiMapper.to_response(domain)


@router.put("/scripts/{script_id}", response_model=SavedScriptResponse)
async def update_saved_script(
        request: Request,
        script_id: str,
        script_update: SavedScriptCreateRequest,
        saved_script_service: FromDishka[SavedScriptService],
        auth_service: FromDishka[AuthService],
) -> SavedScriptResponse:
    current_user = await auth_service.get_current_user(request)

    update_data = SavedScriptApiMapper.request_to_update(script_update)
    domain = await saved_script_service.update_saved_script(
        script_id,
        current_user.user_id,
        update_data
    )
    return SavedScriptApiMapper.to_response(domain)


@router.delete("/scripts/{script_id}", status_code=204)
async def delete_saved_script(
        request: Request,
        script_id: str,
        saved_script_service: FromDishka[SavedScriptService],
        auth_service: FromDishka[AuthService],
) -> None:
    current_user = await auth_service.get_current_user(request)

    await saved_script_service.delete_saved_script(
        script_id,
        current_user.user_id
    )
    return None
