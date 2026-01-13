from datetime import datetime
from typing import TypedDict

import pytest
from app.dlq import AgeStatistics, DLQMessageStatus, EventTypeStatistic, TopicStatistic
from app.schemas_pydantic.dlq import (
    DLQBatchRetryResponse,
    DLQMessageDetail,
    DLQMessageResponse,
    DLQMessagesResponse,
    DLQStats,
    DLQTopicSummaryResponse,
)
from app.schemas_pydantic.user import MessageResponse
from app.settings import Settings
from httpx import AsyncClient


class _RetryRequest(TypedDict):
    event_ids: list[str]


@pytest.mark.integration
class TestDLQRoutes:
    """Test DLQ endpoints against real backend."""

    @pytest.mark.asyncio
    async def test_dlq_requires_authentication(self, client: AsyncClient) -> None:
        """Test that DLQ endpoints require authentication."""
        # Try to access DLQ stats without auth
        response = await client.get("/api/v1/dlq/stats")
        assert response.status_code == 401

        error_data = response.json()
        assert "detail" in error_data
        assert any(word in error_data["detail"].lower()
                   for word in ["not authenticated", "unauthorized", "login"])

    @pytest.mark.asyncio
    async def test_get_dlq_statistics(self, test_user: AsyncClient) -> None:
        """Test getting DLQ statistics."""
        # Get DLQ stats
        response = await test_user.get("/api/v1/dlq/stats")
        assert response.status_code == 200

        # Validate response structure
        stats_data = response.json()
        stats = DLQStats(**stats_data)

        # Verify structure - using typed models
        assert isinstance(stats.by_status, dict)
        assert isinstance(stats.by_topic, list)
        assert isinstance(stats.by_event_type, list)
        assert isinstance(stats.age_stats, AgeStatistics)
        assert stats.timestamp is not None

        # Check status breakdown - iterate over actual enum values
        for status in DLQMessageStatus:
            if status in stats.by_status:
                assert isinstance(stats.by_status[status], int)
                assert stats.by_status[status] >= 0

        # Check topic stats - now typed as TopicStatistic
        for topic_stat in stats.by_topic:
            assert isinstance(topic_stat, TopicStatistic)
            assert topic_stat.count >= 0

        # Check event type stats - now typed as EventTypeStatistic
        for event_type_stat in stats.by_event_type:
            assert isinstance(event_type_stat, EventTypeStatistic)
            assert event_type_stat.count >= 0

        # Check age stats - now typed as AgeStatistics
        assert stats.age_stats.min_age_seconds >= 0
        assert stats.age_stats.max_age_seconds >= 0
        assert stats.age_stats.avg_age_seconds >= 0

    @pytest.mark.asyncio
    async def test_list_dlq_messages(self, test_user: AsyncClient) -> None:
        """Test listing DLQ messages with filters."""
        # List all DLQ messages
        response = await test_user.get("/api/v1/dlq/messages?limit=10&offset=0")
        assert response.status_code == 200

        # Validate response structure
        messages_data = response.json()
        messages_response = DLQMessagesResponse(**messages_data)

        # Verify pagination
        assert isinstance(messages_response.messages, list)
        assert isinstance(messages_response.total, int)
        assert messages_response.limit == 10
        assert messages_response.offset == 0
        assert messages_response.total >= 0

        # If there are messages, validate their structure
        for message in messages_response.messages:
            assert isinstance(message, DLQMessageResponse)
            assert message.event.event_id is not None
            assert message.event.event_type is not None
            assert message.original_topic is not None
            assert message.retry_count >= 0
            assert message.failed_at is not None
            assert message.status in DLQMessageStatus.__members__.values()

    @pytest.mark.asyncio
    async def test_filter_dlq_messages_by_status(self, test_user: AsyncClient) -> None:
        """Test filtering DLQ messages by status."""
        # Test different status filters
        for status in ["pending", "scheduled", "retried", "discarded"]:
            response = await test_user.get(f"/api/v1/dlq/messages?status={status}&limit=5")
            assert response.status_code == 200

            messages_data = response.json()
            messages_response = DLQMessagesResponse(**messages_data)

            # All returned messages should have the requested status
            for message in messages_response.messages:
                assert message.status == status

    @pytest.mark.asyncio
    async def test_filter_dlq_messages_by_topic(self, test_user: AsyncClient) -> None:
        """Test filtering DLQ messages by topic."""
        # Filter by a specific topic
        test_topic = "execution-events"
        response = await test_user.get(f"/api/v1/dlq/messages?topic={test_topic}&limit=5")
        assert response.status_code == 200

        messages_data = response.json()
        messages_response = DLQMessagesResponse(**messages_data)

        # All returned messages should be from the requested topic
        for message in messages_response.messages:
            assert message.original_topic == test_topic

    @pytest.mark.asyncio
    async def test_get_single_dlq_message_detail(self, test_user: AsyncClient) -> None:
        """Test getting detailed information for a single DLQ message."""
        # First get list of messages to find an ID
        list_response = await test_user.get("/api/v1/dlq/messages?limit=1")
        assert list_response.status_code == 200

        messages_data = list_response.json()
        if messages_data["total"] > 0 and messages_data["messages"]:
            # Get details for the first message
            event_id = messages_data["messages"][0]["event_id"]

            detail_response = await test_user.get(f"/api/v1/dlq/messages/{event_id}")
            assert detail_response.status_code == 200

            # Validate detailed response
            detail_data = detail_response.json()
            message_detail = DLQMessageDetail(**detail_data)

            # Verify all fields are present - event is DomainEvent with event_id/event_type
            assert message_detail.event is not None
            assert message_detail.event.event_id == event_id
            assert message_detail.event.event_type is not None
            assert message_detail.original_topic is not None
            assert message_detail.error is not None
            assert message_detail.retry_count >= 0
            assert message_detail.failed_at is not None
            assert message_detail.status in DLQMessageStatus.__members__.values()
            assert message_detail.created_at is not None
            assert message_detail.last_updated is not None

            # Optional fields
            if message_detail.producer_id:
                assert isinstance(message_detail.producer_id, str)
            if message_detail.dlq_offset is not None:
                assert message_detail.dlq_offset >= 0
            if message_detail.dlq_partition is not None:
                assert message_detail.dlq_partition >= 0

    @pytest.mark.asyncio
    async def test_get_nonexistent_dlq_message(self, test_user: AsyncClient) -> None:
        """Test getting a non-existent DLQ message."""
        # Try to get non-existent message
        fake_event_id = "00000000-0000-0000-0000-000000000000"
        response = await test_user.get(f"/api/v1/dlq/messages/{fake_event_id}")
        assert response.status_code == 404

        error_data = response.json()
        assert "detail" in error_data
        assert "not found" in error_data["detail"].lower()

    @pytest.mark.asyncio
    async def test_set_retry_policy(
            self, test_user: AsyncClient, test_settings: Settings
    ) -> None:
        """Test setting a retry policy for a topic."""
        # Set retry policy
        topic = f"{test_settings.KAFKA_TOPIC_PREFIX}test-topic"
        policy_data = {
            "topic": topic,
            "strategy": "exponential_backoff",
            "max_retries": 5,
            "base_delay_seconds": 10,
            "max_delay_seconds": 3600,
            "retry_multiplier": 2.0
        }

        response = await test_user.post("/api/v1/dlq/retry-policy", json=policy_data)
        assert response.status_code == 200

        # Validate response
        result_data = response.json()
        result = MessageResponse(**result_data)
        assert "retry policy set" in result.message.lower()
        assert topic in result.message

    @pytest.mark.asyncio
    async def test_retry_dlq_messages_batch(self, test_user: AsyncClient) -> None:
        """Test retrying a batch of DLQ messages."""
        # Get some failed messages to retry
        list_response = await test_user.get("/api/v1/dlq/messages?status=discarded&limit=3")
        assert list_response.status_code == 200

        messages_data = list_response.json()
        if messages_data["total"] > 0 and messages_data["messages"]:
            # Collect event IDs to retry
            event_ids = [msg["event_id"] for msg in messages_data["messages"][:2]]

            # Retry the messages
            retry_request = {
                "event_ids": event_ids
            }

            retry_response = await test_user.post("/api/v1/dlq/retry", json=retry_request)
            assert retry_response.status_code == 200

            # Validate retry response
            retry_data = retry_response.json()
            batch_result = DLQBatchRetryResponse(**retry_data)

            assert batch_result.total == len(event_ids)
            assert batch_result.successful >= 0
            assert batch_result.failed >= 0
            assert batch_result.successful + batch_result.failed == batch_result.total

            # Check details if present
            if batch_result.details:
                assert isinstance(batch_result.details, list)
                for detail in batch_result.details:
                    assert isinstance(detail, dict)
                    assert "event_id" in detail
                    assert "success" in detail

    @pytest.mark.asyncio
    async def test_discard_dlq_message(self, test_user: AsyncClient) -> None:
        """Test discarding a DLQ message."""
        # Get a failed message to discard
        list_response = await test_user.get("/api/v1/dlq/messages?status=discarded&limit=1")
        assert list_response.status_code == 200

        messages_data = list_response.json()
        if messages_data["total"] > 0 and messages_data["messages"]:
            event_id = messages_data["messages"][0]["event_id"]

            # Discard the message
            discard_reason = "Test discard - message unrecoverable"
            discard_response = await test_user.delete(
                f"/api/v1/dlq/messages/{event_id}?reason={discard_reason}"
            )
            assert discard_response.status_code == 200

            # Validate response
            result_data = discard_response.json()
            result = MessageResponse(**result_data)
            assert "discarded" in result.message.lower()
            assert event_id in result.message

            # Verify message is now discarded
            detail_response = await test_user.get(f"/api/v1/dlq/messages/{event_id}")
            if detail_response.status_code == 200:
                detail_data = detail_response.json()
                # Status should be discarded
                assert detail_data["status"] == "discarded"

    @pytest.mark.asyncio
    async def test_get_dlq_topics_summary(self, test_user: AsyncClient) -> None:
        """Test getting DLQ topics summary."""
        # Get topics summary
        response = await test_user.get("/api/v1/dlq/topics")
        assert response.status_code == 200

        # Validate response
        topics_data = response.json()
        assert isinstance(topics_data, list)

        for topic_data in topics_data:
            topic_summary = DLQTopicSummaryResponse(**topic_data)

            # Verify structure
            assert topic_summary.topic is not None
            assert isinstance(topic_summary.total_messages, int)
            assert topic_summary.total_messages >= 0
            assert isinstance(topic_summary.status_breakdown, dict)

            # Check status breakdown
            for status, count in topic_summary.status_breakdown.items():
                assert status in ["pending", "scheduled", "retried", "discarded"]
                assert isinstance(count, int)
                assert count >= 0

            # Check dates if present (may be str or datetime)
            if topic_summary.oldest_message:
                assert isinstance(topic_summary.oldest_message, (str, datetime))
            if topic_summary.newest_message:
                assert isinstance(topic_summary.newest_message, (str, datetime))

            # Check retry stats
            if topic_summary.avg_retry_count is not None:
                assert topic_summary.avg_retry_count >= 0
            if topic_summary.max_retry_count is not None:
                assert topic_summary.max_retry_count >= 0

    @pytest.mark.asyncio
    async def test_dlq_message_pagination(self, test_user: AsyncClient) -> None:
        """Test DLQ message pagination."""
        # Get first page
        page1_response = await test_user.get("/api/v1/dlq/messages?limit=5&offset=0")
        assert page1_response.status_code == 200

        page1_data = page1_response.json()
        page1 = DLQMessagesResponse(**page1_data)

        # If there are more than 5 messages, get second page
        if page1.total > 5:
            page2_response = await test_user.get("/api/v1/dlq/messages?limit=5&offset=5")
            assert page2_response.status_code == 200

            page2_data = page2_response.json()
            page2 = DLQMessagesResponse(**page2_data)

            # Verify pagination
            assert page2.offset == 5
            assert page2.limit == 5
            assert page2.total == page1.total

            # Messages should be different
            if page1.messages and page2.messages:
                page1_ids = {msg.event.event_id for msg in page1.messages}
                page2_ids = {msg.event.event_id for msg in page2.messages}
                # Should have no overlap
                assert len(page1_ids.intersection(page2_ids)) == 0

    @pytest.mark.asyncio
    async def test_dlq_error_handling(self, test_user: AsyncClient) -> None:
        """Test DLQ error handling for invalid requests."""
        # Test invalid limit
        response = await test_user.get("/api/v1/dlq/messages?limit=10000")  # Too high
        # Should either accept with max limit or reject
        assert response.status_code in [200, 400, 422]

        # Test negative offset
        response = await test_user.get("/api/v1/dlq/messages?limit=10&offset=-1")
        assert response.status_code in [400, 422]

        # Test invalid status filter
        response = await test_user.get("/api/v1/dlq/messages?status=invalid_status")
        assert response.status_code in [400, 422]

        # Test retry with empty list
        retry_request: _RetryRequest = {
            "event_ids": []
        }
        response = await test_user.post("/api/v1/dlq/retry", json=retry_request)
        # Should handle gracefully or reject invalid input
        assert response.status_code in [200, 400, 404, 422]

        # Test discard without reason
        fake_event_id = "00000000-0000-0000-0000-000000000000"
        response = await test_user.delete(f"/api/v1/dlq/messages/{fake_event_id}")
        # Should require reason parameter
        assert response.status_code in [400, 422, 404]
