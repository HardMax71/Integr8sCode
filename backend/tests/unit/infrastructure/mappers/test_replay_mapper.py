import pytest
from datetime import datetime, timezone, timedelta

from app.infrastructure.mappers.replay_mapper import (
    ReplayQueryMapper,
    ReplaySessionDataMapper,
    ReplaySessionMapper,
)
from app.domain.admin.replay_models import (
    ReplayQuery,
    ReplaySession,
    ReplaySessionStatus,
    ReplaySessionStatusDetail,
)
from app.domain.events.event_models import EventSummary


pytestmark = pytest.mark.unit


def _session() -> ReplaySession:
    return ReplaySession(
        session_id="s1",
        status=ReplaySessionStatus.SCHEDULED,
        total_events=10,
        correlation_id="c",
        created_at=datetime.now(timezone.utc),
        dry_run=True,
    )


def test_replay_session_mapper_roundtrip_and_status_helpers() -> None:
    s = _session()
    d = ReplaySessionMapper.to_dict(s)
    s2 = ReplaySessionMapper.from_dict(d)
    assert s2.session_id == s.session_id and s2.status == s.status

    info = ReplaySessionMapper.to_status_info(s2)
    di = ReplaySessionMapper.status_info_to_dict(info)
    assert di["session_id"] == s.session_id and di["status"] == s.status.value

    detail = ReplaySessionStatusDetail(session=s2, estimated_completion=datetime.now(timezone.utc))
    dd = ReplaySessionMapper.status_detail_to_dict(detail)
    assert dd["session_id"] == s.session_id and "execution_results" in dd


def test_replay_query_mapper() -> None:
    q = ReplayQuery(event_ids=["e1"], correlation_id="x", aggregate_id="a")
    mq = ReplayQueryMapper.to_mongodb_query(q)
    assert "event_id" in mq and mq["metadata.correlation_id"] == "x" and mq["aggregate_id"] == "a"

    # time window
    q2 = ReplayQuery(start_time=datetime.now(timezone.utc), end_time=datetime.now(timezone.utc))
    mq2 = ReplayQueryMapper.to_mongodb_query(q2)
    assert "timestamp" in mq2 and "$gte" in mq2["timestamp"] and "$lte" in mq2["timestamp"]


def test_replay_session_data_mapper() -> None:
    es = [EventSummary(event_id="e1", event_type="X", timestamp=datetime.now(timezone.utc))]
    from app.domain.admin.replay_models import ReplaySessionData
    data = ReplaySessionData(total_events=1, replay_correlation_id="rc", dry_run=True, query={"x": 1}, events_preview=es)
    dd = ReplaySessionDataMapper.to_dict(data)
    assert dd["dry_run"] is True and len(dd.get("events_preview", [])) == 1

