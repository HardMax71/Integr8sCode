from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from app.core.exceptions.handlers import _map_to_status_code
from app.core.metrics import ExecutionMetrics, IdempotencyMetrics
from app.db import ExecutionRepository
from app.domain.admin import SystemSettings
from app.domain.enums import EventType, ExecutionStatus, UserRole
from app.domain.exceptions import ConflictError, InfrastructureError
from app.domain.execution import (
    ExecutionAccessDeniedError,
    ExecutionLimitExceededError,
    ExecutionNotRetryableError,
    LanguageLimitsDomain,
    RuntimeNotSupportedError,
)
from app.domain.idempotency import IdempotencyRecord, IdempotencyStatus
from app.domain.user import User
from app.events import UnifiedProducer
from app.runtime_registry import POD_RUNTIME_CONFIGS
from app.services.execution_queue import ExecutionQueueService
from app.services.execution_service import ExecutionService
from app.services.idempotency import IdempotencyConfig, IdempotencyManager, RedisIdempotencyRepository
from app.services.runtime_settings import RuntimeSettingsLoader
from app.settings import Settings
from tests.unit.conftest import make_domain_execution

pytestmark = pytest.mark.unit


def _user(user_id: str) -> User:
    now = datetime.now(timezone.utc)
    return User(
        user_id=user_id,
        username=user_id,
        email=f"{user_id}@example.com",
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
        hashed_password="unused",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def repo() -> AsyncMock:
    return AsyncMock(spec=ExecutionRepository)


@pytest.fixture
def producer() -> AsyncMock:
    return AsyncMock(spec=UnifiedProducer)


@pytest.fixture
def queue() -> AsyncMock:
    q = AsyncMock(spec=ExecutionQueueService)
    q.reserve_user_slot.return_value = True
    return q


@pytest.fixture
def service(repo: AsyncMock, producer: AsyncMock, queue: AsyncMock, test_settings: Settings) -> ExecutionService:
    runtime_settings = AsyncMock(spec=RuntimeSettingsLoader)
    runtime_settings.get_effective_settings.return_value = SystemSettings()
    return ExecutionService(
        execution_repo=repo,
        producer=producer,
        settings=test_settings,
        logger=structlog.get_logger("test"),
        execution_metrics=MagicMock(spec=ExecutionMetrics),
        idempotency_manager=AsyncMock(spec=IdempotencyManager),
        runtime_settings=runtime_settings,
        queue=queue,
    )


@pytest.mark.parametrize(("lang", "lang_version"), [("python", "3.7"), ("go", "1.22"), ("cobol", "1.0")])
async def test_retry_of_an_unoffered_runtime_is_rejected(
    service: ExecutionService, repo: AsyncMock, producer: AsyncMock, lang: str, lang_version: str
) -> None:
    repo.get_execution.return_value = make_domain_execution(
        status=ExecutionStatus.COMPLETED, lang=lang, lang_version=lang_version, user_id="owner"
    )

    with pytest.raises(RuntimeNotSupportedError, match=f"Runtime not supported: {lang} {lang_version}") as exc:
        await service.retry_execution("e1", _user("owner"))

    assert _map_to_status_code(exc.value) == 422
    repo.create_execution.assert_not_awaited()
    producer.produce.assert_not_awaited()


@pytest.mark.parametrize("status", [s for s in ExecutionStatus if not s.is_terminal])
async def test_retry_of_an_unfinished_execution_is_rejected(
    service: ExecutionService, repo: AsyncMock, producer: AsyncMock, status: ExecutionStatus
) -> None:
    repo.get_execution.return_value = make_domain_execution(status=status, user_id="owner")

    with pytest.raises(ExecutionNotRetryableError) as exc:
        await service.retry_execution("e1", _user("owner"))

    assert _map_to_status_code(exc.value) == 400
    repo.create_execution.assert_not_awaited()
    producer.produce.assert_not_awaited()


async def test_execution_without_owner_is_hidden_from_other_users(service: ExecutionService, repo: AsyncMock) -> None:
    repo.get_execution.return_value = make_domain_execution(status=ExecutionStatus.COMPLETED, user_id=None)

    with pytest.raises(ExecutionAccessDeniedError) as exc:
        await service.get_execution_for_user("e1", _user("someone"))

    assert _map_to_status_code(exc.value) == 403


async def test_k8s_limits_report_effective_limits_per_language(
    repo: AsyncMock, producer: AsyncMock, test_settings: Settings
) -> None:
    settings_repo = AsyncMock()
    settings_repo.get_system_settings.return_value = SystemSettings(
        cpu_limit="500m", memory_limit="128Mi", max_timeout_seconds=5
    )
    service = ExecutionService(
        execution_repo=repo,
        producer=producer,
        settings=test_settings,
        logger=structlog.get_logger("test"),
        execution_metrics=MagicMock(spec=ExecutionMetrics),
        idempotency_manager=AsyncMock(spec=IdempotencyManager),
        runtime_settings=RuntimeSettingsLoader(settings_repo, test_settings, structlog.get_logger("test")),
        queue=AsyncMock(spec=ExecutionQueueService),
    )

    limits = await service.get_k8s_resource_limits()

    assert (limits.cpu_limit, limits.memory_limit, limits.execution_timeout) == ("500m", "128Mi", 5)
    assert limits.language_limits.keys() == test_settings.SUPPORTED_RUNTIMES.keys()
    assert limits.language_limits["python"] == LanguageLimitsDomain(
        cpu_limit="500m", memory_limit="128Mi", execution_timeout=5
    )
    go = POD_RUNTIME_CONFIGS["go"]
    assert go.min_cpu and go.min_memory and go.min_timeout_seconds
    assert limits.language_limits["go"] == LanguageLimitsDomain(
        cpu_limit=go.min_cpu, memory_limit=go.min_memory, execution_timeout=go.min_timeout_seconds
    )


class _MemoryIdempotencyRepo(RedisIdempotencyRepository):
    def __init__(self) -> None:
        self.records: dict[str, IdempotencyRecord] = {}

    async def find_by_key(self, key: str) -> IdempotencyRecord | None:
        return self.records.get(key)

    async def insert_processing(self, record: IdempotencyRecord) -> None:
        self.records[record.key] = record

    async def update_record(self, record: IdempotencyRecord) -> int:
        self.records[record.key] = record
        return 1

    async def delete_key(self, key: str) -> int:
        return 1 if self.records.pop(key, None) else 0


_HTTP_KEY = f"idempotency:{EventType.EXECUTION_REQUESTED}:http:u1:k1"


@pytest.fixture
def idem_repo() -> _MemoryIdempotencyRepo:
    return _MemoryIdempotencyRepo()


@pytest.fixture
def idem_service(
    repo: AsyncMock,
    producer: AsyncMock,
    queue: AsyncMock,
    test_settings: Settings,
    idem_repo: _MemoryIdempotencyRepo,
) -> ExecutionService:
    runtime_settings = AsyncMock(spec=RuntimeSettingsLoader)
    runtime_settings.get_effective_settings.return_value = SystemSettings()
    logger = structlog.get_logger("test")
    manager = IdempotencyManager(IdempotencyConfig(), idem_repo, logger, MagicMock(spec=IdempotencyMetrics))
    return ExecutionService(
        execution_repo=repo,
        producer=producer,
        settings=test_settings,
        logger=logger,
        execution_metrics=MagicMock(spec=ExecutionMetrics),
        idempotency_manager=manager,
        runtime_settings=runtime_settings,
        queue=queue,
    )


async def _run(service: ExecutionService) -> str:
    result = await service.execute_script_idempotent(
        script="print(1)", user_id="u1", idempotency_key="k1"
    )
    return result.execution_id


async def test_failed_request_releases_its_idempotency_key(
    idem_service: ExecutionService, repo: AsyncMock, idem_repo: _MemoryIdempotencyRepo
) -> None:
    repo.create_execution.side_effect = [InfrastructureError("mongo down"), make_domain_execution(execution_id="e2")]

    with pytest.raises(InfrastructureError, match="mongo down"):
        await _run(idem_service)
    assert _HTTP_KEY not in idem_repo.records

    assert await _run(idem_service) == "e2"
    assert repo.create_execution.await_count == 2
    assert idem_repo.records[_HTTP_KEY].status == IdempotencyStatus.COMPLETED


async def test_completed_request_replays_the_cached_execution(idem_service: ExecutionService, repo: AsyncMock) -> None:
    repo.create_execution.return_value = make_domain_execution(execution_id="e1")

    assert await _run(idem_service) == "e1"
    assert await _run(idem_service) == "e1"
    repo.create_execution.assert_awaited_once()


async def test_request_in_flight_is_rejected(
    idem_service: ExecutionService, repo: AsyncMock, idem_repo: _MemoryIdempotencyRepo
) -> None:
    idem_repo.records[_HTTP_KEY] = IdempotencyRecord(
        key=_HTTP_KEY,
        status=IdempotencyStatus.PROCESSING,
        event_type=EventType.EXECUTION_REQUESTED,
        event_id="ev",
        created_at=datetime.now(timezone.utc),
        ttl_seconds=86400,
    )

    with pytest.raises(ConflictError, match="'k1' is still being processed") as exc:
        await _run(idem_service)

    assert _map_to_status_code(exc.value) == 409
    repo.create_execution.assert_not_awaited()


async def test_execute_refuses_a_user_at_the_execution_limit(
    service: ExecutionService, repo: AsyncMock, producer: AsyncMock, queue: AsyncMock
) -> None:
    queue.reserve_user_slot.return_value = False

    with pytest.raises(ExecutionLimitExceededError) as exc_info:
        await service.execute_script(script="print(1)", user_id="u1")

    assert _map_to_status_code(exc_info.value) == 429
    assert queue.reserve_user_slot.await_args.args[0] == "u1"
    assert queue.reserve_user_slot.await_args.args[2] == SystemSettings().max_executions_per_user
    repo.create_execution.assert_not_awaited()
    producer.produce.assert_not_awaited()


async def test_execute_reserves_the_slot_under_the_new_execution_id(
    service: ExecutionService, repo: AsyncMock, queue: AsyncMock
) -> None:
    repo.create_execution.side_effect = lambda data: make_domain_execution(execution_id=data.execution_id)

    created = await service.execute_script(script="print(1)", user_id="u1")

    assert queue.reserve_user_slot.await_args.args[1] == created.execution_id
    queue.release_user_slot.assert_not_awaited()


@pytest.mark.parametrize("failing", ["create", "publish"])
async def test_execute_gives_the_slot_back_when_submission_fails(
    service: ExecutionService, repo: AsyncMock, producer: AsyncMock, queue: AsyncMock, failing: str
) -> None:
    repo.create_execution.side_effect = lambda data: make_domain_execution(execution_id=data.execution_id)
    if failing == "create":
        repo.create_execution.side_effect = InfrastructureError("mongo down")
    else:
        producer.produce.side_effect = RuntimeError("kafka down")

    with pytest.raises(InfrastructureError):
        await service.execute_script(script="print(1)", user_id="u1")

    reserved_id = queue.reserve_user_slot.await_args.args[1]
    queue.release_user_slot.assert_awaited_once_with(reserved_id)
