import uuid
from datetime import datetime, timezone

import pytest

from app.db import ExecutionRepository
from app.db.docs import ExecutionDocument
from app.domain.enums import EventType, ExecutionStatus, UserRole
from app.domain.execution import ResourceLimitsDomain
from app.domain.execution.exceptions import (
    ExecutionAccessDeniedError,
    ExecutionNotFoundError,
    ExecutionNotRetryableError,
)
from app.domain.user import User
from app.runtime_registry import DEFAULT_LANG, DEFAULT_LANG_VERSION
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService

pytestmark = [pytest.mark.e2e]


def _user(user_id: str, role: UserRole = UserRole.USER) -> User:
    now = datetime.now(timezone.utc)
    return User(
        user_id=user_id,
        username=user_id,
        email=f"{user_id}@example.com",
        role=role,
        is_active=True,
        is_superuser=False,
        hashed_password="unused",
        created_at=now,
        updated_at=now,
    )


async def _stored_execution(repo: ExecutionRepository, status: ExecutionStatus) -> tuple[str, str]:
    """Insert an execution directly, so no worker picks it up and its status stays put."""
    owner_id = f"test_user_{uuid.uuid4().hex[:8]}"
    created = ExecutionDocument(script="print('stored')", user_id=owner_id, status=status)
    await repo.create_execution(created)
    return created.execution_id, owner_id


async def _stored_executions(repo: ExecutionRepository, count: int) -> tuple[str, set[str]]:
    """Insert ``count`` queued executions for a fresh user; returns the user id and the execution ids."""
    user_id = f"test_user_{uuid.uuid4().hex[:8]}"
    created = [ExecutionDocument(script=f"print({i})", user_id=user_id) for i in range(count)]
    for execution in created:
        await repo.create_execution(execution)
    return user_id, {e.execution_id for e in created}


class TestGetResourceLimits:
    """Tests for get_k8s_resource_limits method."""

    async def test_get_k8s_resource_limits(self, execution_service: ExecutionService) -> None:
        """Get K8s resource limits returns valid configuration."""
        limits = await execution_service.get_k8s_resource_limits()

        assert isinstance(limits, ResourceLimitsDomain)
        assert limits.cpu_limit is not None
        assert limits.memory_limit is not None
        assert limits.cpu_request is not None
        assert limits.memory_request is not None
        assert limits.execution_timeout > 0
        assert isinstance(limits.supported_runtimes, dict)
        assert "python" in limits.supported_runtimes


class TestGetExampleScripts:
    """Tests for get_example_scripts method."""

    async def test_get_example_scripts(self, execution_service: ExecutionService) -> None:
        """Get example scripts returns dictionary with python."""
        examples = await execution_service.get_example_scripts()

        assert isinstance(examples, dict)
        assert "python" in examples
        assert isinstance(examples["python"], str)
        assert len(examples["python"]) > 0


class TestExecuteScript:
    """Tests for execute_script method."""

    async def test_execute_simple_script(self, execution_service: ExecutionService) -> None:
        """Execute simple script creates execution and returns response."""
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        result = await execution_service.execute_script(
            script="print('hello world')",
            user_id=user_id,
        )

        assert result.execution_id is not None
        assert (result.lang, result.lang_version) == (DEFAULT_LANG, DEFAULT_LANG_VERSION)
        assert result.status in [
            ExecutionStatus.QUEUED,
            ExecutionStatus.SCHEDULED,
            ExecutionStatus.RUNNING,
        ]

    async def test_execute_script_with_custom_timeout(self, execution_service: ExecutionService) -> None:
        """Execute script with custom timeout override."""
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        result = await execution_service.execute_script(
            script="import time; time.sleep(1); print('done')",
            user_id=user_id,
        )

        assert result.execution_id is not None
        assert result.status in [
            ExecutionStatus.QUEUED,
            ExecutionStatus.SCHEDULED,
            ExecutionStatus.RUNNING,
        ]

    async def test_execute_script_returns_unique_ids(self, execution_service: ExecutionService) -> None:
        """Each execution gets unique ID."""
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        result1 = await execution_service.execute_script(
            script="print(1)",
            user_id=user_id,
        )

        result2 = await execution_service.execute_script(
            script="print(2)",
            user_id=user_id,
        )

        assert result1.execution_id != result2.execution_id


