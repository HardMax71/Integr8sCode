from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import get_current_user
from app.db.mongodb import DatabaseManager, get_database_manager
from app.db.repositories.sse_repository import SSERepository
from app.schemas_pydantic.sse import SSEHealthResponse
from app.schemas_pydantic.user import UserResponse
from app.services.sse_connection_manager import get_sse_connection_manager
from app.services.sse_shutdown_manager import get_sse_shutdown_manager

router = APIRouter(prefix="/events", tags=["sse"])


@router.get("/notifications/stream")
async def notification_stream(
        request: Request,
        current_user: UserResponse = Depends(get_current_user),
        db_manager: DatabaseManager = Depends(get_database_manager)
) -> EventSourceResponse:
    repository = SSERepository(db_manager)

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
        current_user: UserResponse = Depends(get_current_user),
        db_manager: DatabaseManager = Depends(get_database_manager)
) -> EventSourceResponse:
    repository = SSERepository(db_manager)

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
        current_user: UserResponse = Depends(get_current_user),
        db_manager: DatabaseManager = Depends(get_database_manager)
) -> EventSourceResponse:
    repository = SSERepository(db_manager)
    connection_manager = get_sse_connection_manager()
    shutdown_manager = get_sse_shutdown_manager()

    connection_id = connection_manager.get_connection_id()

    return EventSourceResponse(
        repository.create_kafka_event_stream(
            execution_id=execution_id,
            user_id=current_user.user_id,
            connection_id=connection_id,
            shutdown_manager=shutdown_manager
        )
    )


@router.get("/health", response_model=SSEHealthResponse)
async def sse_health(
        current_user: UserResponse = Depends(get_current_user),
        db_manager: DatabaseManager = Depends(get_database_manager)
) -> SSEHealthResponse:
    repository = SSERepository(db_manager)
    shutdown_manager = get_sse_shutdown_manager()

    return await repository.get_health_status(shutdown_manager)
