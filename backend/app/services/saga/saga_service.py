import logging

from app.db.repositories import ExecutionRepository, SagaRepository
from app.domain.enums import SagaState, UserRole
from app.domain.saga import (
    Saga,
    SagaAccessDeniedError,
    SagaCancellationResult,
    SagaFilter,
    SagaInvalidStateError,
    SagaListResult,
    SagaNotFoundError,
)
from app.domain.user import User
from app.services.saga import SagaOrchestrator


class SagaService:
    """Service for saga business logic and orchestration."""

    def __init__(
        self,
        saga_repo: SagaRepository,
        execution_repo: ExecutionRepository,
        orchestrator: SagaOrchestrator,
        logger: logging.Logger,
    ):
        self.saga_repo = saga_repo
        self.execution_repo = execution_repo
        self.orchestrator = orchestrator
        self.logger = logger

        self.logger.info(
            "SagaService initialized",
            extra={
                "saga_repo": type(saga_repo).__name__,
                "execution_repo": type(execution_repo).__name__,
                "orchestrator": type(orchestrator).__name__,
            },
        )

    async def check_execution_access(self, execution_id: str, user: User) -> bool:
        """Check if user has access to an execution."""
        # Admins have access to all executions
        if user.role == UserRole.ADMIN:
            return True

        # Check if user owns the execution
        execution = await self.execution_repo.get_execution(execution_id)
        if execution and execution.user_id == user.user_id:
            return True

        self.logger.debug(
            "Access denied to execution",
            extra={
                "user_id": user.user_id,
                "execution_id": execution_id,
                "user_role": user.role,
                "execution_exists": execution is not None,
            },
        )
        return False

    async def get_saga_with_access_check(self, saga_id: str, user: User) -> Saga:
        """Get saga with access control."""
        self.logger.debug(
            "Getting saga for user", extra={"saga_id": saga_id, "user_id": user.user_id, "user_role": user.role}
        )

        saga = await self.saga_repo.get_saga(saga_id)
        if not saga:
            self.logger.warning("Saga not found", extra={"saga_id": saga_id})
            raise SagaNotFoundError(saga_id)

        # Check access permissions
        if not await self.check_execution_access(saga.execution_id, user):
            self.logger.warning(
                "Access denied to saga",
                extra={"user_id": user.user_id, "saga_id": saga_id, "execution_id": saga.execution_id},
            )
            raise SagaAccessDeniedError(saga_id, user.user_id)

        return saga

    async def get_execution_sagas(
        self, execution_id: str, user: User, state: SagaState | None = None, limit: int = 100, skip: int = 0
    ) -> SagaListResult:
        """Get sagas for an execution with access control."""
        # Check access to execution
        if not await self.check_execution_access(execution_id, user):
            self.logger.warning(
                "Access denied to execution",
                extra={"user_id": user.user_id, "execution_id": execution_id, "user_role": user.role},
            )
            raise SagaAccessDeniedError(execution_id, user.user_id)

        return await self.saga_repo.get_sagas_by_execution(execution_id, state, limit=limit, skip=skip)

    async def list_user_sagas(
        self, user: User, state: SagaState | None = None, limit: int = 100, skip: int = 0
    ) -> SagaListResult:
        """List sagas accessible by user."""
        saga_filter = SagaFilter(state=state)

        # Non-admin users can only see their own sagas
        if user.role != UserRole.ADMIN:
            user_execution_ids = await self.saga_repo.get_user_execution_ids(user.user_id)
            # If user has no executions, return empty result immediately
            # (empty list would bypass the filter in repository)
            if not user_execution_ids:
                self.logger.debug(
                    "User has no executions, returning empty saga list",
                    extra={"user_id": user.user_id},
                )
                return SagaListResult(sagas=[], total=0, skip=skip, limit=limit)
            saga_filter.execution_ids = user_execution_ids
            self.logger.debug(
                "Filtering sagas for user",
                extra={
                    "user_id": user.user_id,
                    "execution_count": len(user_execution_ids),
                },
            )

        # Get sagas from repository
        result = await self.saga_repo.list_sagas(saga_filter, limit, skip)
        self.logger.debug(
            "Listed sagas for user",
            extra={
                "user_id": user.user_id,
                "count": len(result.sagas),
                "total": result.total,
                "state_filter": state,
            },
        )
        return result

    async def cancel_saga(self, saga_id: str, user: User) -> SagaCancellationResult:
        """Cancel a saga with permission check."""
        self.logger.info(
            "User requesting saga cancellation",
            extra={"user_id": user.user_id, "saga_id": saga_id, "user_role": user.role},
        )
        # Get saga with access check
        saga = await self.get_saga_with_access_check(saga_id, user)

        # Check if saga can be cancelled
        if saga.state not in [SagaState.RUNNING, SagaState.CREATED]:
            raise SagaInvalidStateError(saga_id, saga.state, "cancel")

        # Use orchestrator to cancel
        success = await self.orchestrator.cancel_saga(saga_id)
        if success:
            self.logger.info(
                "User cancelled saga",
                extra={"user_id": user.user_id, "saga_id": saga_id, "user_role": user.role},
            )
        else:
            self.logger.error("Failed to cancel saga", extra={"saga_id": saga_id, "user_id": user.user_id})
        message = "Saga cancelled successfully" if success else "Failed to cancel saga"
        return SagaCancellationResult(success=success, message=message, saga_id=saga_id)

    async def get_saga_statistics(self, user: User, include_all: bool = False) -> dict[str, object]:
        """Get saga statistics."""
        saga_filter = None

        # Non-admin users can only see their own statistics
        if user.role != UserRole.ADMIN or not include_all:
            user_execution_ids = await self.saga_repo.get_user_execution_ids(user.user_id)
            saga_filter = SagaFilter(execution_ids=user_execution_ids)

        return await self.saga_repo.get_saga_statistics(saga_filter)

