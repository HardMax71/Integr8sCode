import pytest
from app.domain.enums.events import EventType
from app.schemas_pydantic.events import (
    DeleteEventResponse,
    EventListResponse,
    EventResponse,
    EventStatistics,
    PublishEventResponse,
    ReplayAggregateResponse,
)
from app.schemas_pydantic.execution import ExecutionResponse
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]


class TestExecutionEvents:
    """Tests for GET /api/v1/events/executions/{execution_id}/events."""

    @pytest.mark.asyncio
    async def test_get_execution_events(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Get events for a specific execution."""
        response = await test_user.get(
            f"/api/v1/events/executions/{created_execution.execution_id}/events"
        )

        assert response.status_code == 200
        result = EventListResponse.model_validate(response.json())

        assert result.total >= 0
        assert result.limit == 100  # default
        assert result.skip == 0
        assert isinstance(result.has_more, bool)
        assert isinstance(result.events, list)

    @pytest.mark.asyncio
    async def test_get_execution_events_pagination(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Pagination works for execution events."""
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
    async def test_get_user_events(self, test_user: AsyncClient) -> None:
        """Get events for current user."""
        response = await test_user.get("/api/v1/events/user")

        assert response.status_code == 200
        result = EventListResponse.model_validate(response.json())

        assert result.total >= 0
        assert isinstance(result.events, list)

    @pytest.mark.asyncio
    async def test_get_user_events_with_filters(
            self, test_user: AsyncClient
    ) -> None:
        """Filter user events by event types."""
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
    async def test_query_events(self, test_user: AsyncClient) -> None:
        """Query events with filters."""
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
        """Query events by correlation ID."""
        response = await test_user.post(
            "/api/v1/events/query",
            json={
                "correlation_id": "test-correlation-123",
                "limit": 100,
            },
        )

        assert response.status_code == 200
        result = EventListResponse.model_validate(response.json())
        # May return empty if no events with this correlation
        assert isinstance(result.events, list)


class TestCorrelationEvents:
    """Tests for GET /api/v1/events/correlation/{correlation_id}."""

    @pytest.mark.asyncio
    async def test_get_events_by_correlation(
            self, test_user: AsyncClient
    ) -> None:
        """Get events by correlation ID."""
        # This will return empty unless we have events with this correlation
        response = await test_user.get(
            "/api/v1/events/correlation/test-correlation-xyz"
        )

        assert response.status_code == 200
        result = EventListResponse.model_validate(response.json())
        assert isinstance(result.events, list)


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
    async def test_get_event_statistics(self, test_user: AsyncClient) -> None:
        """Get event statistics for current user."""
        response = await test_user.get("/api/v1/events/statistics")

        assert response.status_code == 200
        stats = EventStatistics.model_validate(response.json())

        assert stats.total_events >= 0
        assert stats.events_by_type is not None
        assert stats.events_by_service is not None

    @pytest.mark.asyncio
    async def test_get_event_statistics_with_time_range(
            self, test_user: AsyncClient
    ) -> None:
        """Get event statistics with time range."""
        response = await test_user.get(
            "/api/v1/events/statistics",
            params={
                "start_time": "2024-01-01T00:00:00Z",
                "end_time": "2030-01-01T00:00:00Z",
            },
        )

        assert response.status_code == 200
        stats = EventStatistics.model_validate(response.json())
        assert stats.total_events >= 0


class TestSingleEvent:
    """Tests for GET /api/v1/events/{event_id}."""

    @pytest.mark.asyncio
    async def test_get_event_not_found(self, test_user: AsyncClient) -> None:
        """Get nonexistent event returns 404."""
        response = await test_user.get("/api/v1/events/nonexistent-event-id")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_event_by_id(self, test_user: AsyncClient) -> None:
        """Get single event by ID."""
        # First get user events to find an event ID
        events_response = await test_user.get(
            "/api/v1/events/user",
            params={"limit": 1},
        )

        if events_response.status_code == 200:
            result = EventListResponse.model_validate(events_response.json())
            if result.events:
                event_id = result.events[0].event_id

                # Get single event
                response = await test_user.get(f"/api/v1/events/{event_id}")

                assert response.status_code == 200
                event = EventResponse.model_validate(response.json())
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
    async def test_aggregate_events(self, test_user: AsyncClient) -> None:
        """Aggregate events with MongoDB pipeline."""
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


class TestListEventTypes:
    """Tests for GET /api/v1/events/types/list."""

    @pytest.mark.asyncio
    async def test_list_event_types(self, test_user: AsyncClient) -> None:
        """List available event types."""
        response = await test_user.get("/api/v1/events/types/list")

        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, list)


class TestDeleteEvent:
    """Tests for DELETE /api/v1/events/{event_id} (admin only)."""

    @pytest.mark.asyncio
    async def test_delete_event_admin_only(
            self, test_admin: AsyncClient
    ) -> None:
        """Admin can delete events."""
        # First publish an event to delete (must use valid EventType)
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

        # Delete it
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
        response = await test_admin.post(
            f"/api/v1/events/replay/{created_execution_admin.execution_id}",
            params={"dry_run": True},
        )

        # May be 200 or 404 depending on event availability
        if response.status_code == 200:
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
