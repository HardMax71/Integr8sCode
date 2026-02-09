from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import admin_user
from app.db.repositories import DLQRepository
from app.dlq import RetryPolicy
from app.dlq.manager import DLQManager
from app.dlq.models import DLQMessageStatus
from app.domain.enums import EventType
from app.schemas_pydantic.common import ErrorResponse
from app.schemas_pydantic.dlq import (
    DLQBatchRetryResponse,
    DLQMessageDetail,
    DLQMessageResponse,
    DLQMessagesResponse,
    DLQTopicSummaryResponse,
    ManualRetryRequest,
    RetryPolicyRequest,
)
from app.schemas_pydantic.user import MessageResponse

router = APIRouter(
    prefix="/dlq", tags=["Dead Letter Queue"], route_class=DishkaRoute, dependencies=[Depends(admin_user)]
)


@router.get("/messages", response_model=DLQMessagesResponse)
async def get_dlq_messages(
    repository: FromDishka[DLQRepository],
    status: Annotated[DLQMessageStatus | None, Query(description="Filter by message status")] = None,
    topic: Annotated[str | None, Query(description="Filter by source Kafka topic")] = None,
    event_type: Annotated[EventType | None, Query(description="Filter by event type")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DLQMessagesResponse:
    """List DLQ messages with optional filtering."""
    result = await repository.get_messages(
        status=status, topic=topic, event_type=event_type, limit=limit, offset=offset
    )

    # Convert domain messages to response models using model_validate
    messages = [DLQMessageResponse.model_validate(msg) for msg in result.messages]

    return DLQMessagesResponse(messages=messages, total=result.total, offset=result.offset, limit=result.limit)


@router.get(
    "/messages/{event_id}",
    response_model=DLQMessageDetail,
    responses={404: {"model": ErrorResponse, "description": "DLQ message not found"}},
)
async def get_dlq_message(event_id: str, repository: FromDishka[DLQRepository]) -> DLQMessageDetail:
    """Get details of a specific DLQ message."""
    message = await repository.get_message_by_id(event_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return DLQMessageDetail.model_validate(message, from_attributes=True)


@router.post("/retry", response_model=DLQBatchRetryResponse)
async def retry_dlq_messages(
    retry_request: ManualRetryRequest, dlq_manager: FromDishka[DLQManager]
) -> DLQBatchRetryResponse:
    """Retry a batch of DLQ messages by their event IDs."""
    result = await dlq_manager.retry_messages_batch(retry_request.event_ids)
    return DLQBatchRetryResponse.model_validate(result, from_attributes=True)


@router.post("/retry-policy", response_model=MessageResponse)
async def set_retry_policy(policy_request: RetryPolicyRequest, dlq_manager: FromDishka[DLQManager]) -> MessageResponse:
    """Configure a retry policy for a specific Kafka topic."""
    policy = RetryPolicy(**policy_request.model_dump())

    dlq_manager.set_retry_policy(policy_request.topic, policy)

    return MessageResponse(message=f"Retry policy set for topic {policy_request.topic}")


@router.delete(
    "/messages/{event_id}",
    response_model=MessageResponse,
    responses={404: {"model": ErrorResponse, "description": "Message not found or already in terminal state"}},
)
async def discard_dlq_message(
    event_id: str,
    dlq_manager: FromDishka[DLQManager],
    reason: Annotated[str, Query(description="Reason for discarding")],
) -> MessageResponse:
    """Permanently discard a DLQ message with a reason."""
    success = await dlq_manager.discard_message_manually(event_id, f"manual: {reason}")
    if not success:
        raise HTTPException(status_code=404, detail="Message not found or already in terminal state")
    return MessageResponse(message=f"Message {event_id} discarded")


@router.get("/topics", response_model=list[DLQTopicSummaryResponse])
async def get_dlq_topics(repository: FromDishka[DLQRepository]) -> list[DLQTopicSummaryResponse]:
    """Get a per-topic summary of DLQ message counts."""
    topics = await repository.get_topics_summary()
    return [DLQTopicSummaryResponse.model_validate(topic) for topic in topics]