class TestGetExecutionResult:
    """Tests for get_execution_result method."""

    async def test_get_execution_result(
        self, execution_repository: ExecutionRepository, execution_service: ExecutionService
    ) -> None:
        """Get execution result for existing execution."""
        execution_id, owner_id = await _stored_execution(execution_repository, ExecutionStatus.COMPLETED)

        result = await execution_service.get_execution_result(execution_id)

        assert (result.execution_id, result.user_id) == (execution_id, owner_id)

    async def test_get_execution_result_not_found(self, execution_service: ExecutionService) -> None:
        """Get nonexistent execution raises error."""

        with pytest.raises(ExecutionNotFoundError):
            await execution_service.get_execution_result("nonexistent-execution-id")


class TestExecutionAccess:
    """Tests for get_execution_for_user and retry_execution."""

    @pytest.mark.parametrize(
        ("requester", "role", "allowed"),
        [("owner", UserRole.USER, True), ("other", UserRole.USER, False), ("other", UserRole.ADMIN, True)],
    )
    async def test_get_execution_for_user(
        self,
        execution_repository: ExecutionRepository,
        requester: str,
        role: UserRole,
        allowed: bool,
        execution_service: ExecutionService,
    ) -> None:
        execution_id, owner_id = await _stored_execution(execution_repository, ExecutionStatus.COMPLETED)
        user = _user(owner_id if requester == "owner" else f"{owner_id}_other", role)

        if allowed:
            result = await execution_service.get_execution_for_user(execution_id, user)
            assert result.execution_id == execution_id
            assert result.user_id == owner_id
        else:
            with pytest.raises(ExecutionAccessDeniedError, match=f"Access denied to execution '{execution_id}'"):
                await execution_service.get_execution_for_user(execution_id, user)

    async def test_get_execution_for_user_not_found(self, execution_service: ExecutionService) -> None:

        with pytest.raises(ExecutionNotFoundError):
            await execution_service.get_execution_for_user("nonexistent-execution-id", _user("anyone"))

    @pytest.mark.parametrize("status", [ExecutionStatus.QUEUED, ExecutionStatus.RUNNING])
    async def test_retry_active_execution_rejected(
        self, execution_repository: ExecutionRepository, status: ExecutionStatus, execution_service: ExecutionService
    ) -> None:
        execution_id, owner_id = await _stored_execution(execution_repository, status)

        with pytest.raises(ExecutionNotRetryableError, match=f"Cannot retry execution in {status} state"):
            await execution_service.retry_execution(execution_id, _user(owner_id))

    async def test_retry_other_users_execution_denied(
        self, execution_repository: ExecutionRepository, execution_service: ExecutionService
    ) -> None:
        execution_id, owner_id = await _stored_execution(execution_repository, ExecutionStatus.COMPLETED)

        with pytest.raises(ExecutionAccessDeniedError):
            await execution_service.retry_execution(execution_id, _user(f"{owner_id}_other"))

    async def test_retry_completed_execution_creates_new_one(
        self, execution_repository: ExecutionRepository, execution_service: ExecutionService
    ) -> None:
        execution_id, owner_id = await _stored_execution(execution_repository, ExecutionStatus.COMPLETED)

        retried = await execution_service.retry_execution(execution_id, _user(owner_id))

        assert retried.execution_id != execution_id
        assert retried.user_id == owner_id
        assert retried.script == "print('stored')"
        assert retried.status == ExecutionStatus.QUEUED


