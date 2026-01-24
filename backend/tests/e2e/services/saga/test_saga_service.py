from datetime import datetime, timezone
from uuid import uuid4

import pytest
from app.db.repositories import ExecutionRepository, SagaRepository
from app.domain.enums import SagaState
from app.domain.enums.user import UserRole
from app.domain.execution import DomainExecutionCreate
from app.domain.saga.exceptions import SagaAccessDeniedError, SagaNotFoundError
from app.domain.saga.models import Saga, SagaListResult
from app.schemas_pydantic.user import User
from app.services.execution_service import ExecutionService
from app.services.saga.saga_service import SagaService
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.mongodb]


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
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


async def create_execution_for_user(
    exec_repo: ExecutionRepository,
    user_id: str,
) -> str:
    """Create an execution record for a user and return its ID."""
    execution = await exec_repo.create_execution(
        DomainExecutionCreate(
            script="print('test')",
            lang="python",
            lang_version="3.11",
            user_id=user_id,
        )
    )
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
        context_data={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await saga_repo.upsert_saga(saga)
    return saga


class TestListUserSagas:
    """Tests for list_user_sagas method."""

    @pytest.mark.asyncio
    async def test_list_user_sagas_empty(self, scope: AsyncContainer) -> None:
        """List sagas for user with no sagas returns empty list."""
        svc: SagaService = await scope.get(SagaService)
        # Use a unique user ID that has never been used
        user = make_test_user(user_id=f"empty_user_{uuid4().hex[:8]}")

        result = await svc.list_user_sagas(user)

        assert isinstance(result, SagaListResult)
        assert result.total == 0
        assert len(result.sagas) == 0

    @pytest.mark.asyncio
    async def test_list_user_sagas_with_limit(self, scope: AsyncContainer) -> None:
        """List sagas respects limit parameter."""
        svc: SagaService = await scope.get(SagaService)
        exec_repo: ExecutionRepository = await scope.get(ExecutionRepository)
        saga_repo: SagaRepository = await scope.get(SagaRepository)

        # Create unique user
        user_id = f"limit_user_{uuid4().hex[:8]}"
        user = make_test_user(user_id=user_id)

        # Create 7 sagas for this user (more than limit of 5)
        created_count = 7
        for i in range(created_count):
            exec_id = await create_execution_for_user(exec_repo, user_id)
            await create_saga_for_execution(saga_repo, exec_id, saga_name=f"saga_{i}")

        result = await svc.list_user_sagas(user, limit=5)

        assert isinstance(result, SagaListResult)
        assert len(result.sagas) == 5
        assert result.total == created_count

    @pytest.mark.asyncio
    async def test_list_user_sagas_with_skip(self, scope: AsyncContainer) -> None:
        """List sagas respects skip parameter."""
        svc: SagaService = await scope.get(SagaService)
        exec_repo: ExecutionRepository = await scope.get(ExecutionRepository)
        saga_repo: SagaRepository = await scope.get(SagaRepository)

        # Create unique user
        user_id = f"skip_user_{uuid4().hex[:8]}"
        user = make_test_user(user_id=user_id)

        # Create 5 sagas for this user
        created_count = 5
        for i in range(created_count):
            exec_id = await create_execution_for_user(exec_repo, user_id)
            await create_saga_for_execution(saga_repo, exec_id, saga_name=f"saga_{i}")

        # Get all sagas (skip=0)
        result_all = await svc.list_user_sagas(user, skip=0, limit=10)
        assert result_all.total == created_count
        assert len(result_all.sagas) == created_count

        # Skip first 2 sagas
        result_skip = await svc.list_user_sagas(user, skip=2, limit=10)
        assert result_skip.total == created_count
        assert len(result_skip.sagas) == created_count - 2

    @pytest.mark.asyncio
    async def test_list_user_sagas_filter_by_state(
        self, scope: AsyncContainer
    ) -> None:
        """List sagas filtered by state returns only matching state."""
        svc: SagaService = await scope.get(SagaService)
        exec_repo: ExecutionRepository = await scope.get(ExecutionRepository)
        saga_repo: SagaRepository = await scope.get(SagaRepository)

        # Create unique user
        user_id = f"state_user_{uuid4().hex[:8]}"
        user = make_test_user(user_id=user_id)

        # Create sagas with different states
        created_count = 3
        for i in range(created_count):
            exec_id = await create_execution_for_user(exec_repo, user_id)
            await create_saga_for_execution(
                saga_repo, exec_id, state=SagaState.CREATED, saga_name=f"created_{i}"
            )

        # Create 2 sagas with RUNNING state
        running_count = 2
        for i in range(running_count):
            exec_id = await create_execution_for_user(exec_repo, user_id)
            await create_saga_for_execution(
                saga_repo, exec_id, state=SagaState.RUNNING, saga_name=f"running_{i}"
            )

        # Filter by CREATED state
        result = await svc.list_user_sagas(user, state=SagaState.CREATED)

        assert isinstance(result, SagaListResult)
        assert result.total == created_count
        assert len(result.sagas) == created_count
        for saga in result.sagas:
            assert saga.state == SagaState.CREATED

    @pytest.mark.asyncio
    async def test_admin_can_list_all_sagas(self, scope: AsyncContainer) -> None:
        """Admin user can list all sagas."""
        svc: SagaService = await scope.get(SagaService)
        admin = make_test_user(user_id="admin_user", role=UserRole.ADMIN)

        result = await svc.list_user_sagas(admin)

        assert isinstance(result, SagaListResult)
        assert isinstance(result.sagas, list)


class TestGetSagaWithAccessCheck:
    """Tests for get_saga_with_access_check method."""

    @pytest.mark.asyncio
    async def test_get_saga_not_found(self, scope: AsyncContainer) -> None:
        """Get nonexistent saga raises SagaNotFoundError."""
        svc: SagaService = await scope.get(SagaService)
        user = make_test_user()

        with pytest.raises(SagaNotFoundError):
            await svc.get_saga_with_access_check("nonexistent-saga-id", user)


class TestCheckExecutionAccess:
    """Tests for check_execution_access method."""

    @pytest.mark.asyncio
    async def test_admin_has_access_to_any_execution(
        self, scope: AsyncContainer
    ) -> None:
        """Admin has access to any execution."""
        svc: SagaService = await scope.get(SagaService)
        exec_svc: ExecutionService = await scope.get(ExecutionService)
        admin = make_test_user(user_id="admin_user", role=UserRole.ADMIN)

        # Create execution as different user
        exec_result = await exec_svc.execute_script(
            script="print('admin access test')",
            user_id="other_user",
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        has_access = await svc.check_execution_access(
            exec_result.execution_id, admin
        )
        assert has_access is True

    @pytest.mark.asyncio
    async def test_user_has_access_to_own_execution(
        self, scope: AsyncContainer
    ) -> None:
        """User has access to their own execution."""
        svc: SagaService = await scope.get(SagaService)
        exec_svc: ExecutionService = await scope.get(ExecutionService)
        user_id = "saga_owner_user"
        user = make_test_user(user_id=user_id)

        exec_result = await exec_svc.execute_script(
            script="print('owner access test')",
            user_id=user_id,
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        has_access = await svc.check_execution_access(
            exec_result.execution_id, user
        )
        assert has_access is True

    @pytest.mark.asyncio
    async def test_user_no_access_to_other_execution(
        self, scope: AsyncContainer
    ) -> None:
        """User does not have access to other user's execution."""
        svc: SagaService = await scope.get(SagaService)
        exec_svc: ExecutionService = await scope.get(ExecutionService)
        other_user = make_test_user(user_id="different_user")

        exec_result = await exec_svc.execute_script(
            script="print('no access test')",
            user_id="owner_user",
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        has_access = await svc.check_execution_access(
            exec_result.execution_id, other_user
        )
        assert has_access is False

    @pytest.mark.asyncio
    async def test_access_to_nonexistent_execution(
        self, scope: AsyncContainer
    ) -> None:
        """Access check for nonexistent execution returns False."""
        svc: SagaService = await scope.get(SagaService)
        user = make_test_user()

        has_access = await svc.check_execution_access("nonexistent-id", user)
        assert has_access is False


class TestGetExecutionSagas:
    """Tests for get_execution_sagas method."""

    @pytest.mark.asyncio
    async def test_get_execution_sagas_access_denied(
        self, scope: AsyncContainer
    ) -> None:
        """Get sagas for execution without access raises error."""
        svc: SagaService = await scope.get(SagaService)
        exec_svc: ExecutionService = await scope.get(ExecutionService)
        other_user = make_test_user(user_id="no_access_user")

        exec_result = await exec_svc.execute_script(
            script="print('saga access denied')",
            user_id="owner_user",
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        with pytest.raises(SagaAccessDeniedError):
            await svc.get_execution_sagas(exec_result.execution_id, other_user)

    @pytest.mark.asyncio
    async def test_get_execution_sagas_owner_access(
        self, scope: AsyncContainer
    ) -> None:
        """Owner can get sagas for their execution."""
        svc: SagaService = await scope.get(SagaService)
        exec_svc: ExecutionService = await scope.get(ExecutionService)
        user_id = "saga_exec_owner"
        user = make_test_user(user_id=user_id)

        exec_result = await exec_svc.execute_script(
            script="print('owner sagas')",
            user_id=user_id,
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        result = await svc.get_execution_sagas(exec_result.execution_id, user)

        assert isinstance(result, SagaListResult)
        assert isinstance(result.sagas, list)


class TestGetSagaStatistics:
    """Tests for get_saga_statistics method."""

    @pytest.mark.asyncio
    async def test_get_saga_statistics_user(self, scope: AsyncContainer) -> None:
        """Get saga statistics for regular user."""
        svc: SagaService = await scope.get(SagaService)
        user = make_test_user()

        stats = await svc.get_saga_statistics(user)

        assert isinstance(stats, dict)

    @pytest.mark.asyncio
    async def test_get_saga_statistics_admin_all(
        self, scope: AsyncContainer
    ) -> None:
        """Admin can get all saga statistics."""
        svc: SagaService = await scope.get(SagaService)
        admin = make_test_user(user_id="stats_admin", role=UserRole.ADMIN)

        stats = await svc.get_saga_statistics(admin, include_all=True)

        assert isinstance(stats, dict)
