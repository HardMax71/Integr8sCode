import dataclasses
from datetime import datetime, timezone
from typing import Any

import structlog
from beanie.odm.enums import SortDirection

from app.db.docs import ExecutionDocument
from app.domain.enums import QueuePriority
from app.domain.events import ResourceUsageDomain
from app.domain.execution import (
    DomainExecution,
    DomainExecutionCreate,
    ExecutionResultDomain,
)

_exec_fields = set(DomainExecution.__dataclass_fields__)
_result_fields = set(ExecutionResultDomain.__dataclass_fields__)


class ExecutionRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger):
        self.logger = logger

    def _to_domain(self, doc: ExecutionDocument) -> DomainExecution:
        data = doc.model_dump(include=_exec_fields)
        if data.get("resource_usage"):
            data["resource_usage"] = ResourceUsageDomain(**data["resource_usage"])
        return DomainExecution(**data)

    async def create_execution(self, create_data: DomainExecutionCreate) -> DomainExecution:
        doc = ExecutionDocument(**dataclasses.asdict(create_data))
        self.logger.info("Inserting execution into MongoDB", execution_id=doc.execution_id)
        await doc.insert()
        self.logger.info("Inserted execution", execution_id=doc.execution_id)
        return self._to_domain(doc)

    async def get_execution(self, execution_id: str) -> DomainExecution | None:
        self.logger.info("Searching for execution in MongoDB", execution_id=execution_id)
        doc = await ExecutionDocument.find_one(ExecutionDocument.execution_id == execution_id)
        if not doc:
            self.logger.warning("Execution not found in MongoDB", execution_id=execution_id)
            return None

        self.logger.info("Found execution in MongoDB", execution_id=execution_id)
        return self._to_domain(doc)

    async def write_terminal_result(self, result: ExecutionResultDomain) -> bool:
        doc = await ExecutionDocument.find_one(ExecutionDocument.execution_id == result.execution_id)
        if not doc:
            self.logger.warning("No execution found", execution_id=result.execution_id)
            return False

        await doc.set(
            {
                "status": result.status,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "resource_usage": dataclasses.asdict(result.resource_usage) if result.resource_usage else None,
                "error_type": result.error_type,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return True

    async def get_executions(
        self, query: dict[str, Any], limit: int = 50, skip: int = 0, sort: list[tuple[str, int]] | None = None
    ) -> list[DomainExecution]:
        find_query = ExecutionDocument.find(query)
        if sort:
            beanie_sort = [
                (field, SortDirection.ASCENDING if direction == 1 else SortDirection.DESCENDING)
                for field, direction in sort
            ]
            find_query = find_query.sort(beanie_sort)
        docs = await find_query.skip(skip).limit(limit).to_list()
        return [self._to_domain(doc) for doc in docs]

    async def count_executions(self, query: dict[str, Any]) -> int:
        return await ExecutionDocument.find(query).count()

    async def update_priority(self, execution_id: str, priority: QueuePriority) -> DomainExecution | None:
        doc = await ExecutionDocument.find_one(ExecutionDocument.execution_id == execution_id)
        if not doc:
            return None
        await doc.set({"priority": priority, "updated_at": datetime.now(timezone.utc)})
        return self._to_domain(doc)

    async def get_execution_result(self, execution_id: str) -> ExecutionResultDomain | None:
        doc = await ExecutionDocument.find_one(ExecutionDocument.execution_id == execution_id)
        if not doc:
            return None
        data = doc.model_dump(include=_result_fields)
        if data.get("resource_usage"):
            data["resource_usage"] = ResourceUsageDomain(**data["resource_usage"])
        return ExecutionResultDomain(**data)

    async def delete_execution(self, execution_id: str) -> bool:
        doc = await ExecutionDocument.find_one(ExecutionDocument.execution_id == execution_id)
        if not doc:
            return False
        await doc.delete()
        return True
