import pytest
from app.dlq.models import DLQMessageStatus, RetryStrategy
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.schemas_pydantic.dlq import (
    DLQBatchRetryResponse,
    DLQMessageDetail,
    DLQMessagesResponse,
    DLQStats,
    DLQTopicSummaryResponse,
)
from app.schemas_pydantic.user import MessageResponse
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]


class TestGetDLQStats:
    """Tests for GET /api/v1/dlq/stats."""

    @pytest.mark.asyncio
    async def test_get_dlq_stats(self, test_user: AsyncClient) -> None:
        """Get DLQ statistics."""
        response = await test_user.get("/api/v1/dlq/stats")

        assert response.status_code == 200
        stats = DLQStats.model_validate(response.json())

        assert isinstance(stats.by_status, dict)
        assert isinstance(stats.by_topic, list)
        assert isinstance(stats.by_event_type, list)
        assert stats.age_stats is not None
        assert stats.timestamp is not None

    @pytest.mark.asyncio
    async def test_get_dlq_stats_unauthenticated(
            self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/dlq/stats")
        assert response.status_code == 401


class TestGetDLQMessages:
    """Tests for GET /api/v1/dlq/messages."""

    @pytest.mark.asyncio
    async def test_get_dlq_messages(self, test_user: AsyncClient) -> None:
        """Get DLQ messages list."""
        response = await test_user.get("/api/v1/dlq/messages")

        assert response.status_code == 200
        result = DLQMessagesResponse.model_validate(response.json())

        assert result.total >= 0
        assert result.offset == 0
        assert result.limit == 50  # default
        assert isinstance(result.messages, list)

    @pytest.mark.asyncio
    async def test_get_dlq_messages_with_pagination(
            self, test_user: AsyncClient
    ) -> None:
        """Pagination parameters work correctly."""
        response = await test_user.get(
            "/api/v1/dlq/messages",
            params={"limit": 10, "offset": 0},
        )

        assert response.status_code == 200
        result = DLQMessagesResponse.model_validate(response.json())
        assert result.limit == 10
        assert result.offset == 0

    @pytest.mark.asyncio
    async def test_get_dlq_messages_by_status(
            self, test_user: AsyncClient
    ) -> None:
        """Filter DLQ messages by status."""
        response = await test_user.get(
            "/api/v1/dlq/messages",
            params={"status": DLQMessageStatus.PENDING},
        )

        assert response.status_code == 200
        result = DLQMessagesResponse.model_validate(response.json())

        for msg in result.messages:
            assert msg.status == DLQMessageStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_dlq_messages_by_topic(
            self, test_user: AsyncClient
    ) -> None:
        """Filter DLQ messages by topic."""
        response = await test_user.get(
            "/api/v1/dlq/messages",
            params={"topic": KafkaTopic.EXECUTION_EVENTS},
        )

        assert response.status_code == 200
        result = DLQMessagesResponse.model_validate(response.json())
        assert isinstance(result.messages, list)

    @pytest.mark.asyncio
    async def test_get_dlq_messages_by_event_type(
            self, test_user: AsyncClient
    ) -> None:
        """Filter DLQ messages by event type."""
        response = await test_user.get(
            "/api/v1/dlq/messages",
            params={"event_type": EventType.EXECUTION_REQUESTED},
        )

        assert response.status_code == 200
        result = DLQMessagesResponse.model_validate(response.json())
        assert isinstance(result.messages, list)


class TestGetDLQMessage:
    """Tests for GET /api/v1/dlq/messages/{event_id}."""

    @pytest.mark.asyncio
    async def test_get_dlq_message_not_found(
            self, test_user: AsyncClient
    ) -> None:
        """Get nonexistent DLQ message returns 404."""
        response = await test_user.get(
            "/api/v1/dlq/messages/nonexistent-event-id"
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_dlq_message_detail(
            self, test_user: AsyncClient
    ) -> None:
        """Get DLQ message detail if messages exist."""
        # First list messages to find one
        list_response = await test_user.get(
            "/api/v1/dlq/messages",
            params={"limit": 1},
        )
        assert list_response.status_code == 200
        result = DLQMessagesResponse.model_validate(list_response.json())

        if result.messages:
            event_id = result.messages[0].event.event_id

            # Get detail
            response = await test_user.get(
                f"/api/v1/dlq/messages/{event_id}"
            )
            assert response.status_code == 200
            detail = DLQMessageDetail.model_validate(response.json())
            assert detail.event is not None
            assert detail.original_topic is not None
            assert detail.error is not None
            assert detail.retry_count >= 0
            assert detail.failed_at is not None
            assert detail.status is not None


class TestRetryDLQMessages:
    """Tests for POST /api/v1/dlq/retry."""

    @pytest.mark.asyncio
    async def test_retry_dlq_messages(self, test_user: AsyncClient) -> None:
        """Retry DLQ messages."""
        # First list messages to find some
        list_response = await test_user.get(
            "/api/v1/dlq/messages",
            params={"status": DLQMessageStatus.PENDING, "limit": 5},
        )
        assert list_response.status_code == 200
        result = DLQMessagesResponse.model_validate(list_response.json())

        if result.messages:
            event_ids = [msg.event.event_id for msg in result.messages[:2]]

            # Retry
            response = await test_user.post(
                "/api/v1/dlq/retry",
                json={"event_ids": event_ids},
            )
            assert response.status_code == 200
            retry_result = DLQBatchRetryResponse.model_validate(
                response.json()
            )

            assert retry_result.total >= 0
            assert retry_result.successful >= 0
            assert retry_result.failed >= 0
            assert isinstance(retry_result.details, list)

    @pytest.mark.asyncio
    async def test_retry_dlq_messages_empty_list(
            self, test_user: AsyncClient
    ) -> None:
        """Retry with empty event IDs list."""
        response = await test_user.post(
            "/api/v1/dlq/retry",
            json={"event_ids": []},
        )

        assert response.status_code == 200
        result = DLQBatchRetryResponse.model_validate(response.json())
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_retry_dlq_messages_nonexistent(
            self, test_user: AsyncClient
    ) -> None:
        """Retry nonexistent messages."""
        response = await test_user.post(
            "/api/v1/dlq/retry",
            json={"event_ids": ["nonexistent-1", "nonexistent-2"]},
        )

        # May succeed with failures reported in details
        assert response.status_code == 200
        result = DLQBatchRetryResponse.model_validate(response.json())
        assert isinstance(result.details, list)


class TestSetRetryPolicy:
    """Tests for POST /api/v1/dlq/retry-policy."""

    @pytest.mark.asyncio
    async def test_set_retry_policy(self, test_user: AsyncClient) -> None:
        """Set retry policy for a topic."""
        response = await test_user.post(
            "/api/v1/dlq/retry-policy",
            json={
                "topic": KafkaTopic.EXECUTION_EVENTS,
                "strategy": RetryStrategy.EXPONENTIAL_BACKOFF,
                "max_retries": 5,
                "base_delay_seconds": 60.0,
                "max_delay_seconds": 3600.0,
                "retry_multiplier": 2.0,
            },
        )

        assert response.status_code == 200
        result = MessageResponse.model_validate(response.json())
        assert KafkaTopic.EXECUTION_EVENTS in result.message

    @pytest.mark.asyncio
    async def test_set_retry_policy_fixed_strategy(
            self, test_user: AsyncClient
    ) -> None:
        """Set retry policy with fixed strategy."""
        response = await test_user.post(
            "/api/v1/dlq/retry-policy",
            json={
                "topic": KafkaTopic.POD_EVENTS,
                "strategy": RetryStrategy.FIXED_INTERVAL,
                "max_retries": 3,
                "base_delay_seconds": 30.0,
                "max_delay_seconds": 300.0,
                "retry_multiplier": 1.0,
            },
        )

        assert response.status_code == 200
        result = MessageResponse.model_validate(response.json())
        assert KafkaTopic.POD_EVENTS in result.message

    @pytest.mark.asyncio
    async def test_set_retry_policy_scheduled_strategy(
            self, test_user: AsyncClient
    ) -> None:
        """Set retry policy with scheduled strategy."""
        response = await test_user.post(
            "/api/v1/dlq/retry-policy",
            json={
                "topic": KafkaTopic.USER_EVENTS,
                "strategy": RetryStrategy.SCHEDULED,
                "max_retries": 10,
                "base_delay_seconds": 120.0,
                "max_delay_seconds": 7200.0,
                "retry_multiplier": 1.5,
            },
        )

        assert response.status_code == 200
        result = MessageResponse.model_validate(response.json())
        assert KafkaTopic.USER_EVENTS in result.message


class TestDiscardDLQMessage:
    """Tests for DELETE /api/v1/dlq/messages/{event_id}."""

    @pytest.mark.asyncio
    async def test_discard_dlq_message_not_found(
            self, test_user: AsyncClient
    ) -> None:
        """Discard nonexistent message returns 404."""
        response = await test_user.delete(
            "/api/v1/dlq/messages/nonexistent-event-id",
            params={"reason": "Test discard"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_discard_dlq_message(self, test_user: AsyncClient) -> None:
        """Discard a DLQ message if messages exist."""
        # First list messages to find one
        list_response = await test_user.get(
            "/api/v1/dlq/messages",
            params={"limit": 1},
        )
        assert list_response.status_code == 200
        result = DLQMessagesResponse.model_validate(list_response.json())

        if result.messages:
            event_id = result.messages[0].event.event_id

            # Discard
            response = await test_user.delete(
                f"/api/v1/dlq/messages/{event_id}",
                params={"reason": "Test discard for E2E testing"},
            )
            assert response.status_code == 200
            msg_result = MessageResponse.model_validate(
                response.json()
            )
            assert event_id in msg_result.message
            assert "discarded" in msg_result.message.lower()

    @pytest.mark.asyncio
    async def test_discard_dlq_message_requires_reason(
            self, test_user: AsyncClient
    ) -> None:
        """Discard requires reason parameter."""
        response = await test_user.delete(
            "/api/v1/dlq/messages/some-event-id"
        )
        assert response.status_code == 422


class TestGetDLQTopics:
    """Tests for GET /api/v1/dlq/topics."""

    @pytest.mark.asyncio
    async def test_get_dlq_topics(self, test_user: AsyncClient) -> None:
        """Get DLQ topics summary."""
        response = await test_user.get("/api/v1/dlq/topics")

        assert response.status_code == 200
        topics = [
            DLQTopicSummaryResponse.model_validate(t)
            for t in response.json()
        ]

        for topic in topics:
            assert topic.topic is not None
            assert topic.total_messages >= 0
            assert isinstance(topic.status_breakdown, dict)
            assert topic.avg_retry_count >= 0
            assert topic.max_retry_count >= 0

    @pytest.mark.asyncio
    async def test_get_dlq_topics_unauthenticated(
            self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/dlq/topics")
        assert response.status_code == 401
