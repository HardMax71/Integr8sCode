import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.services.saga_service import SagaService
from app.domain.admin.user_models import User
from app.domain.enums.user import UserRole
from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga, SagaListResult
from app.domain.saga.exceptions import SagaAccessDeniedError, SagaInvalidStateError, SagaNotFoundError


pytestmark = pytest.mark.unit


@pytest.fixture()
def repos_and_service() -> tuple[AsyncMock, AsyncMock, AsyncMock, SagaService]:
    saga_repo = AsyncMock()
    exec_repo = AsyncMock()
    orchestrator = AsyncMock()
    service = SagaService(saga_repo, exec_repo, orchestrator)
    return saga_repo, exec_repo, orchestrator, service


def _user_admin() -> User:
    return User(user_id="u1", username="a", email="a@e.com", role=UserRole.ADMIN, is_active=True, is_superuser=True, 
                hashed_password="hashed", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))


def _user_user() -> User:
    return User(user_id="u2", username="b", email="b@e.com", role=UserRole.USER, is_active=True, is_superuser=False,
                hashed_password="hashed", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_check_execution_access_admin_and_owner(repos_and_service) -> None:
    saga_repo, exec_repo, orchestrator, service = repos_and_service
    assert await service.check_execution_access("e", _user_admin()) is True
    exec_repo.get_execution = AsyncMock(return_value=type("E", (), {"user_id": "u2"})())
    assert await service.check_execution_access("e", _user_user()) is True
    exec_repo.get_execution = AsyncMock(return_value=None)
    assert await service.check_execution_access("e", _user_user()) is False


@pytest.mark.asyncio
async def test_get_saga_with_access_check_paths(repos_and_service) -> None:
    saga_repo, exec_repo, orchestrator, service = repos_and_service
    service.execution_repo.get_execution = AsyncMock(return_value=None)
    saga_repo.get_saga = AsyncMock(return_value=None)
    with pytest.raises(SagaNotFoundError):
        await service.get_saga_with_access_check("s", _user_user())

    saga_repo.get_saga = AsyncMock(return_value=Saga(saga_id="s", saga_name="n", execution_id="e", state=SagaState.RUNNING))
    exec_repo.get_execution = AsyncMock(return_value=type("E", (), {"user_id": "other"})())
    with pytest.raises(SagaAccessDeniedError):
        await service.get_saga_with_access_check("s", _user_user())

    exec_repo.get_execution = AsyncMock(return_value=type("E", (), {"user_id": "u2"})())
    saga = await service.get_saga_with_access_check("s", _user_user())
    assert saga.saga_id == "s"


@pytest.mark.asyncio
async def test_get_execution_sagas_and_list_user_sagas(repos_and_service) -> None:
    saga_repo, exec_repo, orchestrator, service = repos_and_service
    # denied
    exec_repo.get_execution = AsyncMock(return_value=type("E", (), {"user_id": "uX"})())
    with pytest.raises(SagaAccessDeniedError):
        await service.get_execution_sagas("e", _user_user())
    # allowed path
    exec_repo.get_execution = AsyncMock(return_value=type("E", (), {"user_id": "u2"})())
    saga_repo.get_sagas_by_execution = AsyncMock(return_value=[Saga(saga_id="s", saga_name="n", execution_id="e", state=SagaState.RUNNING)])
    lst = await service.get_execution_sagas("e", _user_user())
    assert lst and lst[0].execution_id == "e"

    # list_user_sagas: user path filters execution ids
    saga_repo.get_user_execution_ids = AsyncMock(return_value=["e1", "e2"])  # attribute exists on repo
    saga_repo.list_sagas = AsyncMock(return_value=SagaListResult(sagas=[], total=0, skip=0, limit=10))
    _ = await service.list_user_sagas(_user_user())
    # admin path
    _ = await service.list_user_sagas(_user_admin())


@pytest.mark.asyncio
async def test_cancel_and_stats_and_status(repos_and_service) -> None:
    saga_repo, exec_repo, orchestrator, service = repos_and_service
    # cancel invalid state
    service.get_saga_with_access_check = AsyncMock(return_value=Saga(saga_id="s", saga_name="n", execution_id="e", state=SagaState.COMPLETED))
    with pytest.raises(SagaInvalidStateError):
        await service.cancel_saga("s", _user_admin())
    # cancel success and failure logging paths
    service.get_saga_with_access_check = AsyncMock(return_value=Saga(saga_id="s", saga_name="n", execution_id="e", state=SagaState.RUNNING))
    orchestrator.cancel_saga = AsyncMock(return_value=True)
    assert await service.cancel_saga("s", _user_admin()) is True
    orchestrator.cancel_saga = AsyncMock(return_value=False)
    assert await service.cancel_saga("s", _user_admin()) is False

    # stats: user-filtered and admin include_all
    saga_repo.get_user_execution_ids = AsyncMock(return_value=["e1"])
    saga_repo.get_saga_statistics = AsyncMock(return_value={"total": 0})
    _ = await service.get_saga_statistics(_user_user())
    _ = await service.get_saga_statistics(_user_admin(), include_all=True)

    # status from orchestrator allowed
    class Inst:
        saga_id = "s"; saga_name = "n"; execution_id = "e"; state = SagaState.RUNNING
        current_step=None; completed_steps=[]; compensated_steps=[]; context_data={}; error_message=None
        from datetime import datetime, timezone
        created_at = updated_at = completed_at = None
        retry_count = 0
    orchestrator.get_saga_status = AsyncMock(return_value=Inst())
    exec_repo.get_execution = AsyncMock(return_value=type("E", (), {"user_id": "u1"})())
    _ = await service.get_saga_status_from_orchestrator("s", _user_admin())
    # denied on live
    exec_repo.get_execution = AsyncMock(return_value=type("E", (), {"user_id": "other"})())
    with pytest.raises(SagaAccessDeniedError):
        await service.get_saga_status_from_orchestrator("s", _user_user())
    # fallback to repo
    orchestrator.get_saga_status = AsyncMock(return_value=None)
    service.get_saga_with_access_check = AsyncMock(return_value=Saga(saga_id="s", saga_name="n", execution_id="e", state=SagaState.RUNNING))
    assert await service.get_saga_status_from_orchestrator("s", _user_admin())

