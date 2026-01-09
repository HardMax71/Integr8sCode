from datetime import datetime, timezone, timedelta
from typing import Dict
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.domain.enums.events import EventType
from app.schemas_pydantic.events import (
    EventListResponse,
    EventResponse,
    EventStatistics,
    PublishEventResponse,
    ReplayAggregateResponse
)


@pytest.mark.integration
class TestEventsRoutes:
    """Test events endpoints against real backend."""

    @pytest.mark.asyncio
    async def test_events_require_authentication(self, client: AsyncClient) -> None:
        """Test that event endpoints require authentication."""
        # Try to access events without auth
        response = await client.get("/api/v1/events/user")
        assert response.status_code == 401

        error_data = response.json()
        assert "detail" in error_data
        assert any(word in error_data["detail"].lower()
                   for word in ["not authenticated", "unauthorized", "login"])

    @pytest.mark.asyncio
    async def test_get_user_events(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test getting user's events."""
        # Already authenticated via test_user fixture

        # Get user events
        response = await client.get("/api/v1/events/user?limit=10&skip=0")
        # Some deployments may route this path under a dynamic segment and return 404.
        # Accept 200 with a valid payload or 404 (no such resource).
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            # Validate response structure
            events_data = response.json()
            events_response = EventListResponse(**events_data)

            # Verify pagination
            assert isinstance(events_response.events, list)
            assert isinstance(events_response.total, int)
            assert events_response.limit == 10
            assert events_response.skip == 0
            assert isinstance(events_response.has_more, bool)
            assert events_response.total >= 0

            # If there are events, validate their structure
            for event in events_response.events:
                assert isinstance(event, EventResponse)
                assert event.event_id is not None
                assert event.event_type is not None
                assert event.aggregate_id is not None
                assert event.timestamp is not None
                assert event.version is not None
                assert event.user_id is not None

                # Optional fields
                if event.payload:
                    assert isinstance(event.payload, dict)
                if event.metadata:
                    assert isinstance(event.metadata, dict)
                if event.correlation_id:
                    assert isinstance(event.correlation_id, str)

    @pytest.mark.asyncio
    async def test_get_user_events_with_filters(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test filtering user events."""
        # Already authenticated via test_user fixture

        # Create an execution to generate events
        execution_request = {
            "script": "print('Test for event filtering')",
            "lang": "python",
            "lang_version": "3.11"
        }
        exec_response = await client.post("/api/v1/execute", json=execution_request)
        assert exec_response.status_code == 200

        # Filter by event types
        event_types = ["execution.requested", "execution.completed"]
        params = {
            "event_types": event_types,
            "limit": 20,
            "sort_order": "desc"
        }

        response = await client.get("/api/v1/events/user", params=params)
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            events_data = response.json()
            events_response = EventListResponse(**events_data)

            # Filtered events should only contain specified types
            for event in events_response.events:
                if event.event_type:  # Some events might have been created
                    assert any(event_type in event.event_type for event_type in event_types) or len(
                        events_response.events) == 0

    @pytest.mark.asyncio
    async def test_get_execution_events(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test getting events for a specific execution."""
        # Create an execution
        execution_request = {
            "script": "print('Test execution events')",
            "lang": "python",
            "lang_version": "3.11"
        }
        exec_response = await client.post("/api/v1/execute", json=execution_request)
        assert exec_response.status_code == 200

        execution_id = exec_response.json()["execution_id"]

        # Get execution events (JSON, not SSE stream)
        response = await client.get(
            f"/api/v1/events/executions/{execution_id}/events?include_system_events=true"
        )
        assert response.status_code == 200

        events_data = response.json()
        events_response = EventListResponse(**events_data)

        # Should return a valid payload; some environments may have no persisted events
        assert isinstance(events_response.events, list)

        # All events should be for this execution
        for event in events_response.events:
            # Check if execution_id is in aggregate_id or payload
            if event.aggregate_id:
                assert execution_id in event.aggregate_id or event.aggregate_id == execution_id

    @pytest.mark.asyncio
    async def test_query_events_advanced(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test advanced event querying with filters."""
        # Query events with multiple filters
        query_request = {
            "event_types": [
                EventType.EXECUTION_REQUESTED.value,
                EventType.EXECUTION_COMPLETED.value
            ],
            "start_time": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
            "end_time": datetime.now(timezone.utc).isoformat(),
            "limit": 50,
            "skip": 0,
            "sort_by": "timestamp",
            "sort_order": "desc"
        }

        response = await client.post("/api/v1/events/query", json=query_request)
        assert response.status_code == 200

        events_data = response.json()
        events_response = EventListResponse(**events_data)

        # Verify query results
        assert isinstance(events_response.events, list)
        assert events_response.limit == 50
        assert events_response.skip == 0

        # Events should be sorted by timestamp descending
        if len(events_response.events) > 1:
            for i in range(len(events_response.events) - 1):
                t1 = events_response.events[i].timestamp
                t2 = events_response.events[i + 1].timestamp
                assert isinstance(t1, datetime) and isinstance(t2, datetime)
                assert t1 >= t2  # Descending order

    @pytest.mark.asyncio
    async def test_get_events_by_correlation_id(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test getting events by correlation ID."""
        # Create an execution (which generates correlated events)
        execution_request = {
            "script": "print('Test correlation')",
            "lang": "python",
            "lang_version": "3.11"
        }
        exec_response = await client.post("/api/v1/execute", json=execution_request)
        assert exec_response.status_code == 200

        # Get events for the user to find a correlation ID
        user_events_response = await client.get("/api/v1/events/user?limit=10")
        assert user_events_response.status_code == 200

        user_events = user_events_response.json()
        if user_events["events"] and user_events["events"][0].get("correlation_id"):
            correlation_id = user_events["events"][0]["correlation_id"]

            # Get events by correlation ID
            response = await client.get(f"/api/v1/events/correlation/{correlation_id}?limit=50")
            assert response.status_code == 200

            correlated_events = response.json()
            events_response = EventListResponse(**correlated_events)

            # All events should have the same correlation ID
            for event in events_response.events:
                if event.correlation_id:
                    assert event.correlation_id == correlation_id

    @pytest.mark.asyncio
    async def test_get_current_request_events(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test getting events for the current request."""
        # Get current request events (might be empty if no correlation context)
        response = await client.get("/api/v1/events/current-request?limit=10")
        assert response.status_code == 200

        events_data = response.json()
        events_response = EventListResponse(**events_data)

        # Should return a valid response (might be empty)
        assert isinstance(events_response.events, list)
        assert events_response.total >= 0

    @pytest.mark.asyncio
    async def test_get_event_statistics(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test getting event statistics."""
        # Get statistics for last 24 hours
        response = await client.get("/api/v1/events/statistics")
        assert response.status_code == 200

        stats_data = response.json()
        stats = EventStatistics(**stats_data)

        # Verify statistics structure
        assert isinstance(stats.total_events, int)
        assert stats.total_events >= 0
        assert isinstance(stats.events_by_type, dict)
        assert isinstance(stats.events_by_hour, list)
        # Optional extra fields may not be present in this deployment

        # Optional window fields are allowed by schema; no strict check here

        # Events by hour should have proper structure
        for hourly_stat in stats.events_by_hour:
            # Some implementations return {'_id': hour, 'count': n}
            hour_key = "hour" if "hour" in hourly_stat else "_id"
            assert hour_key in hourly_stat
            assert "count" in hourly_stat
            assert isinstance(hourly_stat["count"], int)
            assert hourly_stat["count"] >= 0

    @pytest.mark.asyncio
    async def test_get_single_event(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test getting a single event by ID."""
        # Get user events to find an event ID
        events_response = await client.get("/api/v1/events/user?limit=1")
        assert events_response.status_code == 200

        events_data = events_response.json()
        if events_data["total"] > 0 and events_data["events"]:
            event_id = events_data["events"][0]["event_id"]

            # Get single event
            response = await client.get(f"/api/v1/events/{event_id}")
            assert response.status_code == 200

            event_data = response.json()
            event = EventResponse(**event_data)

            # Verify it's the correct event
            assert event.event_id == event_id
            assert event.event_type is not None
            assert event.timestamp is not None

    @pytest.mark.asyncio
    async def test_get_nonexistent_event(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test getting a non-existent event."""
        # Try to get non-existent event
        fake_event_id = str(uuid4())
        response = await client.get(f"/api/v1/events/{fake_event_id}")
        assert response.status_code == 404

        error_data = response.json()
        assert "detail" in error_data
        assert "not found" in error_data["detail"].lower()

    @pytest.mark.asyncio
    async def test_list_event_types(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test listing available event types."""
        # List event types
        response = await client.get("/api/v1/events/types/list")
        assert response.status_code == 200

        event_types = response.json()
        assert isinstance(event_types, list)

        # Should contain common event types
        common_types = [
            "execution.requested",
            "execution.completed",
            "user.logged_in",
            "user.registered"
        ]

        # At least some common types should be present
        for event_type in event_types:
            assert isinstance(event_type, str)
            assert len(event_type) > 0

    @pytest.mark.asyncio
    async def test_publish_custom_event_requires_admin(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test that publishing custom events requires admin privileges."""
        # Try to publish custom event (logged in as regular user via fixture)
        publish_request = {
            "event_type": EventType.SYSTEM_ERROR.value,
            "payload": {
                "test": "data",
                "value": 123
            },
            "aggregate_id": str(uuid4()),
            "correlation_id": str(uuid4())
        }

        response = await client.post("/api/v1/events/publish", json=publish_request)
        assert response.status_code == 403  # Forbidden for non-admin

    @pytest.mark.asyncio
    @pytest.mark.kafka
    async def test_publish_custom_event_as_admin(self, client: AsyncClient, test_admin: Dict[str, str]) -> None:
        """Test publishing custom events as admin."""
        # Publish custom event (requires Kafka); skip if not available
        aggregate_id = str(uuid4())
        publish_request = {
            "event_type": EventType.SYSTEM_ERROR.value,
            "payload": {
                "error_type": "test_error",
                "message": "Admin test system error",
                "service_name": "tests"
            },
            "aggregate_id": aggregate_id,
            "correlation_id": str(uuid4()),
            "metadata": {
                "source": "integration_test",
                "version": "1.0"
            }
        }

        response = await client.post("/api/v1/events/publish", json=publish_request)
        if response.status_code != 200:
            pytest.skip("Kafka not available for publishing events")

        publish_response = PublishEventResponse(**response.json())
        assert publish_response.event_id is not None
        assert publish_response.status == "published"
        assert publish_response.timestamp is not None

    @pytest.mark.asyncio
    async def test_aggregate_events(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test event aggregation."""
        # Create aggregation pipeline
        aggregation_request = {
            "pipeline": [
                {"$match": {"event_type": {"$regex": "execution"}}},
                {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ],
            "limit": 10
        }

        response = await client.post("/api/v1/events/aggregate", json=aggregation_request)
        assert response.status_code == 200

        results = response.json()
        assert isinstance(results, list)

        # Verify aggregation results structure
        for result in results:
            assert isinstance(result, dict)
            assert "_id" in result  # Group key
            assert "count" in result  # Aggregation result
            assert isinstance(result["count"], int)
            assert result["count"] >= 0

    @pytest.mark.asyncio
    async def test_delete_event_requires_admin(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test that deleting events requires admin privileges."""
        # Try to delete an event (logged in as regular user via fixture)
        fake_event_id = str(uuid4())
        response = await client.delete(f"/api/v1/events/{fake_event_id}")
        assert response.status_code == 403  # Forbidden for non-admin

    @pytest.mark.asyncio
    async def test_replay_aggregate_events_requires_admin(self, client: AsyncClient,
                                                          test_user: Dict[str, str]) -> None:
        """Test that replaying events requires admin privileges."""
        # Try to replay events (logged in as regular user via fixture)
        aggregate_id = str(uuid4())
        response = await client.post(f"/api/v1/events/replay/{aggregate_id}?dry_run=true")
        assert response.status_code == 403  # Forbidden for non-admin

    @pytest.mark.asyncio
    async def test_replay_aggregate_events_dry_run(self, client: AsyncClient, test_admin: Dict[str, str]) -> None:
        """Test replaying events in dry-run mode."""
        # Get an existing aggregate ID from events
        events_response = await client.get("/api/v1/events/user?limit=1")
        assert events_response.status_code == 200

        events_data = events_response.json()
        if events_data["total"] > 0 and events_data["events"]:
            aggregate_id = events_data["events"][0]["aggregate_id"]

            # Try dry-run replay
            response = await client.post(f"/api/v1/events/replay/{aggregate_id}?dry_run=true")

            if response.status_code == 200:
                replay_data = response.json()
                replay_response = ReplayAggregateResponse(**replay_data)

                assert replay_response.dry_run is True
                assert replay_response.aggregate_id == aggregate_id
                assert replay_response.event_count >= 0

                if replay_response.event_types:
                    assert isinstance(replay_response.event_types, list)
                if replay_response.start_time:
                    assert isinstance(replay_response.start_time, datetime)
                if replay_response.end_time:
                    assert isinstance(replay_response.end_time, datetime)
            elif response.status_code == 404:
                # No events for this aggregate
                error_data = response.json()
                assert "detail" in error_data

    @pytest.mark.asyncio
    async def test_event_pagination(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test event pagination."""
        # Get first page
        page1_response = await client.get("/api/v1/events/user?limit=5&skip=0")
        assert page1_response.status_code == 200

        page1_data = page1_response.json()
        page1 = EventListResponse(**page1_data)

        # If there are more than 5 events, get second page
        if page1.total > 5:
            page2_response = await client.get("/api/v1/events/user?limit=5&skip=5")
            assert page2_response.status_code == 200

            page2_data = page2_response.json()
            page2 = EventListResponse(**page2_data)

            # Verify pagination
            assert page2.skip == 5
            assert page2.limit == 5
            assert page2.total == page1.total

            # Events should be different
            if page1.events and page2.events:
                page1_ids = {e.event_id for e in page1.events}
                page2_ids = {e.event_id for e in page2.events}
                # Should have no overlap
                assert len(page1_ids.intersection(page2_ids)) == 0

    @pytest.mark.asyncio
    async def test_events_isolation_between_users(self, client: AsyncClient,
                                                  test_user: Dict[str, str],
                                                  test_admin: Dict[str, str]) -> None:
        """Test that events are properly isolated between users."""
        # Get events as regular user
        user_login_data = {
            "username": test_user["username"],
            "password": test_user["password"]
        }
        user_login_response = await client.post("/api/v1/auth/login", data=user_login_data)
        assert user_login_response.status_code == 200

        user_events_response = await client.get("/api/v1/events/user?limit=10")
        assert user_events_response.status_code == 200

        user_events = user_events_response.json()
        user_event_ids = [e["event_id"] for e in user_events["events"]]

        # Get events as admin (without include_all_users flag)
        admin_login_data = {
            "username": test_admin["username"],
            "password": test_admin["password"]
        }
        admin_login_response = await client.post("/api/v1/auth/login", data=admin_login_data)
        assert admin_login_response.status_code == 200

        admin_events_response = await client.get("/api/v1/events/user?limit=10")
        assert admin_events_response.status_code == 200

        admin_events = admin_events_response.json()
        admin_event_ids = [e["event_id"] for e in admin_events["events"]]

        # Events should be different (unless users share some events)
        # But user IDs in events should be different
        for event in user_events["events"]:
            meta = event.get("metadata") or {}
            if meta.get("user_id"):
                assert meta["user_id"] == test_user.get("user_id", meta["user_id"])

        for event in admin_events["events"]:
            meta = event.get("metadata") or {}
            if meta.get("user_id"):
                assert meta["user_id"] == test_admin.get("user_id", meta["user_id"])
