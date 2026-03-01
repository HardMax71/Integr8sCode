from typing import Any

import structlog

from app.db import ExecutionRepository
from app.domain.enums import ExecutionStatus, QueuePriority
from app.domain.execution import DomainExecution, ExecutionNotFoundError
from app.services.execution_queue import ExecutionQueueService
from app.services.runtime_settings import RuntimeSettingsLoader


class AdminExecutionService:
    """Admin service for managing executions and the execution queue."""

    def __init__(
        self,
        execution_repo: ExecutionRepository,
        queue_service: ExecutionQueueService,
        runtime_settings: RuntimeSettingsLoader,
        logger: structlog.stdlib.BoundLogger,
    ) -> None:
        self._repo = execution_repo
        self._queue = queue_service
        self._runtime_settings = runtime_settings
        self._logger = logger

    async def list_executions(
        self,
        status: ExecutionStatus | None = None,
        priority: QueuePriority | None = None,
        user_id: str | None = None,
        limit: int = 50,
        skip: int = 0,
    ) -> tuple[list[DomainExecution], int]:
        query: dict[str, Any] = {}
        if status:
            query["status"] = status
        if priority:
            query["priority"] = priority
        if user_id:
            query["user_id"] = user_id

        executions = await self._repo.get_executions(
            query=query, limit=limit, skip=skip, sort=[("created_at", -1)],
        )
        total = await self._repo.count_executions(query)
        return executions, total

    async def update_priority(
        self, execution_id: str, new_priority: QueuePriority,
    ) -> DomainExecution:
        updated = await self._repo.update_priority(execution_id, new_priority)
        if not updated:
            raise ExecutionNotFoundError(execution_id)

        await self._queue.update_priority(execution_id, new_priority)

        self._logger.info(
            "Admin updated execution priority",
            execution_id=execution_id,
            new_priority=new_priority,
        )
        return updated

    async def get_queue_status(self) -> dict[str, Any]:
        queue_status = await self._queue.get_queue_status()
        by_priority = await self._queue.get_pending_by_priority()
        settings = await self._runtime_settings.get_effective_settings()

        return {
            **queue_status,
            "max_concurrent": settings.max_concurrent_executions,
            "by_priority": by_priority,
        }
