import pytest
import pytest_asyncio
from app.db.docs.dlq import DLQMessageDocument
from app.dlq.models import DLQMessageStatus, RetryStrategy
from app.domain.enums import EventType
from app.schemas_pydantic.dlq import (
    DLQBatchRetryResponse,
    DLQMessageDetail,
    DLQMessagesResponse,
    DLQTopicSummaryResponse,
)
from app.schemas_pydantic.user import MessageResponse
from httpx import AsyncClient

from tests.conftest import make_execution_requested_event

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]


@pytest_asyncio.fixture
async def stored_dlq_message() -> DLQMessageDocument:
    """Insert a DLQ message directly into MongoDB and return it."""
    event = make_execution_requested_event()
    doc = DLQMessageDocument(
        event=event,
        original_topic="execution-events",
        error="Simulated failure for E2E testing",
        retry_count=0,
        status=DLQMessageStatus.PENDING,
        producer_id="e2e-test",
    )
    await doc.insert()
    return doc


class TestGetDLQMessages:
    """Tests for GET /api/v1/dlq/messages."""

    @pytest.mark.asyncio
    async def test_get_dlq_messages(self, test_admin: AsyncClient) -> None:
        """Get DLQ messages list."""
        response = await test_admin.get("/api/v1/dlq/messages")

        assert response.status_code == 200
        result = DLQMessagesResponse.model_validate(response.json())

        assert result.offset == 0
        assert result.limit == 50  # default

    @pytest.mark.asyncio
    async def test_get_dlq_messages_with_pagination(
            self, test_admin: AsyncClient
    ) -> None:
        """Pagination parameters work correctly."""
        response = await test_admin.get(
            "/api/v1/dlq/messages",
            params={"limit": 10, "offset": 0},
        )

        assert response.status_code == 200
        result = DLQMessagesResponse.model_validate(response.json())
        assert result.limit == 10
        assert result.offset == 0

    @pytest.mark.asyncio
    async def test_get_dlq_messages_by_status(
            self, test_admin: AsyncClient
    ) -> None:
        """Filter DLQ messages by status."""
        response = await test_admin.get(
            "/api/v1/dlq/messages",
            params={"status": DLQMessageStatus.PENDING},
        )

        assert response.status_code == 200
        result = DLQMessagesResponse.model_validate(response.json())

        for msg in result.messages:
            assert msg.status == DLQMessageStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_dlq_messages_by_topic(
            self, test_admin: AsyncClient
    ) -> None:
        """Filter DLQ messages by topic."""
        response = await test_admin.get(
            "/api/v1/dlq/messages",
            params={"topic": "execution-events"},
        )

        assert response.status_code == 200
        DLQMessagesResponse.model_validate(response.json())

    @pytest.mark.asyncio
    async def test_get_dlq_messages_by_event_type(
            self, test_admin: AsyncClient
    ) -> None:
        """Filter DLQ messages by event type."""
        response = await test_admin.get(
            "/api/v1/dlq/messages",
            params={"event_type": EventType.EXECUTION_REQUESTED},
        )

        assert response.status_code == 200
        DLQMessagesResponse.model_validate(response.json())


