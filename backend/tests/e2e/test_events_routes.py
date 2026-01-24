import asyncio

import pytest
from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent
from app.schemas_pydantic.events import (
    DeleteEventResponse,
    EventListResponse,
    EventStatistics,
    PublishEventRequest,
    PublishEventResponse,
    ReplayAggregateResponse,
)
from app.schemas_pydantic.execution import ExecutionResponse
from httpx import AsyncClient
from pydantic import TypeAdapter

DomainEventAdapter: TypeAdapter[DomainEvent] = TypeAdapter(DomainEvent)

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]


async def wait_for_user_events(
        client: AsyncClient,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
) -> EventListResponse:
    """Poll until at least one event exists for the user.

    Args:
        client: Authenticated HTTP client
        timeout: Maximum time to wait in seconds
        poll_interval: Time between polls in seconds

    Returns:
        EventListResponse with at least one event

    Raises:
        TimeoutError: If no events appear within timeout
        AssertionError: If API returns unexpected status code
    """
    deadline = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < deadline:
        response = await client.get("/api/v1/events/user", params={"limit": 10})
        assert response.status_code == 200, f"Unexpected: {response.status_code} - {response.text}"

        result = EventListResponse.model_validate(response.json())
        if result.events:
            return result

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"No events appeared for user within {timeout}s")


async def wait_for_aggregate_events(
        client: AsyncClient,
        aggregate_id: str,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
) -> EventListResponse:
    """Poll until at least one event exists for the aggregate.

    Args:
        client: Authenticated HTTP client
        aggregate_id: Aggregate ID (execution_id) to check
        timeout: Maximum time to wait in seconds
        poll_interval: Time between polls in seconds

    Returns:
        EventListResponse with at least one event

    Raises:
        TimeoutError: If no events appear within timeout
        AssertionError: If API returns unexpected status code
    """
    deadline = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < deadline:
        response = await client.get(
            f"/api/v1/events/executions/{aggregate_id}/events",
            params={"limit": 10},
        )
        assert response.status_code == 200, f"Unexpected: {response.status_code} - {response.text}"

        result = EventListResponse.model_validate(response.json())
        if result.events:
            return result

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"No events appeared for aggregate {aggregate_id} within {timeout}s")


