import pytest
from app.services.execution_service import ExecutionService
from app.db.repositories.execution_repository import ExecutionRepository
from app.services.kubernetes_service import KubernetesService

@pytest.fixture
def execution_service(test_db):
    execution_repo = ExecutionRepository(test_db)
    k8s_service = KubernetesService()
    return ExecutionService(execution_repo, k8s_service)

@pytest.mark.asyncio
async def test_execute_script(execution_service):
    script = "print('Hello, World!')"
    result = await execution_service.execute_script(script)
    assert result.status == "queued"
    # Optionally, verify the execution is in the database
    execution_in_db = await execution_service.execution_repo.get_execution(result.id)
    assert execution_in_db is not None
    assert execution_in_db['status'] == "queued"

@pytest.mark.asyncio
async def test_get_execution_result(execution_service):
    execution_id = "test_id"
    # Insert a test execution into the test database
    await execution_service.execution_repo.create_execution({
        "id": execution_id,
        "status": "completed",
        "output": "Hello, World!"
    })
    result = await execution_service.get_execution_result(execution_id)
    assert result.status == "completed"
    assert result.output == "Hello, World!"