class TestGetExecutionEvents:
    """Tests for get_events_by_aggregate via EventService."""

    async def test_get_execution_events(self, execution_service: ExecutionService, event_service: EventService) -> None:
        """Get events for execution returns list."""
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        exec_result = await execution_service.execute_script(
            script="print('events test')",
            user_id=user_id,
        )

        events = await event_service.get_events_by_aggregate(
            aggregate_id=exec_result.execution_id,
        )

        assert EventType.EXECUTION_REQUESTED in {e.event_type for e in events}

    async def test_get_execution_events_with_filter(
        self, execution_service: ExecutionService, event_service: EventService
    ) -> None:
        """Get events filtered by type."""
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        exec_result = await execution_service.execute_script(
            script="print('filter test')",
            user_id=user_id,
        )

        events = await event_service.get_events_by_aggregate(
            aggregate_id=exec_result.execution_id,
            event_types=[EventType.EXECUTION_REQUESTED],
        )

        assert {e.event_type for e in events} == {EventType.EXECUTION_REQUESTED}


class TestGetUserExecutions:
    """Tests for get_user_executions method."""

    async def test_get_user_executions(
        self, execution_repository: ExecutionRepository, execution_service: ExecutionService
    ) -> None:
        """Get user executions returns exactly the user's executions."""
        user_id, ids = await _stored_executions(execution_repository, 3)

        executions = await execution_service.get_user_executions(user_id=user_id, limit=10, skip=0)

        assert {e.execution_id for e in executions} == ids

    async def test_get_user_executions_pagination(
        self, execution_repository: ExecutionRepository, execution_service: ExecutionService
    ) -> None:
        """Pages split the user's executions without overlap."""
        user_id, ids = await _stored_executions(execution_repository, 5)

        page1 = await execution_service.get_user_executions(user_id=user_id, limit=2, skip=0)
        page2 = await execution_service.get_user_executions(user_id=user_id, limit=2, skip=2)
        page3 = await execution_service.get_user_executions(user_id=user_id, limit=2, skip=4)

        assert [len(page1), len(page2), len(page3)] == [2, 2, 1]
        assert {e.execution_id for e in page1 + page2 + page3} == ids

    async def test_get_user_executions_filter_by_language(
        self, execution_service: ExecutionService, execution_repository: ExecutionRepository
    ) -> None:
        """Filter executions by language."""
        user_id, python_ids = await _stored_executions(execution_repository, 1)
        await execution_repository.create_execution(ExecutionDocument(script="echo hi", user_id=user_id, lang="bash"))

        executions = await execution_service.get_user_executions(user_id=user_id, lang="python", limit=10, skip=0)

        assert {e.execution_id for e in executions} == python_ids


class TestCountUserExecutions:
    """Tests for count_user_executions method."""

    async def test_count_user_executions(
        self, execution_repository: ExecutionRepository, execution_service: ExecutionService
    ) -> None:
        """Count user executions returns correct count."""
        user_id, _ = await _stored_executions(execution_repository, 3)

        assert await execution_service.count_user_executions(user_id=user_id) == 3


class TestDeleteExecution:
    """Tests for delete_execution method."""

    async def test_delete_execution(
        self, execution_repository: ExecutionRepository, execution_service: ExecutionService
    ) -> None:
        """Delete execution removes it from database."""
        execution_id, _ = await _stored_execution(execution_repository, ExecutionStatus.COMPLETED)

        assert await execution_service.delete_execution(execution_id, "test-admin") is True

        with pytest.raises(ExecutionNotFoundError):
            await execution_service.get_execution_result(execution_id)

    async def test_delete_nonexistent_execution(self, execution_service: ExecutionService) -> None:
        """Delete nonexistent execution raises error."""

        with pytest.raises(ExecutionNotFoundError):
            await execution_service.delete_execution("nonexistent-id", "test-admin")


class TestGetExecutionStats:
    """Tests for get_execution_stats method."""

    async def test_get_execution_stats(
        self, execution_repository: ExecutionRepository, execution_service: ExecutionService
    ) -> None:
        """Get execution statistics for user."""
        user_id, _ = await _stored_executions(execution_repository, 2)

        stats = await execution_service.get_execution_stats(user_id=user_id)

        assert stats["total"] == 2
        assert "by_status" in stats
        assert "by_language" in stats
