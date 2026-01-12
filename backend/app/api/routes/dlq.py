from datetime import datetime, timezone
from typing import List

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import current_user
from app.db.repositories.dlq_repository import DLQRepository
from app.dlq import RetryPolicy
from app.dlq.manager import DLQManager
from app.dlq.models import DLQMessageStatus
from app.domain.enums.events import EventType
from app.schemas_pydantic.dlq import (
    DLQBatchRetryResponse,
    DLQMessageDetail,
    DLQMessageResponse,
    DLQMessagesResponse,
    DLQStats,
    DLQTopicSummaryResponse,
    ManualRetryRequest,
    RetryPolicyRequest,
)
from app.schemas_pydantic.user import MessageResponse

router = APIRouter(
    prefix="/dlq", tags=["Dead Letter Queue"], route_class=DishkaRoute, dependencies=[Depends(current_user)]
)


@router.get("/stats", response_model=DLQStats)
async def get_dlq_statistics(repository: FromDishka[DLQRepository]) -> DLQStats:
    stats = await repository.get_dlq_stats()
    return DLQStats(
        by_status=stats.by_status,
        by_topic=[{"topic": t.topic, "count": t.count, "avg_retry_count": t.avg_retry_count} for t in stats.by_topic],
        by_event_type=[{"event_type": e.event_type, "count": e.count} for e in stats.by_event_type],
        age_stats={
            "min_age": stats.age_stats.min_age_seconds,
            "max_age": stats.age_stats.max_age_seconds,
            "avg_age": stats.age_stats.avg_age_seconds,
        }
        if stats.age_stats
        else {},
        timestamp=stats.timestamp,
    )


@router.get("/messages", response_model=DLQMessagesResponse)
async def get_dlq_messages(
    repository: FromDishka[DLQRepository],
    status: DLQMessageStatus | None = Query(None),
    topic: str | None = None,
    event_type: EventType | None = Query(None),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> DLQMessagesResponse:
    result = await repository.get_messages(
        status=status, topic=topic, event_type=event_type, limit=limit, offset=offset
    )

    # Convert domain messages to response models using model_validate
    messages = [DLQMessageResponse.model_validate(msg) for msg in result.messages]

    return DLQMessagesResponse(messages=messages, total=result.total, offset=result.offset, limit=result.limit)


@router.get("/messages/{event_id}", response_model=DLQMessageDetail)
async def get_dlq_message(event_id: str, repository: FromDishka[DLQRepository]) -> DLQMessageDetail:
    message = await repository.get_message_by_id(event_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    return DLQMessageDetail(
        event_id=message.event.event_id,
        event=message.event.model_dump(),
        event_type=message.event.event_type,
        original_topic=message.original_topic,
        error=message.error,
        retry_count=message.retry_count,
        failed_at=message.failed_at or datetime(1970, 1, 1, tzinfo=timezone.utc),
        status=DLQMessageStatus(message.status),
        created_at=message.created_at,
        last_updated=message.last_updated,
        next_retry_at=message.next_retry_at,
        retried_at=message.retried_at,
        discarded_at=message.discarded_at,
        discard_reason=message.discard_reason,
        producer_id=message.producer_id,
        dlq_offset=message.dlq_offset,
        dlq_partition=message.dlq_partition,
        last_error=message.last_error,
    )


@router.post("/retry", response_model=DLQBatchRetryResponse)
async def retry_dlq_messages(
    retry_request: ManualRetryRequest, dlq_manager: FromDishka[DLQManager]
) -> DLQBatchRetryResponse:
    result = await dlq_manager.retry_messages_batch(retry_request.event_ids)
    return DLQBatchRetryResponse(
        total=result.total,
        successful=result.successful,
        failed=result.failed,
        details=[
            {"event_id": d.event_id, "status": d.status, **({"error": d.error} if d.error else {})}
            for d in result.details
        ],
    )


@router.post("/retry-policy", response_model=MessageResponse)
async def set_retry_policy(policy_request: RetryPolicyRequest, dlq_manager: FromDishka[DLQManager]) -> MessageResponse:
    policy = RetryPolicy(
        topic=policy_request.topic,
        strategy=policy_request.strategy,
        max_retries=policy_request.max_retries,
        base_delay_seconds=policy_request.base_delay_seconds,
        max_delay_seconds=policy_request.max_delay_seconds,
        retry_multiplier=policy_request.retry_multiplier,
    )

    dlq_manager.set_retry_policy(policy_request.topic, policy)

    return MessageResponse(message=f"Retry policy set for topic {policy_request.topic}")


@router.delete("/messages/{event_id}", response_model=MessageResponse)
async def discard_dlq_message(
    event_id: str,
    repository: FromDishka[DLQRepository],
    dlq_manager: FromDishka[DLQManager],
    reason: str = Query(..., description="Reason for discarding"),
) -> MessageResponse:
    message_data = await repository.get_message_by_id(event_id)
    if not message_data:
        raise HTTPException(status_code=404, detail="Message not found")

    await dlq_manager._discard_message(message_data, f"manual: {reason}")
    await repository.mark_message_discarded(event_id, f"manual: {reason}")
    return MessageResponse(message=f"Message {event_id} discarded")


@router.get("/topics", response_model=List[DLQTopicSummaryResponse])
async def get_dlq_topics(repository: FromDishka[DLQRepository]) -> List[DLQTopicSummaryResponse]:
    topics = await repository.get_topics_summary()
    return [DLQTopicSummaryResponse.model_validate(topic) for topic in topics]
