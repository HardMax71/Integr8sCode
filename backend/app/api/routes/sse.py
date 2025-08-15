from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import get_current_user
from app.core.service_dependencies import (
    SSEConnectionManagerDep,
    SSERepositoryDep,
    SSEShutdownManagerDep,
)
from app.schemas_pydantic.sse import SSEHealthResponse
from app.schemas_pydantic.user import UserResponse

router = APIRouter(prefix="/events", tags=["sse"])


@router.get("/notifications/stream")
async def notification_stream(
        request: Request,
        repository: SSERepositoryDep,
        current_user: UserResponse = Depends(get_current_user),
) -> EventSourceResponse:
    async def check_disconnected() -> bool:
        """Check if the request is disconnected."""
        return await request.is_disconnected()

    return EventSourceResponse(
        repository.create_notification_stream(
            user_id=current_user.user_id,
            request_disconnected_check=check_disconnected
        )
    )


@router.get("/executions/{execution_id}")
async def execution_events(
        execution_id: str,
        request: Request,
        repository: SSERepositoryDep,
        current_user: UserResponse = Depends(get_current_user)
) -> EventSourceResponse:
    async def check_disconnected() -> bool:
        """Check if the request is disconnected."""
        return await request.is_disconnected()

    return EventSourceResponse(
        repository.create_execution_event_stream(
            execution_id=execution_id,
            user_id=current_user.user_id,
            request_disconnected_check=check_disconnected
        )
    )


@router.get("/executions/{execution_id}/kafka")
async def execution_events_kafka(
        execution_id: str,
        request: Request,
        repository: SSERepositoryDep,
        shutdown_manager: SSEShutdownManagerDep,
        connection_manager: SSEConnectionManagerDep,
        current_user: UserResponse = Depends(get_current_user)
) -> EventSourceResponse:
    connection_id = connection_manager.get_connection_id()

    return EventSourceResponse(
        repository.create_kafka_event_stream(
            execution_id=execution_id,
            user_id=current_user.user_id,
            connection_id=connection_id,
            shutdown_manager=shutdown_manager,
            connection_manager=connection_manager
        )
    )


@router.get("/health", response_model=SSEHealthResponse)
async def sse_health(
        repository: SSERepositoryDep,
        shutdown_manager: SSEShutdownManagerDep,
        current_user: UserResponse = Depends(get_current_user),
) -> SSEHealthResponse:
    return await repository.get_health_status(shutdown_manager)
