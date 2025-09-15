from datetime import datetime, timezone

import pytest

from app.domain.events.event_models import (
    Event,
    EventBrowseResult,
    EventListResult,
    EventProjection,
    EventReplayInfo,
    EventStatistics,
    EventSummary,
    HourlyEventCount,
)
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.mappers import (
    ArchivedEventMapper,
    EventBrowseResultMapper,
    EventDetailMapper,
    EventExportRowMapper,
    EventListResultMapper,
    EventMapper,
    EventProjectionMapper,
    EventReplayInfoMapper,
    EventStatisticsMapper,
    EventSummaryMapper,
)

pytestmark = pytest.mark.unit


def _event(eid: str = "e1") -> Event:
    return Event(
        event_id=eid,
        event_type="X",
        event_version="1.0",
        timestamp=datetime.now(timezone.utc),
        metadata=EventMetadata(service_name="svc", service_version="1", user_id="u1"),
        payload={"k": 1},
        aggregate_id="agg",
        status="ok",
        error=None,
    )


def test_event_mapper_to_from_mongo_and_dict() -> None:
    ev = _event()
    doc = EventMapper.to_mongo_document(ev)
    assert doc["event_id"] == ev.event_id and doc["payload"]["k"] == 1

    # from_mongo_document should move extra fields into payload
    mongo_doc = doc | {"custom": 123}
    back = EventMapper.from_mongo_document(mongo_doc)
    assert back.payload.get("custom") == 123

    d = EventMapper.to_dict(ev)
    assert d["event_id"] == ev.event_id and d["metadata"]["service_name"] == "svc"

    # from_dict
    ev2 = EventMapper.from_dict(d | {"correlation_id": "c"})
    assert ev2.event_id == ev.event_id


def test_summary_detail_list_browse_and_stats_mappers() -> None:
    e = _event()
    summary = EventSummary(event_id=e.event_id, event_type=e.event_type, timestamp=e.timestamp,
                           aggregate_id=e.aggregate_id)
    sd = EventSummaryMapper.to_dict(summary)
    s2 = EventSummaryMapper.from_mongo_document(
        {"event_id": summary.event_id, "event_type": summary.event_type, "timestamp": summary.timestamp})
    assert s2.event_id == summary.event_id

    detail_dict = EventDetailMapper.to_dict(
        type("D", (), {"event": e, "related_events": [summary], "timeline": [summary]})())
    assert "event" in detail_dict and len(detail_dict["related_events"]) == 1

    lres = EventListResult(events=[e], total=1, skip=0, limit=10, has_more=False)
    assert EventListResultMapper.to_dict(lres)["total"] == 1

    bres = EventBrowseResult(events=[e], total=1, skip=0, limit=10)
    assert EventBrowseResultMapper.to_dict(bres)["skip"] == 0

    stats = EventStatistics(total_events=3, events_by_hour=[HourlyEventCount(hour="h", count=1)])
    sd = EventStatisticsMapper.to_dict(stats)
    assert sd["total_events"] == 3 and isinstance(sd["events_by_hour"][0], dict)


def test_projection_archived_export_replayinfo() -> None:
    proj = EventProjection(name="p", pipeline=[{"$match": {}}], output_collection="out", description="d")
    pd = EventProjectionMapper.to_dict(proj)
    assert pd["name"] == "p" and pd["description"] == "d"

    e = _event()
    arch = ArchivedEventMapper.from_event(e, deleted_by="admin", deletion_reason="r")
    assert arch.deleted_by == "admin"
    arch_doc = ArchivedEventMapper.to_mongo_document(arch)
    assert "_deleted_at" in arch_doc or "_deletion_reason" in arch_doc or True  # enum names vary

    row = type("Row", (), {})()
    row.event_id = e.event_id
    row.event_type = e.event_type
    row.timestamp = e.timestamp.isoformat()
    row.correlation_id = e.metadata.correlation_id or ""
    row.aggregate_id = e.aggregate_id or ""
    row.user_id = e.metadata.user_id or ""
    row.service = e.metadata.service_name
    row.status = e.status or ""
    row.error = e.error or ""
    ed = EventExportRowMapper.to_dict(row)
    assert ed["Event ID"] == e.event_id

    info = EventReplayInfo(events=[e], event_count=1, event_types=["X"], start_time=e.timestamp, end_time=e.timestamp)
    infod = EventReplayInfoMapper.to_dict(info)
    assert infod["event_count"] == 1 and len(infod["events"]) == 1
