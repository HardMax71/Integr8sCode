from datetime import datetime, timezone
from typing import Any

import structlog
from beanie.odm.enums import SortDirection

from app.db.docs import ExecutionDocument
from app.domain.execution import (
    DomainExecution,
    DomainExecutionCreate,
    ExecutionResultDomain,
)


class ExecutionRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger):
        self.logger = logger

    async def create_execution(self, create_data: DomainExecutionCreate) -> DomainExecution:
        doc = ExecutionDocument(**create_data.model_dump())
        self.logger.info("Inserting execution into MongoDB", execution_id=doc.execution_id)
        await doc.insert()
        self.logger.info("Inserted execution", execution_id=doc.execution_id)
        return DomainExecution.model_validate(doc)

    async def get_execution(self, execution_id: str) -> DomainExecution | None:
        self.logger.info("Searching for execution in MongoDB", execution_id=execution_id)
        doc = await ExecutionDocument.find_one(ExecutionDocument.execution_id == execution_id)
        if not doc:
            self.logger.warning("Execution not found in MongoDB", execution_id=execution_id)
            return None

        self.logger.info("Found execution in MongoDB", execution_id=execution_id)
        return DomainExecution.model_validate(doc)

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
                "resource_usage": result.resource_usage.model_dump() if result.resource_usage else None,
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
        return [DomainExecution.model_validate(doc) for doc in docs]

    async def count_executions(self, query: dict[str, Any]) -> int:
        return await ExecutionDocument.find(query).count()

    async def delete_execution(self, execution_id: str) -> bool:
        doc = await ExecutionDocument.find_one(ExecutionDocument.execution_id == execution_id)
        if not doc:
            return False
        await doc.delete()
        return True
