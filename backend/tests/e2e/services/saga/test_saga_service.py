from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.db.docs import ExecutionDocument
from app.db.repositories import ExecutionRepository, SagaRepository
from app.domain.enums import SagaState, UserRole
from app.domain.saga import Saga, SagaAccessDeniedError, SagaContextData, SagaListResult, SagaNotFoundError
from app.domain.user import User
from app.services.saga import SagaService

pytestmark = [pytest.mark.e2e]


def make_test_user(
    user_id: str = "test_user_1",
    role: UserRole = UserRole.USER,
) -> User:
    """Create a test user for saga access checks."""
    return User(
        user_id=user_id,
        username=user_id,
        email=f"{user_id}@example.com",
        role=role,
        is_active=True,
        is_superuser=role == UserRole.ADMIN,
        hashed_password="unused",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


async def create_execution_for_user(
    exec_repo: ExecutionRepository,
    user_id: str,
) -> str:
    """Create an execution record for a user and return its ID."""
    execution = ExecutionDocument(
        script="print('test')",
        user_id=user_id,
    )
    await exec_repo.create_execution(execution)
    return execution.execution_id


async def create_saga_for_execution(
    saga_repo: SagaRepository,
    execution_id: str,
    state: SagaState = SagaState.CREATED,
    saga_name: str = "test_saga",
) -> Saga:
    """Create a saga for an execution with the given state."""
    saga = Saga(
        saga_id=str(uuid4()),
        saga_name=saga_name,
        execution_id=execution_id,
        state=state,
        current_step="step1",
        completed_steps=[],
        compensated_steps=[],
        context_data=SagaContextData(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    created_saga, _ = await saga_repo.get_or_create_saga(saga)
    return created_saga


class TestListUserSagas:
    """Tests for list_user_sagas method."""

    async def test_list_user_sagas_empty(self, saga_service: SagaService) -> None:
        """List sagas for user with no sagas returns empty list."""
        # Use a unique user ID that has never been used
        user = make_test_user(user_id=f"empty_user_{uuid4().hex[:8]}")

        result = await saga_service.list_user_sagas(user)

        assert isinstance(result, SagaListResult)
        assert result.total == 0
        assert len(result.sagas) == 0

    async def test_list_user_sagas_with_limit(
        self, saga_service: SagaService, execution_repository: ExecutionRepository, saga_repository: SagaRepository
    ) -> None:
        """List sagas respects limit parameter."""

        # Create unique user
        user_id = f"limit_user_{uuid4().hex[:8]}"
        user = make_test_user(user_id=user_id)

        # Create 7 sagas for this user (more than limit of 5)
        created_count = 7
        for i in range(created_count):
            exec_id = await create_execution_for_user(execution_repository, user_id)
            await create_saga_for_execution(saga_repository, exec_id, saga_name=f"saga_{i}")

        result = await saga_service.list_user_sagas(user, limit=5)

        assert isinstance(result, SagaListResult)
        assert len(result.sagas) == 5
        assert result.total == created_count

    async def test_list_user_sagas_with_skip(
        self, saga_service: SagaService, execution_repository: ExecutionRepository, saga_repository: SagaRepository
    ) -> None:
        """List sagas respects skip parameter."""

        # Create unique user
        user_id = f"skip_user_{uuid4().hex[:8]}"
        user = make_test_user(user_id=user_id)

        # Create 5 sagas for this user
        created_count = 5
        for i in range(created_count):
            exec_id = await create_execution_for_user(execution_repository, user_id)
            await create_saga_for_execution(saga_repository, exec_id, saga_name=f"saga_{i}")

        # Get all sagas (skip=0)
        result_all = await saga_service.list_user_sagas(user, skip=0, limit=10)
        assert result_all.total == created_count
        assert len(result_all.sagas) == created_count

        # Skip first 2 sagas
        result_skip = await saga_service.list_user_sagas(user, skip=2, limit=10)
        assert result_skip.total == created_count
        assert len(result_skip.sagas) == created_count - 2

    async def test_list_user_sagas_filter_by_state(
        self, saga_service: SagaService, execution_repository: ExecutionRepository, saga_repository: SagaRepository
    ) -> None:
        """List sagas filtered by state returns only matching state."""

        # Create unique user
        user_id = f"state_user_{uuid4().hex[:8]}"
        user = make_test_user(user_id=user_id)

        # Create sagas with different states
        created_count = 3
        for i in range(created_count):
            exec_id = await create_execution_for_user(execution_repository, user_id)
            await create_saga_for_execution(saga_repository, exec_id, state=SagaState.CREATED, saga_name=f"created_{i}")

        # Create 2 sagas with RUNNING state
        running_count = 2
        for i in range(running_count):
            exec_id = await create_execution_for_user(execution_repository, user_id)
            await create_saga_for_execution(saga_repository, exec_id, state=SagaState.RUNNING, saga_name=f"running_{i}")

        # Filter by CREATED state
        result = await saga_service.list_user_sagas(user, state=SagaState.CREATED)

        assert isinstance(result, SagaListResult)
        assert result.total == created_count
        assert len(result.sagas) == created_count
        for saga in result.sagas:
            assert saga.state == SagaState.CREATED

    async def test_list_user_sagas_search(
        self, saga_service: SagaService, execution_repository: ExecutionRepository, saga_repository: SagaRepository
    ) -> None:
        """Search matches saga name or execution ID case-insensitively and treats regex characters literally."""

        user_id = f"search_user_{uuid4().hex[:8]}"
        user = make_test_user(user_id=user_id)
        exec_ids = [await create_execution_for_user(execution_repository, user_id) for _ in range(3)]
        await create_saga_for_execution(saga_repository, exec_ids[0], saga_name="Alpha_flow")
        await create_saga_for_execution(saga_repository, exec_ids[1], saga_name="beta.flow")
        await create_saga_for_execution(saga_repository, exec_ids[2], saga_name="gamma_flow")

        by_name = await saga_service.list_user_sagas(user, search="ALPHA")
        assert [s.saga_name for s in by_name.sagas] == ["Alpha_flow"]
        assert by_name.total == 1

        literal_dot = await saga_service.list_user_sagas(user, search=".flow")
        assert [s.saga_name for s in literal_dot.sagas] == ["beta.flow"]

        by_execution = await saga_service.list_user_sagas(user, search=exec_ids[2][:13])
        assert [s.execution_id for s in by_execution.sagas] == [exec_ids[2]]

        scoped = await saga_service.list_user_sagas(user, execution_id=exec_ids[0], search="beta")
        assert scoped.total == 0
        assert scoped.sagas == []

    async def test_admin_can_list_all_sagas(self, saga_service: SagaService) -> None:
        """Admin user can list all sagas."""
        admin = make_test_user(user_id="admin_user", role=UserRole.ADMIN)

        result = await saga_service.list_user_sagas(admin)

        assert isinstance(result, SagaListResult)
        assert isinstance(result.sagas, list)


class TestGetSagaWithAccessCheck:
    """Tests for get_saga_with_access_check method."""

    async def test_get_saga_not_found(self, saga_service: SagaService) -> None:
        """Get nonexistent saga raises SagaNotFoundError."""
        user = make_test_user()

        with pytest.raises(SagaNotFoundError):
            await saga_service.get_saga_with_access_check("nonexistent-saga-id", user)


class TestCheckExecutionAccess:
    """Tests for check_execution_access method."""

    async def test_admin_has_access_to_any_execution(
        self, saga_service: SagaService, execution_repository: ExecutionRepository
    ) -> None:
        """Admin has access to any execution."""
        admin = make_test_user(user_id="admin_user", role=UserRole.ADMIN)

        execution_id = await create_execution_for_user(execution_repository, f"other_user_{uuid4().hex[:8]}")

        has_access = await saga_service.check_execution_access(execution_id, admin)
        assert has_access is True

    async def test_user_has_access_to_own_execution(
        self, saga_service: SagaService, execution_repository: ExecutionRepository
    ) -> None:
        """User has access to their own execution."""
        user_id = f"saga_owner_user_{uuid4().hex[:8]}"
        user = make_test_user(user_id=user_id)

        execution_id = await create_execution_for_user(execution_repository, user_id)

        has_access = await saga_service.check_execution_access(execution_id, user)
        assert has_access is True

    async def test_user_no_access_to_other_execution(
        self, saga_service: SagaService, execution_repository: ExecutionRepository
    ) -> None:
        """User does not have access to other user's execution."""
        other_user = make_test_user(user_id="different_user")

        execution_id = await create_execution_for_user(execution_repository, f"owner_user_{uuid4().hex[:8]}")

        has_access = await saga_service.check_execution_access(execution_id, other_user)
        assert has_access is False

    async def test_access_to_nonexistent_execution(self, saga_service: SagaService) -> None:
        """Access check for nonexistent execution returns False."""
        user = make_test_user()

        has_access = await saga_service.check_execution_access("nonexistent-id", user)
        assert has_access is False


class TestGetExecutionSagas:
    """Tests for get_execution_sagas method."""

    async def test_get_execution_sagas_access_denied(
        self, saga_service: SagaService, execution_repository: ExecutionRepository
    ) -> None:
        """Get sagas for execution without access raises error."""
        other_user = make_test_user(user_id="no_access_user")

        execution_id = await create_execution_for_user(execution_repository, f"owner_user_{uuid4().hex[:8]}")

        with pytest.raises(SagaAccessDeniedError):
            await saga_service.get_execution_sagas(execution_id, other_user)

    async def test_get_execution_sagas_owner_access(
        self, saga_service: SagaService, execution_repository: ExecutionRepository
    ) -> None:
        """Owner can get sagas for their execution."""
        user_id = f"saga_exec_owner_{uuid4().hex[:8]}"
        user = make_test_user(user_id=user_id)

        execution_id = await create_execution_for_user(execution_repository, user_id)

        result = await saga_service.get_execution_sagas(execution_id, user)

        assert isinstance(result, SagaListResult)
        assert isinstance(result.sagas, list)


class TestGetSagaStatistics:
    """Tests for get_saga_statistics method."""

    async def test_get_saga_statistics_user(self, saga_service: SagaService) -> None:
        """Get saga statistics for regular user."""
        user = make_test_user()

        stats = await saga_service.get_saga_statistics(user)

        assert isinstance(stats, dict)

    async def test_get_saga_statistics_admin_all(self, saga_service: SagaService) -> None:
        """Admin can get all saga statistics."""
        admin = make_test_user(user_id="stats_admin", role=UserRole.ADMIN)

        stats = await saga_service.get_saga_statistics(admin, include_all=True)

        assert isinstance(stats, dict)
