import asyncio

import pytest
from app.domain.enums.events import EventType
from app.domain.enums.replay import ReplayStatus
from app.domain.events.typed import DomainEvent
from app.schemas_pydantic.admin_events import (
    EventBrowseRequest,
    EventBrowseResponse,
    EventDeleteResponse,
    EventDetailResponse,
    EventFilter,
    EventReplayRequest,
    EventReplayResponse,
    EventReplayStatusResponse,
    EventStatsResponse,
)
from app.schemas_pydantic.execution import ExecutionRequest, ExecutionResponse
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.admin, pytest.mark.kafka]


async def wait_for_events(
    client: AsyncClient,
    aggregate_id: str,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
) -> list[DomainEvent]:
    """Poll until at least one event exists for the aggregate.

    Args:
        client: Admin HTTP client
        aggregate_id: Execution ID to get events for
        timeout: Maximum time to wait in seconds
        poll_interval: Time between polls in seconds

    Returns:
        List of events for the aggregate

    Raises:
        TimeoutError: If no events appear within timeout
        AssertionError: If API returns unexpected status code
    """
    deadline = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < deadline:
        request = EventBrowseRequest(
            filters=EventFilter(aggregate_id=aggregate_id),
            limit=10,
        )
        response = await client.post(
            "/api/v1/admin/events/browse", json=request.model_dump()
        )
        assert response.status_code == 200, f"Unexpected: {response.status_code} - {response.text}"

        result = EventBrowseResponse.model_validate(response.json())
        if result.events:
            return result.events

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"No events appeared for aggregate {aggregate_id} within {timeout}s")


class TestBrowseEvents:
    """Tests for POST /api/v1/admin/events/browse."""

    @pytest.mark.asyncio
    async def test_browse_events(self, test_admin: AsyncClient) -> None:
        """Admin can browse events."""
        request = EventBrowseRequest(
            filters=EventFilter(),
            skip=0,
            limit=50,
            sort_by="timestamp",
            sort_order=-1,
        )
        response = await test_admin.post(
            "/api/v1/admin/events/browse", json=request.model_dump()
        )

        assert response.status_code == 200
        result = EventBrowseResponse.model_validate(response.json())

        assert result.total >= 0
        assert result.skip == 0
        assert result.limit == 50
        assert isinstance(result.events, list)

    @pytest.mark.asyncio
    async def test_browse_events_with_event_type_filter(
        self, test_admin: AsyncClient, created_execution_admin: ExecutionResponse
    ) -> None:
        """Browse events filtered by event type."""
        await wait_for_events(test_admin, created_execution_admin.execution_id)

        request = EventBrowseRequest(
            filters=EventFilter(event_types=[EventType.EXECUTION_REQUESTED]),
            skip=0,
            limit=20,
        )
        response = await test_admin.post(
            "/api/v1/admin/events/browse", json=request.model_dump()
        )

        assert response.status_code == 200
        result = EventBrowseResponse.model_validate(response.json())
        assert isinstance(result.events, list)
        assert result.total >= 1

    @pytest.mark.asyncio
    async def test_browse_events_with_pagination(
        self, test_admin: AsyncClient
    ) -> None:
        """Pagination works for event browsing."""
        request = EventBrowseRequest(
            filters=EventFilter(),
            skip=10,
            limit=25,
        )
        response = await test_admin.post(
            "/api/v1/admin/events/browse", json=request.model_dump()
        )

        assert response.status_code == 200
        result = EventBrowseResponse.model_validate(response.json())
        assert result.skip == 10
        assert result.limit == 25

    @pytest.mark.asyncio
    async def test_browse_events_with_aggregate_filter(
        self, test_admin: AsyncClient, created_execution_admin: ExecutionResponse
    ) -> None:
        """Browse events filtered by aggregate ID."""
        await wait_for_events(test_admin, created_execution_admin.execution_id)

        request = EventBrowseRequest(
            filters=EventFilter(aggregate_id=created_execution_admin.execution_id),
            limit=50,
        )
        response = await test_admin.post(
            "/api/v1/admin/events/browse", json=request.model_dump()
        )

        assert response.status_code == 200
        result = EventBrowseResponse.model_validate(response.json())
        assert result.total >= 1
        assert len(result.events) >= 1

    @pytest.mark.asyncio
    async def test_browse_events_with_search_text(
        self, test_admin: AsyncClient
    ) -> None:
        """Browse events with text search."""
        request = EventBrowseRequest(
            filters=EventFilter(search_text="execution"),
            limit=20,
        )
        response = await test_admin.post(
            "/api/v1/admin/events/browse", json=request.model_dump()
        )

        assert response.status_code == 200
        result = EventBrowseResponse.model_validate(response.json())
        assert isinstance(result.events, list)

    @pytest.mark.asyncio
    async def test_browse_events_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot browse admin events."""
        response = await test_user.post(
            "/api/v1/admin/events/browse",
            json={"filters": {}, "limit": 10},
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_browse_events_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.post(
            "/api/v1/admin/events/browse",
            json={"filters": {}, "limit": 10},
        )

        assert response.status_code == 401


class TestEventStats:
    """Tests for GET /api/v1/admin/events/stats."""

    @pytest.mark.asyncio
    async def test_get_event_stats(self, test_admin: AsyncClient) -> None:
        """Admin can get event statistics."""
        response = await test_admin.get("/api/v1/admin/events/stats")

        assert response.status_code == 200
        stats = EventStatsResponse.model_validate(response.json())

        assert stats.total_events >= 0
        assert isinstance(stats.events_by_type, list)
        assert isinstance(stats.events_by_hour, list)
        assert isinstance(stats.top_users, list)
        assert stats.error_rate >= 0.0
        assert stats.avg_processing_time >= 0.0

    @pytest.mark.asyncio
    async def test_get_event_stats_with_hours(
        self, test_admin: AsyncClient
    ) -> None:
        """Get event statistics for specific time period."""
        response = await test_admin.get(
            "/api/v1/admin/events/stats",
            params={"hours": 48},
        )

        assert response.status_code == 200
        stats = EventStatsResponse.model_validate(response.json())
        assert stats.total_events >= 0

    @pytest.mark.asyncio
    async def test_get_event_stats_max_hours(
        self, test_admin: AsyncClient
    ) -> None:
        """Get event statistics for maximum time period (168 hours)."""
        response = await test_admin.get(
            "/api/v1/admin/events/stats",
            params={"hours": 168},
        )

        assert response.status_code == 200
        stats = EventStatsResponse.model_validate(response.json())
        assert isinstance(stats.events_by_hour, list)

    @pytest.mark.asyncio
    async def test_get_event_stats_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot get event stats."""
        response = await test_user.get("/api/v1/admin/events/stats")

        assert response.status_code == 403


