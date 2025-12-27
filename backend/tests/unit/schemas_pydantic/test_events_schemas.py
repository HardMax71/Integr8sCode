import math
from datetime import datetime, timezone, timedelta

import pytest

from app.domain.enums.common import SortOrder
from app.domain.enums.events import EventType
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.schemas_pydantic.events import (
    EventAggregationRequest,
    EventBase,
    EventFilterRequest,
    EventInDB,
    EventListResponse,
    EventProjection,
    EventQuery,
    EventResponse,
    EventStatistics,
    PublishEventRequest,
    PublishEventResponse,
    ResourceUsage,
)


def test_event_filter_request_sort_validator_accepts_allowed_fields():
    req = EventFilterRequest(sort_by="timestamp", sort_order=SortOrder.DESC)
    assert req.sort_by == "timestamp"

    for field in ("event_type", "aggregate_id", "correlation_id", "stored_at"):
        req2 = EventFilterRequest(sort_by=field)
        assert req2.sort_by == field


def test_event_filter_request_sort_validator_rejects_invalid():
    with pytest.raises(ValueError):
        EventFilterRequest(sort_by="not-a-field")


def test_event_base_and_in_db_defaults_and_metadata():
    meta = AvroEventMetadata(service_name="tests", service_version="1.0", user_id="u1")
    ev = EventBase(
        event_type=EventType.EXECUTION_REQUESTED,
        metadata=meta,
        payload={"execution_id": "e1"},
    )
    assert ev.event_id and ev.timestamp.tzinfo is not None
    edb = EventInDB(**ev.model_dump())
    assert isinstance(edb.stored_at, datetime)
    assert isinstance(edb.ttl_expires_at, datetime)
    # ttl should be after stored_at by ~30 days
    assert edb.ttl_expires_at > edb.stored_at


def test_publish_event_request_and_response():
    req = PublishEventRequest(
        event_type=EventType.EXECUTION_REQUESTED,
        payload={"x": 1},
        aggregate_id="agg",
    )
    assert req.event_type is EventType.EXECUTION_REQUESTED
    resp = PublishEventResponse(event_id="e", status="queued", timestamp=datetime.now(timezone.utc))
    assert resp.status == "queued"


def test_event_query_schema_and_list_response():
    q = EventQuery(
        event_types=[EventType.EXECUTION_REQUESTED, EventType.POD_CREATED],
        user_id="u1",
        start_time=datetime.now(timezone.utc) - timedelta(hours=1),
        end_time=datetime.now(timezone.utc),
        limit=50,
        skip=0,
    )
    assert len(q.event_types or []) == 2 and q.limit == 50

    # Minimal list response compose/decompose
    er = EventResponse(
        event_id="id",
        event_type=EventType.POD_CREATED,
        event_version="1.0",
        timestamp=datetime.now(timezone.utc),
        metadata={},
        payload={},
    )
    lst = EventListResponse(events=[er], total=1, limit=1, skip=0, has_more=False)
    assert lst.total == 1 and not lst.has_more


def test_event_projection_and_statistics_examples():
    proj = EventProjection(
        name="exec_summary",
        source_events=[EventType.EXECUTION_REQUESTED, EventType.EXECUTION_COMPLETED],
        aggregation_pipeline=[{"$match": {"event_type": str(EventType.EXECUTION_REQUESTED)}}],
        output_collection="summary",
    )
    assert proj.refresh_interval_seconds == 300

    stats = EventStatistics(
        total_events=2,
        events_by_type={str(EventType.EXECUTION_REQUESTED): 1},
        events_by_service={"svc": 2},
        events_by_hour=[{"hour": "2025-01-01 00:00", "count": 2}],
    )
    assert stats.total_events == 2


def test_resource_usage_schema():
    ru = ResourceUsage(cpu_seconds=1.5, memory_mb_seconds=256.0, disk_io_mb=10.0, network_io_mb=5.0)
    dumped = ru.model_dump()
    assert math.isclose(dumped["cpu_seconds"], 1.5)