class TestGetDLQMessage:
    """Tests for GET /api/v1/dlq/messages/{event_id}."""

    @pytest.mark.asyncio
    async def test_get_dlq_message_not_found(
            self, test_admin: AsyncClient
    ) -> None:
        """Get nonexistent DLQ message returns 404."""
        response = await test_admin.get(
            "/api/v1/dlq/messages/nonexistent-event-id"
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_dlq_message_detail(
            self, test_admin: AsyncClient, stored_dlq_message: DLQMessageDocument
    ) -> None:
        """Get DLQ message detail by event_id."""
        event_id = stored_dlq_message.event.event_id

        response = await test_admin.get(
            f"/api/v1/dlq/messages/{event_id}"
        )
        assert response.status_code == 200
        detail = DLQMessageDetail.model_validate(response.json())
        assert detail.event.event_id == event_id
        assert detail.original_topic == "execution-events"
        assert detail.error == "Simulated failure for E2E testing"
        assert detail.retry_count == 0


class TestRetryDLQMessages:
    """Tests for POST /api/v1/dlq/retry."""

    @pytest.mark.asyncio
    async def test_retry_dlq_messages(
            self, test_admin: AsyncClient, stored_dlq_message: DLQMessageDocument
    ) -> None:
        """Retry a known DLQ message."""
        event_ids = [stored_dlq_message.event.event_id]

        response = await test_admin.post(
            "/api/v1/dlq/retry",
            json={"event_ids": event_ids},
        )
        assert response.status_code == 200
        retry_result = DLQBatchRetryResponse.model_validate(
            response.json()
        )

        assert retry_result.total == 1
        assert retry_result.successful + retry_result.failed == 1

    @pytest.mark.asyncio
    async def test_retry_dlq_messages_empty_list(
            self, test_admin: AsyncClient
    ) -> None:
        """Retry with empty event IDs list."""
        response = await test_admin.post(
            "/api/v1/dlq/retry",
            json={"event_ids": []},
        )

        assert response.status_code == 200
        result = DLQBatchRetryResponse.model_validate(response.json())
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_retry_dlq_messages_nonexistent(
            self, test_admin: AsyncClient
    ) -> None:
        """Retry nonexistent messages."""
        response = await test_admin.post(
            "/api/v1/dlq/retry",
            json={"event_ids": ["nonexistent-1", "nonexistent-2"]},
        )

        # May succeed with failures reported in details
        assert response.status_code == 200
        result = DLQBatchRetryResponse.model_validate(response.json())
        assert result.total == 2
        assert result.failed == 2


class TestSetRetryPolicy:
    """Tests for POST /api/v1/dlq/retry-policy."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("strategy", "topic"),
        [
            (RetryStrategy.EXPONENTIAL_BACKOFF, "execution-events"),
            (RetryStrategy.FIXED_INTERVAL, "test-topic"),
            (RetryStrategy.SCHEDULED, "notifications-topic"),
        ],
        ids=str,
    )
    async def test_set_retry_policy(
        self, test_admin: AsyncClient, strategy: RetryStrategy, topic: str
    ) -> None:
        """Set retry policy for each strategy type."""
        response = await test_admin.post(
            "/api/v1/dlq/retry-policy",
            json={
                "topic": topic,
                "strategy": strategy,
                "max_retries": 5,
                "base_delay_seconds": 60.0,
                "max_delay_seconds": 3600.0,
                "retry_multiplier": 2.0,
            },
        )

        assert response.status_code == 200
        result = MessageResponse.model_validate(response.json())
        assert topic in result.message


class TestDiscardDLQMessage:
    """Tests for DELETE /api/v1/dlq/messages/{event_id}."""

    @pytest.mark.asyncio
    async def test_discard_dlq_message_not_found(
            self, test_admin: AsyncClient
    ) -> None:
        """Discard nonexistent message returns 404."""
        response = await test_admin.delete(
            "/api/v1/dlq/messages/nonexistent-event-id",
            params={"reason": "Test discard"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_discard_dlq_message(
            self, test_admin: AsyncClient, stored_dlq_message: DLQMessageDocument
    ) -> None:
        """Discard a known DLQ message."""
        event_id = stored_dlq_message.event.event_id

        response = await test_admin.delete(
            f"/api/v1/dlq/messages/{event_id}",
            params={"reason": "Test discard for E2E testing"},
        )
        assert response.status_code == 200
        msg_result = MessageResponse.model_validate(
            response.json()
        )
        assert event_id in msg_result.message
        assert "discarded" in msg_result.message.lower()

        # Verify message is actually gone or marked discarded
        get_resp = await test_admin.get(f"/api/v1/dlq/messages/{event_id}")
        if get_resp.status_code == 200:
            detail = DLQMessageDetail.model_validate(get_resp.json())
            assert detail.status == DLQMessageStatus.DISCARDED

    @pytest.mark.asyncio
    async def test_discard_dlq_message_requires_reason(
            self, test_admin: AsyncClient
    ) -> None:
        """Discard requires reason parameter."""
        response = await test_admin.delete(
            "/api/v1/dlq/messages/some-event-id"
        )
        assert response.status_code == 422


class TestGetDLQTopics:
    """Tests for GET /api/v1/dlq/topics."""

    @pytest.mark.asyncio
    async def test_get_dlq_topics(self, test_admin: AsyncClient) -> None:
        """Get DLQ topics summary."""
        response = await test_admin.get("/api/v1/dlq/topics")

        assert response.status_code == 200
        topics = [
            DLQTopicSummaryResponse.model_validate(t)
            for t in response.json()
        ]

        for topic in topics:
            assert topic.topic
            assert topic.total_messages >= 0
            assert topic.avg_retry_count >= 0
            assert topic.max_retry_count >= 0

    @pytest.mark.asyncio
    async def test_get_dlq_topics_unauthenticated(
            self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/dlq/topics")
        assert response.status_code == 401
