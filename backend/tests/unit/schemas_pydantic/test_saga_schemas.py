from datetime import datetime, timezone

from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga
from app.schemas_pydantic.saga import SagaStatusResponse


def test_saga_status_response_from_domain():
    s = Saga(
        saga_id="s1",
        saga_name="exec-saga",
        execution_id="e1",
        state=SagaState.RUNNING,
        current_step="allocate",
        completed_steps=["validate"],
        compensated_steps=[],
        error_message=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        completed_at=None,
        retry_count=1,
    )
    resp = SagaStatusResponse.from_domain(s)
    assert resp.saga_id == "s1" and resp.current_step == "allocate"
    assert resp.created_at.endswith("Z") is False  # isoformat without enforced Z; just ensure string

