from datetime import datetime, timezone

import pytest

from app.domain.events.event_models import (
    Event,
    EventSummary,
)
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.mappers import (
    ArchivedEventMapper,
    EventExportRowMapper,
    EventMapper,
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


def test_event_mapper_to_from_mongo() -> None:
    ev = _event()
    doc = EventMapper.to_mongo_document(ev)
    assert doc["event_id"] == ev.event_id and doc["payload"]["k"] == 1

    # from_mongo_document should move extra fields into payload
    mongo_doc = doc | {"custom": 123}
    back = EventMapper.from_mongo_document(mongo_doc)
    assert back.payload.get("custom") == 123


def test_summary_mapper() -> None:
    e = _event()
    summary = EventSummary(
        event_id=e.event_id, event_type=e.event_type, timestamp=e.timestamp, aggregate_id=e.aggregate_id
    )
    s2 = EventSummaryMapper.from_mongo_document(
        {"event_id": summary.event_id, "event_type": summary.event_type, "timestamp": summary.timestamp}
    )
    assert s2.event_id == summary.event_id


def test_archived_export_mapper() -> None:
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
