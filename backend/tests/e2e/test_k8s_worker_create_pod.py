import pytest
from httpx2 import AsyncClient

from app.domain.enums import EventType, ExecutionStatus
from app.infrastructure.kafka.topics import RESULT_TYPES
from app.schemas_pydantic.execution import ExecutionRequest, ExecutionResult
from tests.e2e.conftest import wait_for_event

pytestmark = [pytest.mark.e2e]


async def test_worker_creates_configmap_and_pod(test_user: AsyncClient) -> None:
    """Verify the worker creates ConfigMap + Pod by running through the full pipeline."""
    request = ExecutionRequest(script="print('k8s-test')")

    resp = await test_user.post("/api/v1/execute", json=request.model_dump())
    assert resp.status_code == 200
    execution_id = resp.json()["execution_id"]

    # The worker took the execution from the queue and created its ConfigMap and pod
    await wait_for_event(execution_id, EventType.POD_CREATED)

    # Full pipeline completed: pod ran, result stored
    await wait_for_event(execution_id, *RESULT_TYPES, timeout=30.0)

    result_resp = await test_user.get(f"/api/v1/executions/{execution_id}/result")
    assert result_resp.status_code == 200
    result = ExecutionResult.model_validate(result_resp.json())
    assert result.status == ExecutionStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout is not None
    assert "k8s-test" in result.stdout
