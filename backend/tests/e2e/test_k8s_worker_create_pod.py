import pytest
import redis.asyncio as redis
from app.domain.enums import ExecutionStatus
from app.schemas_pydantic.execution import ExecutionRequest, ExecutionResult
from httpx import AsyncClient

from tests.e2e.conftest import wait_for_pod_created, wait_for_result

pytestmark = [pytest.mark.e2e, pytest.mark.k8s]


@pytest.mark.asyncio
async def test_worker_creates_configmap_and_pod(
    test_user: AsyncClient, redis_client: redis.Redis
) -> None:
    """Verify k8s-worker creates ConfigMap + Pod by running through the full pipeline."""
    request = ExecutionRequest(script="print('k8s-test')", lang="python", lang_version="3.11")

    resp = await test_user.post("/api/v1/execute", json=request.model_dump())
    assert resp.status_code == 200
    execution_id = resp.json()["execution_id"]

    # Saga dispatched CREATE_POD_COMMAND → k8s-worker created ConfigMap + Pod
    await wait_for_pod_created(redis_client, execution_id)

    # Full pipeline completed: pod ran, result stored
    await wait_for_result(redis_client, execution_id, timeout=30.0)

    result_resp = await test_user.get(f"/api/v1/executions/{execution_id}/result")
    assert result_resp.status_code == 200
    result = ExecutionResult.model_validate(result_resp.json())
    assert result.status == ExecutionStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout is not None
    assert "k8s-test" in result.stdout
