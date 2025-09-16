import asyncio
import pytest
from datetime import datetime

from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga, SagaConfig, SagaListResult
from app.domain.user import User
from app.domain.enums.user import UserRole
from app.services.saga.saga_orchestrator import SagaOrchestrator
from app.services.saga.execution_saga import ExecutionSaga
from app.services.saga.saga_service import SagaService


pytestmark = pytest.mark.unit


class _FakeSagaRepo:
    def __init__(self) -> None:
        self.sagas: dict[str, Saga] = {}
        self.saved: list[Saga] = []
        self.user_execs: dict[str, list[str]] = {}

    async def upsert_saga(self, saga: Saga) -> bool:
        self.sagas[saga.saga_id] = saga
        self.saved.append(saga)
        return True

    async def get_saga(self, saga_id: str) -> Saga | None:
        return self.sagas.get(saga_id)

    async def get_sagas_by_execution(self, execution_id: str, state: str | None = None):  # noqa: ARG002
        return [s for s in self.sagas.values() if s.execution_id == execution_id]

    async def get_user_execution_ids(self, user_id: str) -> list[str]:
        return self.user_execs.get(user_id, [])

    async def list_sagas(self, filter, limit: int, skip: int):  # noqa: ARG002
        sagas = list(self.sagas.values())[skip: skip + limit]
        return SagaListResult(sagas=sagas, total=len(self.sagas), skip=skip, limit=limit)

    async def get_saga_statistics(self, filter=None):  # noqa: ARG002
        return {"total": len(self.sagas), "by_state": {}}


class _FakeExecRepo:
    def __init__(self) -> None:
        self.owner: dict[str, str] = {}

    async def get_execution(self, execution_id: str):
        class X:
            def __init__(self, user_id):
                self.user_id = user_id
        uid = self.owner.get(execution_id)
        return X(uid) if uid else None


class _FakeIdem:
    async def close(self):
        return None


class _FakeEventStore: ...


class _FakeProducer:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def produce(self, event_to_produce, key: str | None = None):  # noqa: ARG002
        self.events.append(event_to_produce)


class _FakeAllocRepo:
    async def release_allocation(self, aid: str) -> None:  # noqa: ARG002
        return None


def _orchestrator(repo: _FakeSagaRepo, prod: _FakeProducer) -> SagaOrchestrator:
    cfg = SagaConfig(name="test", store_events=True, enable_compensation=True, publish_commands=False)
    orch = SagaOrchestrator(
        config=cfg,
        saga_repository=repo,
        producer=prod,
        event_store=_FakeEventStore(),
        idempotency_manager=_FakeIdem(),
        resource_allocation_repository=_FakeAllocRepo(),
    )
    orch.register_saga(ExecutionSaga)
    return orch


@pytest.mark.asyncio
async def test_saga_service_access_and_cancel_paths() -> None:
    srepo = _FakeSagaRepo()
    erepo = _FakeExecRepo()
    prod = _FakeProducer()
    orch = _orchestrator(srepo, prod)

    svc = SagaService(saga_repo=srepo, execution_repo=erepo, orchestrator=orch)

    # Prepare saga
    saga = Saga(saga_id="s1", saga_name=ExecutionSaga.get_name(), execution_id="e1", state=SagaState.RUNNING)
    saga.completed_steps = ["allocate_resources", "create_pod"]
    saga.context_data = {"user_id": "u1", "allocation_id": "alloc1", "pod_creation_triggered": True}
    srepo.sagas[saga.saga_id] = saga
    erepo.owner["e1"] = "u1"

    now = datetime.utcnow()
    user = User(
        user_id="u1",
        username="u1",
        email="u1@test.com",
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
        hashed_password="hashed",
        created_at=now,
        updated_at=now
    )
    assert await svc.check_execution_access("e1", user) is True

    # Cancel succeeds
    ok = await svc.cancel_saga("s1", user)
    assert ok is True
    assert prod.events, "expected cancellation event to be published"

    # Invalid state
    saga2 = Saga(saga_id="s2", saga_name=ExecutionSaga.get_name(), execution_id="e1", state=SagaState.COMPLETED)
    srepo.sagas["s2"] = saga2
    with pytest.raises(Exception):
        await svc.cancel_saga("s2", user)

    # Admin bypasses owner check
    admin = User(
        user_id="admin",
        username="a",
        email="admin@test.com",
        role=UserRole.ADMIN,
        is_active=True,
        is_superuser=True,
        hashed_password="hashed",
        created_at=now,
        updated_at=now
    )
    assert await svc.check_execution_access("eX", admin) is True

    # list_user_sagas filters by user executions
    srepo.user_execs["u1"] = ["e1"]
    res = await svc.list_user_sagas(user, limit=10, skip=0)
    assert isinstance(res, SagaListResult)

    # Orchestrator get status falls back to repo if not in memory
    got = await svc.get_saga_status_from_orchestrator("s1", user)
    assert got and got.saga_id == "s1"

    # get_saga_with_access_check denies for non-owner, non-admin
    other = User(
        user_id="u2",
        username="u2",
        email="u2@test.com",
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
        hashed_password="hashed",
        created_at=now,
        updated_at=now
    )
    with pytest.raises(Exception):
        await svc.get_saga_with_access_check("s1", other)

    # get_saga_statistics admin-all path
    admin = User(
        user_id="admin",
        username="a",
        email="admin@test.com",
        role=UserRole.ADMIN,
        is_active=True,
        is_superuser=True,
        hashed_password="hashed",
        created_at=now,
        updated_at=now
    )
    stats = await svc.get_saga_statistics(admin, include_all=True)
    assert "total" in stats

    # Access denied path for get_saga_with_access_check when saga not owned and user not admin
    srepo.sagas["s3"] = Saga(saga_id="s3", saga_name=ExecutionSaga.get_name(), execution_id="e3", state=SagaState.RUNNING)
    with pytest.raises(Exception):
        await svc.get_saga_with_access_check("s3", other)

    # get_execution_sagas access check: non-owner denied
    with pytest.raises(Exception):
        await svc.get_execution_sagas("e999", other)

    # Admin access to get_execution_sagas
    ok_list = await svc.get_execution_sagas("e999", admin)
    assert isinstance(ok_list, list)


@pytest.mark.asyncio
async def test_saga_service_negative_paths_and_live_denied() -> None:
    srepo = _FakeSagaRepo()
    erepo = _FakeExecRepo()
    prod = _FakeProducer()
    orch = _orchestrator(srepo, prod)
    svc = SagaService(saga_repo=srepo, execution_repo=erepo, orchestrator=orch)

    # get_saga_with_access_check -> not found
    now = datetime.utcnow()
    test_user = User(
        user_id="u",
        username="u",
        email="u@test.com",
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
        hashed_password="hashed",
        created_at=now,
        updated_at=now
    )
    with pytest.raises(Exception):
        await svc.get_saga_with_access_check("missing", test_user)

    # check_execution_access negative (not admin, not owner, no exec)
    assert await svc.check_execution_access("nope", test_user) is False

    # live saga returned by orchestrator but user not owner -> denied
    s = Saga(saga_id="sX", saga_name=ExecutionSaga.get_name(), execution_id="eX", state=SagaState.RUNNING)
    orch._running_instances["sX"] = s
    other_user = User(
        user_id="other",
        username="o",
        email="other@test.com",
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
        hashed_password="hashed",
        created_at=now,
        updated_at=now
    )
    with pytest.raises(Exception):
        await svc.get_saga_status_from_orchestrator("sX", other_user)