class TestExportEventsCSV:
    """Tests for GET /api/v1/admin/events/export/csv."""

    @pytest.mark.asyncio
    async def test_export_events_csv(self, test_admin: AsyncClient) -> None:
        """Admin can export events as CSV."""
        response = await test_admin.get("/api/v1/admin/events/export/csv")

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/csv" in content_type or "application/octet-stream" in content_type
        content_disposition = response.headers.get("content-disposition", "")
        assert "attachment" in content_disposition
        assert ".csv" in content_disposition

        body_csv = response.text
        assert "Event ID" in body_csv
        assert "Timestamp" in body_csv

    @pytest.mark.asyncio
    async def test_export_events_csv_with_filters(
        self, test_admin: AsyncClient
    ) -> None:
        """Export CSV with event type filters."""
        response = await test_admin.get(
            "/api/v1/admin/events/export/csv",
            params={
                "event_types": [EventType.EXECUTION_REQUESTED],
                "limit": 100,
            },
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_export_events_csv_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot export events."""
        response = await test_user.get("/api/v1/admin/events/export/csv")

        assert response.status_code == 403


class TestExportEventsJSON:
    """Tests for GET /api/v1/admin/events/export/json."""

    @pytest.mark.asyncio
    async def test_export_events_json(self, test_admin: AsyncClient) -> None:
        """Admin can export events as JSON."""
        response = await test_admin.get("/api/v1/admin/events/export/json")

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type or "application/octet-stream" in content_type
        content_disposition = response.headers.get("content-disposition", "")
        assert "attachment" in content_disposition
        assert ".json" in content_disposition

        data = response.json()
        assert "export_metadata" in data
        assert "events" in data
        assert isinstance(data["events"], list)
        assert "exported_at" in data["export_metadata"]

    @pytest.mark.asyncio
    async def test_export_events_json_with_filters(
        self, test_admin: AsyncClient
    ) -> None:
        """Export JSON with comprehensive filters."""
        response = await test_admin.get(
            "/api/v1/admin/events/export/json",
            params={
                "event_types": [EventType.EXECUTION_REQUESTED, EventType.EXECUTION_STARTED],
                "limit": 500,
            },
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_export_events_json_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot export events."""
        response = await test_user.get("/api/v1/admin/events/export/json")

        assert response.status_code == 403


class TestGetEventDetail:
    """Tests for GET /api/v1/admin/events/{event_id}."""

    @pytest.mark.asyncio
    async def test_get_event_detail(
        self, test_admin: AsyncClient, created_execution_admin: ExecutionResponse
    ) -> None:
        """Admin can get event details."""
        events = await wait_for_events(test_admin, created_execution_admin.execution_id)
        event_id = events[0].event_id

        response = await test_admin.get(f"/api/v1/admin/events/{event_id}")

        assert response.status_code == 200
        detail = EventDetailResponse.model_validate(response.json())

        assert detail.event is not None
        assert isinstance(detail.related_events, list)
        assert isinstance(detail.timeline, list)

    @pytest.mark.asyncio
    async def test_get_event_detail_not_found(
        self, test_admin: AsyncClient
    ) -> None:
        """Get nonexistent event returns 404."""
        response = await test_admin.get(
            "/api/v1/admin/events/nonexistent-event-id"
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_event_detail_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot get event details."""
        response = await test_user.get("/api/v1/admin/events/some-event-id")

        assert response.status_code == 403


class TestReplayEvents:
    """Tests for POST /api/v1/admin/events/replay."""

    @pytest.mark.asyncio
    async def test_replay_events_dry_run(
        self, test_admin: AsyncClient, created_execution_admin: ExecutionResponse
    ) -> None:
        """Admin can replay events in dry run mode."""
        await wait_for_events(test_admin, created_execution_admin.execution_id)

        request = EventReplayRequest(
            aggregate_id=created_execution_admin.execution_id,
            dry_run=True,
        )
        response = await test_admin.post(
            "/api/v1/admin/events/replay", json=request.model_dump()
        )

        assert response.status_code == 200
        result = EventReplayResponse.model_validate(response.json())
        assert result.dry_run is True
        assert result.total_events >= 1
        assert result.replay_correlation_id is not None
        assert result.status == ReplayStatus.PREVIEW

    @pytest.mark.asyncio
    async def test_replay_events_no_events_found(
        self, test_admin: AsyncClient
    ) -> None:
        """Replay with non-matching filter returns 404."""
        request = EventReplayRequest(
            correlation_id="nonexistent-correlation-id-12345",
            dry_run=True,
        )
        response = await test_admin.post(
            "/api/v1/admin/events/replay", json=request.model_dump()
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_replay_events_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot replay events."""
        response = await test_user.post(
            "/api/v1/admin/events/replay",
            json={"aggregate_id": "test", "dry_run": True},
        )

        assert response.status_code == 403


class TestGetReplayStatus:
    """Tests for GET /api/v1/admin/events/replay/{session_id}/status."""

    @pytest.mark.asyncio
    async def test_get_replay_status_not_found(
        self, test_admin: AsyncClient
    ) -> None:
        """Get nonexistent replay session returns 404."""
        response = await test_admin.get(
            "/api/v1/admin/events/replay/nonexistent-session/status"
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_replay_status_after_replay(
        self, test_admin: AsyncClient, simple_execution_request: ExecutionRequest
    ) -> None:
        """Get replay status after starting a replay."""
        exec_response = await test_admin.post(
            "/api/v1/execute", json=simple_execution_request.model_dump()
        )
        assert exec_response.status_code == 200

        execution = ExecutionResponse.model_validate(exec_response.json())
        await wait_for_events(test_admin, execution.execution_id)

        request = EventReplayRequest(
            aggregate_id=execution.execution_id,
            dry_run=False,
        )
        replay_response = await test_admin.post(
            "/api/v1/admin/events/replay", json=request.model_dump()
        )
        assert replay_response.status_code == 200

        replay_result = EventReplayResponse.model_validate(replay_response.json())
        assert replay_result.session_id is not None

        status_response = await test_admin.get(
            f"/api/v1/admin/events/replay/{replay_result.session_id}/status"
        )

        assert status_response.status_code == 200
        status = EventReplayStatusResponse.model_validate(status_response.json())
        assert status.session_id == replay_result.session_id
        # After scheduling a replay (dry_run=False), status is SCHEDULED or RUNNING if it started quickly
        assert status.status in (ReplayStatus.SCHEDULED, ReplayStatus.RUNNING)
        assert status.total_events >= 1
        assert status.replayed_events >= 0
        assert status.progress_percentage >= 0.0

    @pytest.mark.asyncio
    async def test_get_replay_status_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot get replay status."""
        response = await test_user.get(
            "/api/v1/admin/events/replay/some-session/status"
        )

        assert response.status_code == 403


class TestDeleteEvent:
    """Tests for DELETE /api/v1/admin/events/{event_id}."""

    @pytest.mark.asyncio
    async def test_delete_event(
        self, test_admin: AsyncClient, simple_execution_request: ExecutionRequest
    ) -> None:
        """Admin can delete an event."""
        exec_response = await test_admin.post(
            "/api/v1/execute", json=simple_execution_request.model_dump()
        )
        assert exec_response.status_code == 200

        execution = ExecutionResponse.model_validate(exec_response.json())
        events = await wait_for_events(test_admin, execution.execution_id)
        event_id = events[0].event_id

        response = await test_admin.delete(f"/api/v1/admin/events/{event_id}")

        assert response.status_code == 200
        result = EventDeleteResponse.model_validate(response.json())
        assert result.event_id == event_id
        assert "deleted" in result.message.lower()

        verify_response = await test_admin.get(f"/api/v1/admin/events/{event_id}")
        assert verify_response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_event_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot delete events."""
        response = await test_user.delete(
            "/api/v1/admin/events/some-event-id"
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_event_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.delete("/api/v1/admin/events/some-event-id")

        assert response.status_code == 401
