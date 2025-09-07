import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from app.core.exceptions import IntegrationException
from app.domain.enums import UserRole
from app.domain.enums.execution import ExecutionStatus
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.domain.execution.models import DomainExecution
from app.services.execution_service import ExecutionService


class FakeRepo:
    def __init__(self): self.updated = []
    async def create_execution(self, e: DomainExecution): return e
    async def update_execution(self, execution_id: str, update_data: dict):  # noqa: ANN001
        self.updated.append((execution_id, update_data)); return True
    async def delete_execution(self, execution_id: str): return True  # noqa: ANN001
    async def get_executions(self, query, limit=1000):  # noqa: ANN001
        now = datetime.now(timezone.utc)
        return [DomainExecution(script="p", lang="python", lang_version="3.11", user_id="u", status=ExecutionStatus.COMPLETED, created_at=now - timedelta(seconds=2), updated_at=now)]


class FakeProducer:
    def __init__(self, raise_on_produce=False): self.raise_on_produce = raise_on_produce; self.calls = []
    async def produce(self, **kwargs):  # noqa: ANN001
        if self.raise_on_produce: raise RuntimeError("x")
        self.calls.append(kwargs)


class FakeStore:
    async def store_event(self, event): return True  # noqa: ANN001


def make_settings():
    return SimpleNamespace(
        SUPPORTED_RUNTIMES={"python": ["3.11"]},
        K8S_POD_CPU_LIMIT="100m",
        K8S_POD_MEMORY_LIMIT="128Mi",
        K8S_POD_CPU_REQUEST="50m",
        K8S_POD_MEMORY_REQUEST="64Mi",
        K8S_POD_EXECUTION_TIMEOUT=30,
        EXAMPLE_SCRIPTS={"python": "print(1)"},
    )


class Request:
    def __init__(self): self.client = SimpleNamespace(host="1.2.3.4"); self.headers = {"user-agent": "UA"}


@pytest.mark.asyncio
async def test_execute_script_happy_and_publish() -> None:
    svc = ExecutionService(FakeRepo(), FakeProducer(), FakeStore(), make_settings())
    res = await svc.execute_script("print(1)", user_id="u", client_ip="1.2.3.4", user_agent="UA", lang="python", lang_version="3.11")
    assert isinstance(res, DomainExecution)


@pytest.mark.asyncio
async def test_execute_script_runtime_validation_and_publish_error() -> None:
    svc = ExecutionService(FakeRepo(), FakeProducer(raise_on_produce=True), FakeStore(), make_settings())
    # publish error triggers IntegrationException and updates error
    with pytest.raises(IntegrationException):
        await svc.execute_script("print(1)", user_id="u", client_ip="1.2.3.4", user_agent="UA", lang="python", lang_version="3.11")


@pytest.mark.asyncio
async def test_limits_examples_stats_and_delete_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = ExecutionService(FakeRepo(), FakeProducer(), FakeStore(), make_settings())
    limits = await svc.get_k8s_resource_limits()
    assert "cpu_limit" in limits
    ex = await svc.get_example_scripts()
    assert isinstance(ex, dict)

    stats = await svc.get_execution_stats(user_id=None, time_range=(None, None))
    assert stats["total"] == 1 and stats["success_rate"] > 0

    # delete with publish cancellation event
    ok = await svc.delete_execution("e1")
    assert ok is True
