import pytest
from app.domain.enums import ExecutionStatus
from app.schemas_pydantic.execution import ExecutionRequest, ExecutionResponse, ExecutionResult
from httpx import AsyncClient

from tests.e2e.conftest import EventWaiter

pytestmark = [pytest.mark.e2e, pytest.mark.k8s]


@pytest.mark.asyncio
async def test_worker_creates_configmap_and_pod(
    test_user: AsyncClient, event_waiter: EventWaiter
) -> None:
    """Full K8s pipeline: HTTP submit -> saga -> k8s-worker creates ConfigMap+Pod -> result stored."""
    request = ExecutionRequest(script="print('k8s-test')", lang="python", lang_version="3.11")
    resp = await test_user.post("/api/v1/execute", json=request.model_dump())
    assert resp.status_code == 200
    execution = ExecutionResponse.model_validate(resp.json())

    await event_waiter.wait_for_result(execution.execution_id)

    result_resp = await test_user.get(f"/api/v1/executions/{execution.execution_id}/result")
    assert result_resp.status_code == 200
    result = ExecutionResult.model_validate(result_resp.json())
    assert result.status == ExecutionStatus.COMPLETED
    assert result.stdout is not None
    assert result.stdout.strip() == "k8s-test"
