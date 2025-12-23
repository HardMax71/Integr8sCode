from app.core.database_context import Collection, Database
from app.domain.events.event_models import CollectionNames
from app.domain.execution import DomainExecution
from app.domain.sse import SSEEventDomain, SSEExecutionStatusDomain
from app.infrastructure.mappers import SSEMapper


class SSERepository:
    def __init__(self, database: Database):
        self.db = database
        self.executions_collection: Collection = self.db.get_collection(CollectionNames.EXECUTIONS)
        self.events_collection: Collection = self.db.get_collection(CollectionNames.EVENTS)
        self.mapper = SSEMapper()

    async def get_execution_status(self, execution_id: str) -> SSEExecutionStatusDomain | None:
        execution = await self.executions_collection.find_one(
            {"execution_id": execution_id}, {"status": 1, "execution_id": 1, "_id": 0}
        )

        if execution:
            return self.mapper.to_execution_status(execution_id, execution.get("status", "unknown"))
        return None

    async def get_execution_events(self, execution_id: str, limit: int = 100, skip: int = 0) -> list[SSEEventDomain]:
        cursor = (
            self.events_collection.find({"aggregate_id": execution_id}).sort("timestamp", 1).skip(skip).limit(limit)
        )

        events: list[SSEEventDomain] = []
        async for event in cursor:
            events.append(self.mapper.event_from_mongo_document(event))
        return events

    async def get_execution_for_user(self, execution_id: str, user_id: str) -> DomainExecution | None:
        doc = await self.executions_collection.find_one({"execution_id": execution_id, "user_id": user_id})
        if not doc:
            return None
        return self.mapper.execution_from_mongo_document(doc)

    async def get_execution(self, execution_id: str) -> DomainExecution | None:
        doc = await self.executions_collection.find_one({"execution_id": execution_id})
        if not doc:
            return None
        return self.mapper.execution_from_mongo_document(doc)
