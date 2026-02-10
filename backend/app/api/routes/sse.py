from copy import deepcopy
from typing import Annotated, Any

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import current_user
from app.domain.user import User
from app.schemas_pydantic.notification import NotificationResponse
from app.schemas_pydantic.sse import SSEExecutionEventData
from app.services.sse import SSEService

router = APIRouter(prefix="/events", tags=["sse"], route_class=DishkaRoute)


def _sse_schema(model: type[BaseModel]) -> dict[str, Any]:
    # model_json_schema() emits $defs with local $ref pointers that openapi-ts
    # cannot resolve when inlined into the OpenAPI spec. Resolve all $refs
    # against the local $defs to produce a self-contained schema dict.
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                return resolve(deepcopy(defs[name]))
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)  # type: ignore[no-any-return]


@router.get(
    "/notifications/stream",
    response_class=EventSourceResponse,
    responses={200: {"content": {"text/event-stream": {"schema": _sse_schema(NotificationResponse)}}}},
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
    response_class=EventSourceResponse,
    responses={200: {"content": {"text/event-stream": {"schema": _sse_schema(SSEExecutionEventData)}}}},
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
