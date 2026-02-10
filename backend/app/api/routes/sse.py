from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import current_user
from app.domain.user import User
from app.schemas_pydantic.notification import NotificationResponse
from app.schemas_pydantic.sse import SSEExecutionEventData
from app.services.sse import SSEService

router = APIRouter(prefix="/events", tags=["sse"], route_class=DishkaRoute)


@router.get(
    "/notifications/stream",
    responses={200: {"content": {"text/event-stream": {"schema": NotificationResponse}}}},
)
async def notification_stream(
    user: Annotated[User, Depends(current_user)],
    sse_service: FromDishka[SSEService],
) -> EventSourceResponse:
    """Stream notifications for authenticated user."""
    return EventSourceResponse(
        sse_service.create_notification_stream(user_id=user.user_id),
        ping=30,
    )


@router.get(
    "/executions/{execution_id}",
    responses={200: {"content": {"text/event-stream": {"schema": SSEExecutionEventData}}}},
)
async def execution_events(
    execution_id: str,
    user: Annotated[User, Depends(current_user)],
    sse_service: FromDishka[SSEService],
) -> EventSourceResponse:
    """Stream events for specific execution."""
    return EventSourceResponse(
        sse_service.create_execution_stream(execution_id=execution_id, user_id=user.user_id)
    )
