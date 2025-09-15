from app.core.logging import logger
from app.db.repositories.execution_repository import ExecutionRepository
from app.db.repositories.saga_repository import SagaRepository
from app.domain.enums.saga import SagaState
from app.domain.enums.user import UserRole
from app.domain.saga.exceptions import (
    SagaAccessDeniedError,
    SagaInvalidStateError,
    SagaNotFoundError,
)
from app.domain.saga.models import Saga, SagaFilter, SagaListResult
from app.domain.user import User
from app.services.saga import SagaOrchestrator


class SagaService:
    """Service for saga business logic and orchestration."""

    def __init__(
            self,
            saga_repo: SagaRepository,
            execution_repo: ExecutionRepository,
            orchestrator: SagaOrchestrator
    ):
        self.saga_repo = saga_repo
        self.execution_repo = execution_repo
        self.orchestrator = orchestrator

        logger.info(
            "SagaService initialized",
            extra={
                "saga_repo": type(saga_repo).__name__,
                "execution_repo": type(execution_repo).__name__,
                "orchestrator": type(orchestrator).__name__
            }
        )

    async def check_execution_access(
            self,
            execution_id: str,
            user: User
    ) -> bool:
        """Check if user has access to an execution."""
        # Admins have access to all executions
        if user.role == UserRole.ADMIN:
            return True

        # Check if user owns the execution
        execution = await self.execution_repo.get_execution(execution_id)
        if execution and execution.user_id == user.user_id:
            return True

        logger.debug(
            f"Access denied for user {user.user_id} to execution {execution_id}",
            extra={"user_role": user.role, "execution_exists": execution is not None}
        )
        return False

    async def get_saga_with_access_check(
            self,
            saga_id: str,
            user: User
    ) -> Saga:
        """Get saga with access control."""
        logger.debug(
            f"Getting saga {saga_id} for user {user.user_id}",
            extra={"user_role": user.role}
        )

        saga = await self.saga_repo.get_saga(saga_id)
        if not saga:
            logger.warning(f"Saga {saga_id} not found")
            raise SagaNotFoundError(f"Saga {saga_id} not found")

        # Check access permissions
        if not await self.check_execution_access(saga.execution_id, user):
            logger.warning(
                f"Access denied for user {user.user_id} to saga {saga_id}",
                extra={"execution_id": saga.execution_id}
            )
            raise SagaAccessDeniedError(
                f"Access denied - you don't have access to execution {saga.execution_id}"
            )

        return saga

    async def get_execution_sagas(
            self,
            execution_id: str,
            user: User,
            state: SagaState | None = None
    ) -> list[Saga]:
        """Get sagas for an execution with access control."""
        # Check access to execution
        if not await self.check_execution_access(execution_id, user):
            logger.warning(
                f"Access denied for user {user.user_id} to execution {execution_id}",
                extra={"user_role": user.role}
            )
            raise SagaAccessDeniedError(
                f"Access denied - no access to execution {execution_id}"
            )

        return await self.saga_repo.get_sagas_by_execution(execution_id, state)

    async def list_user_sagas(
            self,
            user: User,
            state: SagaState | None = None,
            limit: int = 100,
            skip: int = 0
    ) -> SagaListResult:
        """List sagas accessible by user."""
        saga_filter = SagaFilter(state=state)

        # Non-admin users can only see their own sagas
        if user.role != UserRole.ADMIN:
            user_execution_ids = await self.saga_repo.get_user_execution_ids(user.user_id)
            saga_filter.execution_ids = user_execution_ids
            logger.debug(
                f"Filtering sagas for user {user.user_id}",
                extra={"execution_count": len(user_execution_ids) if user_execution_ids else 0}
            )

        # Get sagas from repository
        result = await self.saga_repo.list_sagas(saga_filter, limit, skip)
        logger.debug(
            f"Listed {len(result.sagas)} sagas for user {user.user_id}",
            extra={"total": result.total, "state_filter": str(state) if state else None}
        )
        return result

    async def cancel_saga(
            self,
            saga_id: str,
            user: User
    ) -> bool:
        """Cancel a saga with permission check."""
        logger.info(
            f"User {user.user_id} requesting cancellation of saga {saga_id}",
            extra={"user_role": user.role}
        )
        # Get saga with access check
        saga = await self.get_saga_with_access_check(saga_id, user)

        # Check if saga can be cancelled
        if saga.state not in [SagaState.RUNNING, SagaState.CREATED]:
            raise SagaInvalidStateError(
                f"Cannot cancel saga in {saga.state} state. "
                f"Only RUNNING or CREATED sagas can be cancelled."
            )

        # Use orchestrator to cancel
        success = await self.orchestrator.cancel_saga(saga_id)
        if success:
            logger.info(
                f"User {user.user_id} cancelled saga {saga_id}",
                extra={"user_role": user.role, "saga_id": saga_id}
            )
        else:
            logger.error(
                f"Failed to cancel saga {saga_id} for user {user.user_id}",
                extra={"saga_id": saga_id}
            )
        return success

    async def get_saga_statistics(
            self,
            user: User,
            include_all: bool = False
    ) -> dict[str, object]:
        """Get saga statistics."""
        saga_filter = None

        # Non-admin users can only see their own statistics
        if user.role != UserRole.ADMIN or not include_all:
            user_execution_ids = await self.saga_repo.get_user_execution_ids(user.user_id)
            saga_filter = SagaFilter(execution_ids=user_execution_ids)

        return await self.saga_repo.get_saga_statistics(saga_filter)

    async def get_saga_status_from_orchestrator(
            self,
            saga_id: str,
            user: User
    ) -> Saga | None:
        """Get saga status from orchestrator with fallback to database."""
        logger.debug(f"Getting live saga status for {saga_id}")

        # Try orchestrator first for live status
        saga = await self.orchestrator.get_saga_status(saga_id)
        if saga:

            # Check access
            if not await self.check_execution_access(saga.execution_id, user):
                logger.warning(
                    f"Access denied for user {user.user_id} to live saga {saga_id}",
                    extra={"execution_id": saga.execution_id}
                )
                raise SagaAccessDeniedError(f"Access denied - no access to execution {saga.execution_id}")

            logger.debug(f"Retrieved live status for saga {saga_id}")
            return saga

        # Fall back to repository
        logger.debug(f"No live status found for saga {saga_id}, checking database")
        return await self.get_saga_with_access_check(saga_id, user)
