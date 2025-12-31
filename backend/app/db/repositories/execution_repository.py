import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from beanie.odm.enums import SortDirection

from app.db.docs import ExecutionDocument, ResourceUsage
from app.domain.execution import (
    DomainExecution,
    DomainExecutionCreate,
    DomainExecutionUpdate,
    ExecutionResultDomain,
)


class ExecutionRepository:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    async def create_execution(self, create_data: DomainExecutionCreate) -> DomainExecution:
        doc = ExecutionDocument(**asdict(create_data))
        self.logger.info("Inserting execution into MongoDB", extra={"execution_id": doc.execution_id})
        await doc.insert()
        self.logger.info("Inserted execution", extra={"execution_id": doc.execution_id})
        return DomainExecution(**doc.model_dump(exclude={"id"}))

    async def get_execution(self, execution_id: str) -> DomainExecution | None:
        self.logger.info("Searching for execution in MongoDB", extra={"execution_id": execution_id})
        doc = await ExecutionDocument.find_one({"execution_id": execution_id})
        if not doc:
            self.logger.warning("Execution not found in MongoDB", extra={"execution_id": execution_id})
            return None

        self.logger.info("Found execution in MongoDB", extra={"execution_id": execution_id})
        return DomainExecution(**doc.model_dump(exclude={"id"}))

    async def update_execution(self, execution_id: str, update_data: DomainExecutionUpdate) -> bool:
        doc = await ExecutionDocument.find_one({"execution_id": execution_id})
        if not doc:
            return False

        update_dict = {k: v for k, v in asdict(update_data).items() if v is not None}
        if "resource_usage" in update_dict:
            update_dict["resource_usage"] = ResourceUsage.model_validate(update_data.resource_usage)
        if update_dict:
            update_dict["updated_at"] = datetime.now(timezone.utc)
            await doc.set(update_dict)
        return True

    async def write_terminal_result(self, result: ExecutionResultDomain) -> bool:
        doc = await ExecutionDocument.find_one({"execution_id": result.execution_id})
        if not doc:
            self.logger.warning("No execution found", extra={"execution_id": result.execution_id})
            return False

        await doc.set(
            {
                "status": result.status,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "resource_usage": ResourceUsage.model_validate(result.resource_usage),
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
        return [DomainExecution(**doc.model_dump(exclude={"id"})) for doc in docs]

    async def count_executions(self, query: dict[str, Any]) -> int:
        return await ExecutionDocument.find(query).count()

    async def delete_execution(self, execution_id: str) -> bool:
        doc = await ExecutionDocument.find_one({"execution_id": execution_id})
        if not doc:
            return False
        await doc.delete()
        return True
