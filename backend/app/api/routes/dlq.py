from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_current_user
from app.core.logging import logger
from app.core.service_dependencies import DLQRepositoryDep, get_dlq_manager
from app.dlq.manager import DLQManager, RetryPolicy
from app.schemas_pydantic.dlq import (
    DLQBatchRetryResponse,
    DLQMessageDetail,
    DLQMessageResponse,
    DLQMessagesResponse,
    DLQMessageStatus,
    DLQStats,
    DLQTopicSummaryResponse,
    ManualRetryRequest,
    RetryPolicyRequest,
)
from app.schemas_pydantic.user import MessageResponse

router = APIRouter(prefix="/dlq", tags=["Dead Letter Queue"])


@router.get("/stats", response_model=DLQStats)
async def get_dlq_statistics(
        repository: DLQRepositoryDep,
        current_user: dict = Depends(get_current_user)
) -> DLQStats:
    """Get DLQ statistics"""
    try:
        stats = await repository.get_dlq_stats()
        return DLQStats(**stats.to_dict())
    except Exception as e:
        logger.error(f"Failed to get DLQ stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages", response_model=DLQMessagesResponse)
async def get_dlq_messages(
        repository: DLQRepositoryDep,
        current_user: dict = Depends(get_current_user),
        status: Optional[DLQMessageStatus] = Query(None),
        topic: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = Query(50, ge=1, le=1000),
        offset: int = Query(0, ge=0)
) -> DLQMessagesResponse:
    """Get DLQ messages with filters"""
    try:
        result = await repository.get_messages(
            status=status.value if status else None,
            topic=topic,
            event_type=event_type,
            limit=limit,
            offset=offset
        )
        
        # Convert domain messages to response models
        messages = [
            DLQMessageResponse(
                event_id=msg.event_id or "unknown",
                event_type=msg.event_type,
                original_topic=msg.original_topic,
                error=msg.error,
                retry_count=msg.retry_count,
                failed_at=msg.failed_at,
                status=DLQMessageStatus(msg.status.value),
                age_seconds=msg.age_seconds,
                details={
                    "producer_id": msg.producer_id,
                    "dlq_offset": msg.dlq_offset,
                    "dlq_partition": msg.dlq_partition,
                    "last_error": msg.last_error,
                    "next_retry_at": msg.next_retry_at
                }
            )
            for msg in result.messages
        ]
        
        return DLQMessagesResponse(
            messages=messages,
            total=result.total,
            offset=result.offset,
            limit=result.limit
        )
    except Exception as e:
        logger.error(f"Failed to get DLQ messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages/{event_id}", response_model=DLQMessageDetail)
async def get_dlq_message(
        event_id: str,
        repository: DLQRepositoryDep,
        current_user: dict = Depends(get_current_user)
) -> DLQMessageDetail:
    """Get specific DLQ message details"""
    try:
        message = await repository.get_message_by_id(event_id)

        if not message:
            raise HTTPException(status_code=404, detail="Message not found")

        return DLQMessageDetail(
            event_id=message.event_id or "unknown",
            event=message.event,
            event_type=message.event_type,
            original_topic=message.original_topic,
            error=message.error,
            retry_count=message.retry_count,
            failed_at=message.failed_at,
            status=DLQMessageStatus(message.status.value),
            created_at=message.created_at,
            last_updated=message.last_updated,
            next_retry_at=message.next_retry_at,
            retried_at=message.retried_at,
            discarded_at=message.discarded_at,
            discard_reason=message.discard_reason,
            producer_id=message.producer_id,
            dlq_offset=message.dlq_offset,
            dlq_partition=message.dlq_partition,
            last_error=message.last_error
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get DLQ message {event_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retry", response_model=DLQBatchRetryResponse)
async def retry_dlq_messages(
        request: ManualRetryRequest,
        repository: DLQRepositoryDep,
        dlq_manager: DLQManager = Depends(get_dlq_manager),
        current_user: dict = Depends(get_current_user)
) -> DLQBatchRetryResponse:
    """Manually retry DLQ messages"""
    try:
        result = await repository.retry_messages_batch(request.event_ids, dlq_manager)
        
        return DLQBatchRetryResponse(**result.to_dict())

    except Exception as e:
        logger.error(f"Failed to retry DLQ messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retry-policy", response_model=MessageResponse)
async def set_retry_policy(
        request: RetryPolicyRequest,
        dlq_manager: DLQManager = Depends(get_dlq_manager),
        current_user: dict = Depends(get_current_user)
) -> MessageResponse:
    """Set retry policy for a topic"""
    try:

        policy = RetryPolicy(
            topic=request.topic,
            strategy=request.strategy,
            max_retries=request.max_retries,
            base_delay_seconds=request.base_delay_seconds,
            max_delay_seconds=request.max_delay_seconds,
            retry_multiplier=request.retry_multiplier
        )

        dlq_manager.set_retry_policy(request.topic, policy)

        return MessageResponse(
            message=f"Retry policy set for topic {request.topic}"
        )

    except Exception as e:
        logger.error(f"Failed to set retry policy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/messages/{event_id}", response_model=MessageResponse)
async def discard_dlq_message(
        event_id: str,
        repository: DLQRepositoryDep,
        dlq_manager: DLQManager = Depends(get_dlq_manager),
        current_user: dict = Depends(get_current_user),
        reason: str = Query(..., description="Reason for discarding")
) -> MessageResponse:
    """Discard a DLQ message"""
    try:
        # Get message from repository
        message_data = await repository.get_message_for_retry(event_id)

        if not message_data:
            raise HTTPException(status_code=404, detail="Message not found")

        # Use dlq_manager for discard logic
        await dlq_manager._discard_message(message_data, f"manual: {reason}")

        # Mark as discarded in repository
        await repository.mark_message_discarded(event_id, f"manual: {reason}")

        return MessageResponse(
            message=f"Message {event_id} discarded"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to discard DLQ message {event_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/topics", response_model=List[DLQTopicSummaryResponse])
async def get_dlq_topics(
        repository: DLQRepositoryDep,
        current_user: dict = Depends(get_current_user)
) -> List[DLQTopicSummaryResponse]:
    """Get summary of all topics in DLQ"""
    try:
        topics = await repository.get_topics_summary()
        return [
            DLQTopicSummaryResponse(**topic.to_dict())
            for topic in topics
        ]
    except Exception as e:
        logger.error(f"Failed to get DLQ topics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
