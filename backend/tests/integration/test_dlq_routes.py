from typing import Dict

import pytest
from httpx import AsyncClient

from app.schemas_pydantic.dlq import (
    DLQStats,
    DLQMessagesResponse,
    DLQMessageResponse,
    DLQMessageDetail,
    DLQMessageStatus,
    DLQBatchRetryResponse,
    DLQTopicSummaryResponse
)
from app.schemas_pydantic.user import MessageResponse


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
    async def test_get_dlq_statistics(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test getting DLQ statistics."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Get DLQ stats
        response = await client.get("/api/v1/dlq/stats")
        assert response.status_code == 200

        # Validate response structure
        stats_data = response.json()
        stats = DLQStats(**stats_data)

        # Verify structure
        assert isinstance(stats.by_status, dict)
        assert isinstance(stats.by_topic, list)
        assert isinstance(stats.by_event_type, list)
        assert isinstance(stats.age_stats, dict)
        assert stats.timestamp is not None

        # Check status breakdown
        for status in ["pending", "retrying", "failed", "discarded"]:
            if status in stats.by_status:
                assert isinstance(stats.by_status[status], int)
                assert stats.by_status[status] >= 0

        # Check topic stats
        for topic_stat in stats.by_topic:
            assert "topic" in topic_stat
            assert "count" in topic_stat
            assert isinstance(topic_stat["count"], int)
            assert topic_stat["count"] >= 0

        # Check event type stats  
        for event_type_stat in stats.by_event_type:
            assert "event_type" in event_type_stat
            assert "count" in event_type_stat
            assert isinstance(event_type_stat["count"], int)
            assert event_type_stat["count"] >= 0

        # Check age stats
        if stats.age_stats:
            for key in ["min", "max", "avg", "median"]:
                if key in stats.age_stats:
                    assert isinstance(stats.age_stats[key], (int, float))
                    assert stats.age_stats[key] >= 0

    @pytest.mark.asyncio
    async def test_list_dlq_messages(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test listing DLQ messages with filters."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # List all DLQ messages
        response = await client.get("/api/v1/dlq/messages?limit=10&offset=0")
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
            assert message.event_id is not None
            assert message.event_type is not None
            assert message.original_topic is not None
            assert message.retry_count >= 0
            assert message.failed_at is not None
            assert message.status in DLQMessageStatus.__members__.values()

            # Check age_seconds is reasonable
            if message.age_seconds is not None:
                assert message.age_seconds >= 0

            # Check details if present
            if message.details:
                assert isinstance(message.details, dict)

    @pytest.mark.asyncio
    async def test_filter_dlq_messages_by_status(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test filtering DLQ messages by status."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Test different status filters
        for status in ["pending", "scheduled", "retried", "discarded"]:
            response = await client.get(f"/api/v1/dlq/messages?status={status}&limit=5")
            assert response.status_code == 200

            messages_data = response.json()
            messages_response = DLQMessagesResponse(**messages_data)

            # All returned messages should have the requested status
            for message in messages_response.messages:
                assert message.status == status

    @pytest.mark.asyncio
    async def test_filter_dlq_messages_by_topic(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test filtering DLQ messages by topic."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Filter by a specific topic
        test_topic = "execution-events"
        response = await client.get(f"/api/v1/dlq/messages?topic={test_topic}&limit=5")
        assert response.status_code == 200

        messages_data = response.json()
        messages_response = DLQMessagesResponse(**messages_data)

        # All returned messages should be from the requested topic
        for message in messages_response.messages:
            assert message.original_topic == test_topic

    @pytest.mark.asyncio
    async def test_get_single_dlq_message_detail(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test getting detailed information for a single DLQ message."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # First get list of messages to find an ID
        list_response = await client.get("/api/v1/dlq/messages?limit=1")
        assert list_response.status_code == 200

        messages_data = list_response.json()
        if messages_data["total"] > 0 and messages_data["messages"]:
            # Get details for the first message
            event_id = messages_data["messages"][0]["event_id"]

            detail_response = await client.get(f"/api/v1/dlq/messages/{event_id}")
            assert detail_response.status_code == 200

            # Validate detailed response
            detail_data = detail_response.json()
            message_detail = DLQMessageDetail(**detail_data)

            # Verify all fields are present
            assert message_detail.event_id == event_id
            assert message_detail.event is not None
            assert isinstance(message_detail.event, dict)
            assert message_detail.event_type is not None
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
    async def test_get_nonexistent_dlq_message(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test getting a non-existent DLQ message."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Try to get non-existent message
        fake_event_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(f"/api/v1/dlq/messages/{fake_event_id}")
        assert response.status_code == 404

        error_data = response.json()
        assert "detail" in error_data
        assert "not found" in error_data["detail"].lower()

    @pytest.mark.asyncio
    async def test_set_retry_policy(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test setting a retry policy for a topic."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Set retry policy
        policy_data = {
            "topic": "test-topic",
            "strategy": "exponential_backoff",
            "max_retries": 5,
            "base_delay_seconds": 10,
            "max_delay_seconds": 3600,
            "retry_multiplier": 2.0
        }

        response = await client.post("/api/v1/dlq/retry-policy", json=policy_data)
        assert response.status_code == 200

        # Validate response
        result_data = response.json()
        result = MessageResponse(**result_data)
        assert "retry policy set" in result.message.lower()
        assert policy_data["topic"] in result.message

    @pytest.mark.asyncio
    async def test_retry_dlq_messages_batch(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test retrying a batch of DLQ messages."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Get some failed messages to retry
        list_response = await client.get("/api/v1/dlq/messages?status=discarded&limit=3")
        assert list_response.status_code == 200

        messages_data = list_response.json()
        if messages_data["total"] > 0 and messages_data["messages"]:
            # Collect event IDs to retry
            event_ids = [msg["event_id"] for msg in messages_data["messages"][:2]]

            # Retry the messages
            retry_request = {
                "event_ids": event_ids
            }

            retry_response = await client.post("/api/v1/dlq/retry", json=retry_request)
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
    async def test_discard_dlq_message(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test discarding a DLQ message."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Get a failed message to discard
        list_response = await client.get("/api/v1/dlq/messages?status=discarded&limit=1")
        assert list_response.status_code == 200

        messages_data = list_response.json()
        if messages_data["total"] > 0 and messages_data["messages"]:
            event_id = messages_data["messages"][0]["event_id"]

            # Discard the message
            discard_reason = "Test discard - message unrecoverable"
            discard_response = await client.delete(
                f"/api/v1/dlq/messages/{event_id}?reason={discard_reason}"
            )
            assert discard_response.status_code == 200

            # Validate response
            result_data = discard_response.json()
            result = MessageResponse(**result_data)
            assert "discarded" in result.message.lower()
            assert event_id in result.message

            # Verify message is now discarded
            detail_response = await client.get(f"/api/v1/dlq/messages/{event_id}")
            if detail_response.status_code == 200:
                detail_data = detail_response.json()
                # Status should be discarded
                assert detail_data["status"] == "discarded"

    @pytest.mark.asyncio
    async def test_get_dlq_topics_summary(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test getting DLQ topics summary."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Get topics summary
        response = await client.get("/api/v1/dlq/topics")
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
                assert status in ["pending", "retrying", "failed", "discarded"]
                assert isinstance(count, int)
                assert count >= 0

            # Check dates if present
            if topic_summary.oldest_message:
                assert isinstance(topic_summary.oldest_message, str)
            if topic_summary.newest_message:
                assert isinstance(topic_summary.newest_message, str)

            # Check retry stats
            if topic_summary.avg_retry_count is not None:
                assert topic_summary.avg_retry_count >= 0
            if topic_summary.max_retry_count is not None:
                assert topic_summary.max_retry_count >= 0

    @pytest.mark.asyncio
    async def test_dlq_message_pagination(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test DLQ message pagination."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Get first page
        page1_response = await client.get("/api/v1/dlq/messages?limit=5&offset=0")
        assert page1_response.status_code == 200

        page1_data = page1_response.json()
        page1 = DLQMessagesResponse(**page1_data)

        # If there are more than 5 messages, get second page
        if page1.total > 5:
            page2_response = await client.get("/api/v1/dlq/messages?limit=5&offset=5")
            assert page2_response.status_code == 200

            page2_data = page2_response.json()
            page2 = DLQMessagesResponse(**page2_data)

            # Verify pagination
            assert page2.offset == 5
            assert page2.limit == 5
            assert page2.total == page1.total

            # Messages should be different
            if page1.messages and page2.messages:
                page1_ids = {msg.event_id for msg in page1.messages}
                page2_ids = {msg.event_id for msg in page2.messages}
                # Should have no overlap
                assert len(page1_ids.intersection(page2_ids)) == 0

    @pytest.mark.asyncio
    async def test_dlq_error_handling(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test DLQ error handling for invalid requests."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Test invalid limit
        response = await client.get("/api/v1/dlq/messages?limit=10000")  # Too high
        # Should either accept with max limit or reject
        assert response.status_code in [200, 400, 422]

        # Test negative offset
        response = await client.get("/api/v1/dlq/messages?limit=10&offset=-1")
        assert response.status_code in [400, 422]

        # Test invalid status filter
        response = await client.get("/api/v1/dlq/messages?status=invalid_status")
        assert response.status_code in [400, 422]

        # Test retry with empty list
        retry_request = {
            "event_ids": []
        }
        response = await client.post("/api/v1/dlq/retry", json=retry_request)
        # Should handle gracefully or reject invalid input
        assert response.status_code in [200, 400, 404, 422]

        # Test discard without reason
        fake_event_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(f"/api/v1/dlq/messages/{fake_event_id}")
        # Should require reason parameter
        assert response.status_code in [400, 422, 404]
