from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.domain.sse import SSEHealthDomain
from app.schemas_pydantic.sse import (
    ShutdownStatusResponse,
    SSEExecutionEventData,
    SSEHealthResponse,
    SSENotificationEventData,
)
from app.services.auth_service import AuthService
from app.services.sse.sse_service import SSEService

router = APIRouter(prefix="/events", tags=["sse"], route_class=DishkaRoute)


@router.get("/notifications/stream", responses={200: {"model": SSENotificationEventData}})
async def notification_stream(
    request: Request,
    sse_service: FromDishka[SSEService],
    auth_service: FromDishka[AuthService],
) -> EventSourceResponse:
    """Stream notifications for authenticated user."""
    current_user = await auth_service.get_current_user(request)

    return EventSourceResponse(sse_service.create_notification_stream(user_id=current_user.user_id))


@router.get("/executions/{execution_id}", responses={200: {"model": SSEExecutionEventData}})
async def execution_events(
    execution_id: str, request: Request, sse_service: FromDishka[SSEService], auth_service: FromDishka[AuthService]
) -> EventSourceResponse:
    """Stream events for specific execution."""
    current_user = await auth_service.get_current_user(request)

    return EventSourceResponse(
        sse_service.create_execution_stream(execution_id=execution_id, user_id=current_user.user_id)
    )


@router.get("/health", response_model=SSEHealthResponse)
async def sse_health(
    request: Request,
    sse_service: FromDishka[SSEService],
    auth_service: FromDishka[AuthService],
) -> SSEHealthResponse:
    """Get SSE service health status."""
    _ = await auth_service.get_current_user(request)
    domain: SSEHealthDomain = await sse_service.get_health_status()
    return SSEHealthResponse(
        status=domain.status,
        kafka_enabled=domain.kafka_enabled,
        active_connections=domain.active_connections,
        active_executions=domain.active_executions,
        active_consumers=domain.active_consumers,
        max_connections_per_user=domain.max_connections_per_user,
        shutdown=ShutdownStatusResponse(**vars(domain.shutdown)),
        timestamp=domain.timestamp,
    )
