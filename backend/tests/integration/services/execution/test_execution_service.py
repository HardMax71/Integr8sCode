import pytest

from app.services.execution_service import ExecutionService

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_execute_script_and_limits(scope) -> None:  # type: ignore[valid-type]
    svc: ExecutionService = await scope.get(ExecutionService)
    limits = await svc.get_k8s_resource_limits()
    assert set(limits.keys()) >= {"cpu_limit", "memory_limit", "supported_runtimes"}
    ex = await svc.get_example_scripts()
    assert isinstance(ex, dict)

    res = await svc.execute_script(
        "print(1)", user_id="u", client_ip="127.0.0.1", user_agent="pytest",
        lang="python", lang_version="3.11"
    )
    assert res.execution_id and res.lang == "python"
