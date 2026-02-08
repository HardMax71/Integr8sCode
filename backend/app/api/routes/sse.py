from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.schemas_pydantic.notification import NotificationResponse
from app.schemas_pydantic.sse import SSEExecutionEventData
from app.services.auth_service import AuthService
from app.services.sse import SSEService

router = APIRouter(prefix="/events", tags=["sse"], route_class=DishkaRoute)


@router.get("/notifications/stream", responses={200: {"model": NotificationResponse}})
async def notification_stream(
    request: Request,
    sse_service: FromDishka[SSEService],
    auth_service: FromDishka[AuthService],
) -> EventSourceResponse:
    """Stream notifications for authenticated user."""
    current_user = await auth_service.get_current_user(request)

    return EventSourceResponse(
        sse_service.create_notification_stream(user_id=current_user.user_id),
        ping=30,
    )


@router.get("/executions/{execution_id}", responses={200: {"model": SSEExecutionEventData}})
async def execution_events(
    execution_id: str, request: Request, sse_service: FromDishka[SSEService], auth_service: FromDishka[AuthService]
) -> EventSourceResponse:
    """Stream events for specific execution."""
    current_user = await auth_service.get_current_user(request)

    return EventSourceResponse(
        sse_service.create_execution_stream(execution_id=execution_id, user_id=current_user.user_id)
    )
