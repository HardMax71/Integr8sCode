from datetime import datetime, timezone

import pytest

from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga, SagaFilter, SagaInstance
from app.infrastructure.mappers import (
    SagaEventMapper,
    SagaFilterMapper,
    SagaInstanceMapper,
    SagaMapper,
    SagaResponseMapper,
)

pytestmark = pytest.mark.unit


def _saga() -> Saga:
    return Saga(
        saga_id="s1",
        saga_name="demo",
        execution_id="e1",
        state=SagaState.RUNNING,
        current_step="a",
        completed_steps=["a"],
        compensated_steps=[],
        context_data={"k": "v"},
        error_message=None,
    )


def test_saga_mapper_to_from_mongo_and_dict() -> None:
    s = _saga()
    m = SagaMapper()
    doc = m.to_mongo(s)
    s2 = m.from_mongo({**doc})
    assert s2.saga_id == s.saga_id and s2.state == s.state
    d = m.to_dict(s)
    assert d["state"] == SagaState.RUNNING.value and isinstance(d["created_at"], str)


def test_saga_response_mapper() -> None:
    s = _saga()
    rm = SagaResponseMapper()
    resp = rm.to_response(s)
    assert resp.saga_id == s.saga_id
    lst = rm.list_to_responses([s])
    assert len(lst) == 1 and lst[0].saga_id == s.saga_id


def test_saga_instance_mapper_roundtrip_and_clean_context() -> None:
    inst = SagaInstance(saga_name="demo", execution_id="e1", context_data={"_private": "x", "ok": object()})
    md = SagaInstanceMapper.to_mongo(inst)
    assert "_private" not in md["context_data"] and "ok" in md["context_data"]

    doc = {
        "saga_id": inst.saga_id,
        "saga_name": inst.saga_name,
        "execution_id": inst.execution_id,
        "state": "completed",
        "completed_steps": ["a"],
        "compensated_steps": [],
        "context_data": {"a": 1},
        "retry_count": 1,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    inst2 = SagaInstanceMapper.from_mongo(doc)
    assert inst2.state in (SagaState.COMPLETED, SagaState.CREATED)

    # bad state falls back to CREATED
    doc_bad = doc | {"state": "???"}
    inst3 = SagaInstanceMapper.from_mongo(doc_bad)
    assert inst3.state == SagaState.CREATED


def test_saga_event_mapper_to_cancelled_event() -> None:
    inst = SagaInstance(saga_name="demo", execution_id="e1", context_data={"user_id": "u1"}, error_message="e")
    ev = SagaEventMapper.to_cancelled_event(inst)
    assert ev.cancelled_by == "u1" and ev.reason == "e"


def test_saga_filter_mapper_to_query() -> None:
    f = SagaFilter(state=SagaState.COMPLETED, execution_ids=["e1"], saga_name="demo", error_status=False)
    fq = SagaFilterMapper().to_mongodb_query(f)
    assert fq["state"] == SagaState.COMPLETED.value and fq["execution_id"]["$in"] == ["e1"] and fq[
        "error_message"] is None