class TestExecutionEvents:
    """Tests for GET /api/v1/events/executions/{execution_id}/events."""

    @pytest.mark.asyncio
    async def test_get_execution_events(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Get events for a specific execution."""
        result = await wait_for_aggregate_events(test_user, created_execution.execution_id)

        assert result.total >= 1
        assert result.limit == 10
        assert result.skip == 0
        assert isinstance(result.has_more, bool)
        assert len(result.events) >= 1

    @pytest.mark.asyncio
    async def test_get_execution_events_pagination(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Pagination works for execution events."""
        await wait_for_aggregate_events(test_user, created_execution.execution_id)

        response = await test_user.get(
            f"/api/v1/events/executions/{created_execution.execution_id}/events",
            params={"limit": 5, "skip": 0},
        )

        assert response.status_code == 200
        result = EventListResponse.model_validate(response.json())
        assert result.limit == 5
        assert result.skip == 0

    @pytest.mark.asyncio
    async def test_get_execution_events_access_denied(
            self, test_user: AsyncClient, another_user: AsyncClient,
            created_execution: ExecutionResponse
    ) -> None:
        """Cannot access another user's execution events."""
        response = await another_user.get(
            f"/api/v1/events/executions/{created_execution.execution_id}/events"
        )

        assert response.status_code == 403


class TestUserEvents:
    """Tests for GET /api/v1/events/user."""

    @pytest.mark.asyncio
    async def test_get_user_events(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Get events for current user."""
        result = await wait_for_user_events(test_user)

        assert result.total >= 1
        assert len(result.events) >= 1

    @pytest.mark.asyncio
    async def test_get_user_events_with_filters(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Filter user events by event types."""
        await wait_for_user_events(test_user)

        response = await test_user.get(
            "/api/v1/events/user",
            params={
                "event_types": [EventType.EXECUTION_REQUESTED],
                "limit": 10,
            },
        )

        assert response.status_code == 200
        result = EventListResponse.model_validate(response.json())
        assert result.limit == 10

    @pytest.mark.asyncio
    async def test_get_user_events_unauthenticated(
            self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/events/user")
        assert response.status_code == 401


class TestQueryEvents:
    """Tests for POST /api/v1/events/query."""

    @pytest.mark.asyncio
    async def test_query_events(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Query events with filters."""
        await wait_for_user_events(test_user)

        response = await test_user.post(
            "/api/v1/events/query",
            json={
                "event_types": [EventType.EXECUTION_REQUESTED],
                "limit": 50,
                "skip": 0,
            },
        )

        assert response.status_code == 200
        result = EventListResponse.model_validate(response.json())
        assert result.limit == 50

    @pytest.mark.asyncio
    async def test_query_events_with_correlation_id(
            self, test_user: AsyncClient
    ) -> None:
        """Query events by correlation ID returns empty for nonexistent."""
        response = await test_user.post(
            "/api/v1/events/query",
            json={
                "correlation_id": "nonexistent-correlation-123",
                "limit": 100,
            },
        )

        assert response.status_code == 200
        result = EventListResponse.model_validate(response.json())
        assert isinstance(result.events, list)
        assert result.total == 0


class TestCorrelationEvents:
    """Tests for GET /api/v1/events/correlation/{correlation_id}."""

    @pytest.mark.asyncio
    async def test_get_events_by_nonexistent_correlation(
            self, test_user: AsyncClient
    ) -> None:
        """Get events by nonexistent correlation ID returns empty."""
        response = await test_user.get(
            "/api/v1/events/correlation/nonexistent-correlation-xyz"
        )

        assert response.status_code == 200
        result = EventListResponse.model_validate(response.json())
        assert isinstance(result.events, list)
        assert result.total == 0


class TestCurrentRequestEvents:
    """Tests for GET /api/v1/events/current-request."""

    @pytest.mark.asyncio
    async def test_get_current_request_events(
            self, test_user: AsyncClient
    ) -> None:
        """Get events for current request correlation."""
        response = await test_user.get("/api/v1/events/current-request")

        assert response.status_code == 200
        result = EventListResponse.model_validate(response.json())
        assert isinstance(result.events, list)


class TestEventStatistics:
    """Tests for GET /api/v1/events/statistics."""

    @pytest.mark.asyncio
    async def test_get_event_statistics(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Get event statistics for current user."""
        await wait_for_user_events(test_user)

        response = await test_user.get("/api/v1/events/statistics")

        assert response.status_code == 200
        stats = EventStatistics.model_validate(response.json())

        assert stats.total_events >= 1
        assert stats.events_by_type is not None
        assert stats.events_by_service is not None

    @pytest.mark.asyncio
    async def test_get_event_statistics_with_time_range(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Get event statistics with time range."""
        await wait_for_user_events(test_user)

        response = await test_user.get(
            "/api/v1/events/statistics",
            params={
                "start_time": "2024-01-01T00:00:00Z",
                "end_time": "2030-01-01T00:00:00Z",
            },
        )

        assert response.status_code == 200
        stats = EventStatistics.model_validate(response.json())
        assert stats.total_events >= 1


class TestSingleEvent:
    """Tests for GET /api/v1/events/{event_id}."""

    @pytest.mark.asyncio
    async def test_get_event_not_found(self, test_user: AsyncClient) -> None:
        """Get nonexistent event returns 404."""
        response = await test_user.get("/api/v1/events/nonexistent-event-id")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_event_by_id(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Get single event by ID."""
        events_result = await wait_for_user_events(test_user)
        event_id = events_result.events[0].event_id

        response = await test_user.get(f"/api/v1/events/{event_id}")

        assert response.status_code == 200
        event = DomainEventAdapter.validate_python(response.json())
        assert event.event_id == event_id


class TestPublishEvent:
    """Tests for POST /api/v1/events/publish (admin only)."""

    @pytest.mark.asyncio
    async def test_publish_event_admin_only(
            self, test_admin: AsyncClient
    ) -> None:
        """Admin can publish custom events."""
        response = await test_admin.post(
            "/api/v1/events/publish",
            json={
                "event_type": EventType.SYSTEM_ERROR,
                "payload": {
                    "error_type": "test_error",
                    "message": "Test error message",
                    "service_name": "test-service",
                },
                "aggregate_id": "test-aggregate-123",
            },
        )

        assert response.status_code == 200
        result = PublishEventResponse.model_validate(response.json())
        assert result.event_id is not None
        assert result.status == "published"
        assert result.timestamp is not None

    @pytest.mark.asyncio
    async def test_publish_event_forbidden_for_user(
            self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot publish events."""
        response = await test_user.post(
            "/api/v1/events/publish",
            json={
                "event_type": EventType.SYSTEM_ERROR,
                "payload": {
                    "error_type": "test_error",
                    "message": "Test error message",
                    "service_name": "test-service",
                },
            },
        )

        assert response.status_code == 403


class TestAggregateEvents:
    """Tests for POST /api/v1/events/aggregate."""

    @pytest.mark.asyncio
    async def test_aggregate_events(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Aggregate events with MongoDB pipeline."""
        await wait_for_user_events(test_user)

        response = await test_user.post(
            "/api/v1/events/aggregate",
            json={
                "pipeline": [
                    {"$group": {"_id": "$event_type", "count": {"$sum": 1}}}
                ],
                "limit": 100,
            },
        )

        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, list)
        assert len(result) >= 1


class TestListEventTypes:
    """Tests for GET /api/v1/events/types/list."""

    @pytest.mark.asyncio
    async def test_list_event_types(self, test_admin: AsyncClient) -> None:
        """List available event types."""
        # First create an event so there's at least one type (requires admin)
        request = PublishEventRequest(
            event_type=EventType.SCRIPT_SAVED,
            payload={
                "script_id": "test-script",
                "user_id": "test-user",
                "title": "Test Script",
                "language": "python",
            },
        )
        await test_admin.post("/api/v1/events/publish", json=request.model_dump())

        # Query with admin (admins can see all events, users only see their own)
        response = await test_admin.get("/api/v1/events/types/list")

        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, list)
        assert len(result) > 0


class TestDeleteEvent:
    """Tests for DELETE /api/v1/events/{event_id} (admin only)."""

    @pytest.mark.asyncio
    async def test_delete_event_admin_only(
            self, test_admin: AsyncClient
    ) -> None:
        """Admin can delete events."""
        publish_response = await test_admin.post(
            "/api/v1/events/publish",
            json={
                "event_type": EventType.SYSTEM_ERROR,
                "payload": {
                    "error_type": "test_delete_error",
                    "message": "Event to be deleted",
                    "service_name": "test-service",
                },
                "aggregate_id": "delete-test-agg",
            },
        )

        assert publish_response.status_code == 200
        event_id = publish_response.json()["event_id"]

        delete_response = await test_admin.delete(
            f"/api/v1/events/{event_id}"
        )

        assert delete_response.status_code == 200
        result = DeleteEventResponse.model_validate(delete_response.json())
        assert result.event_id == event_id
        assert "deleted" in result.message.lower()

    @pytest.mark.asyncio
    async def test_delete_event_forbidden_for_user(
            self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot delete events."""
        response = await test_user.delete("/api/v1/events/some-event-id")

        assert response.status_code == 403


class TestReplayAggregateEvents:
    """Tests for POST /api/v1/events/replay/{aggregate_id}."""

    @pytest.mark.asyncio
    async def test_replay_events_dry_run(
            self, test_admin: AsyncClient, created_execution_admin: ExecutionResponse
    ) -> None:
        """Replay events in dry run mode."""
        await wait_for_aggregate_events(test_admin, created_execution_admin.execution_id)

        response = await test_admin.post(
            f"/api/v1/events/replay/{created_execution_admin.execution_id}",
            params={"dry_run": True},
        )

        assert response.status_code == 200
        result = ReplayAggregateResponse.model_validate(response.json())
        assert result.dry_run is True
        assert result.aggregate_id == created_execution_admin.execution_id

    @pytest.mark.asyncio
    async def test_replay_events_not_found(
            self, test_admin: AsyncClient
    ) -> None:
        """Replay nonexistent aggregate returns 404."""
        response = await test_admin.post(
            "/api/v1/events/replay/nonexistent-aggregate",
            params={"dry_run": True},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_replay_events_forbidden_for_user(
            self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot replay events."""
        response = await test_user.post(
            "/api/v1/events/replay/some-aggregate",
            params={"dry_run": True},
        )

        assert response.status_code == 403


class TestEventIsolation:
    """Tests for event access isolation between users."""

    @pytest.mark.asyncio
    async def test_user_cannot_access_other_users_events(
            self,
            test_user: AsyncClient,
            another_user: AsyncClient,
            created_execution: ExecutionResponse,
    ) -> None:
        """User cannot access another user's execution events."""
        await wait_for_aggregate_events(test_user, created_execution.execution_id)

        response = await another_user.get(
            f"/api/v1/events/executions/{created_execution.execution_id}/events"
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_user_events_only_shows_own_events(
            self,
            test_user: AsyncClient,
            another_user: AsyncClient,
            created_execution: ExecutionResponse,
    ) -> None:
        """User events endpoint only returns user's own events."""
        events_result = await wait_for_user_events(test_user)
        user_event_ids = {e.event_id for e in events_result.events}

        another_response = await another_user.get("/api/v1/events/user")
        assert another_response.status_code == 200

        another_result = EventListResponse.model_validate(another_response.json())
        another_event_ids = {e.event_id for e in another_result.events}

        assert user_event_ids.isdisjoint(another_event_ids)
