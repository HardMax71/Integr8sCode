from datetime import datetime, timezone

from app.core.database_context import Collection, Database
from app.domain.enums.execution import ExecutionStatus
from app.domain.events.event_models import CollectionNames
from app.domain.execution import DomainExecution
from app.domain.sse import SSEExecutionStatusDomain
from app.infrastructure.mappers import SSEMapper


class SSERepository:
    def __init__(self, database: Database) -> None:
        self.db = database
        self.executions_collection: Collection = self.db.get_collection(CollectionNames.EXECUTIONS)
        self.mapper = SSEMapper()

    async def get_execution_status(self, execution_id: str) -> SSEExecutionStatusDomain | None:
        doc = await self.executions_collection.find_one(
            {"execution_id": execution_id}, {"status": 1, "_id": 0}
        )
        if not doc:
            return None
        return SSEExecutionStatusDomain(
            execution_id=execution_id,
            status=ExecutionStatus(doc["status"]),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    async def get_execution(self, execution_id: str) -> DomainExecution | None:
        doc = await self.executions_collection.find_one({"execution_id": execution_id})
        if not doc:
            return None
        return self.mapper.execution_from_mongo_document(doc)
