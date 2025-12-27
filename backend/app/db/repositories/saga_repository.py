from datetime import datetime, timezone

from pymongo import DESCENDING

from app.core.database_context import Collection, Database
from app.domain.enums.saga import SagaState
from app.domain.events.event_models import CollectionNames
from app.domain.saga.models import Saga, SagaFilter, SagaListResult
from app.infrastructure.mappers import SagaFilterMapper, SagaMapper


class SagaRepository:
    """Repository for saga data access.

    This repository handles all database operations for sagas,
    following clean architecture principles with no business logic
    or HTTP-specific concerns.
    """

    def __init__(self, database: Database):
        self.db = database
        self.sagas: Collection = self.db.get_collection(CollectionNames.SAGAS)
        self.executions: Collection = self.db.get_collection(CollectionNames.EXECUTIONS)
        self.mapper = SagaMapper()
        self.filter_mapper = SagaFilterMapper()

    async def upsert_saga(self, saga: Saga) -> bool:
        doc = self.mapper.to_mongo(saga)
        result = await self.sagas.replace_one(
            {"saga_id": saga.saga_id},
            doc,
            upsert=True,
        )
        return result.modified_count > 0

    async def get_saga_by_execution_and_name(self, execution_id: str, saga_name: str) -> Saga | None:
        doc = await self.sagas.find_one(
            {
                "execution_id": execution_id,
                "saga_name": saga_name,
            }
        )
        return self.mapper.from_mongo(doc) if doc else None

    async def get_saga(self, saga_id: str) -> Saga | None:
        doc = await self.sagas.find_one({"saga_id": saga_id})
        return self.mapper.from_mongo(doc) if doc else None

    async def get_sagas_by_execution(
        self, execution_id: str, state: SagaState | None = None, limit: int = 100, skip: int = 0
    ) -> SagaListResult:
        query: dict[str, object] = {"execution_id": execution_id}
        if state:
            query["state"] = state.value

        total = await self.sagas.count_documents(query)
        cursor = self.sagas.find(query).sort("created_at", DESCENDING).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        sagas = [self.mapper.from_mongo(doc) for doc in docs]

        return SagaListResult(sagas=sagas, total=total, skip=skip, limit=limit)

    async def list_sagas(self, saga_filter: SagaFilter, limit: int = 100, skip: int = 0) -> SagaListResult:
        query = self.filter_mapper.to_mongodb_query(saga_filter)

        # Get total count
        total = await self.sagas.count_documents(query)

        # Get sagas with pagination
        cursor = self.sagas.find(query).sort("created_at", DESCENDING).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)

        sagas = [self.mapper.from_mongo(doc) for doc in docs]

        return SagaListResult(sagas=sagas, total=total, skip=skip, limit=limit)

    async def update_saga_state(self, saga_id: str, state: SagaState, error_message: str | None = None) -> bool:
        update_data: dict[str, object] = {"state": state.value, "updated_at": datetime.now(timezone.utc)}

        if error_message:
            update_data["error_message"] = error_message

        result = await self.sagas.update_one({"saga_id": saga_id}, {"$set": update_data})

        return result.modified_count > 0

    async def get_user_execution_ids(self, user_id: str) -> list[str]:
        cursor = self.executions.find({"user_id": user_id}, {"execution_id": 1})
        docs = await cursor.to_list(length=None)
        return [doc["execution_id"] for doc in docs]

    async def count_sagas_by_state(self) -> dict[str, int]:
        pipeline = [{"$group": {"_id": "$state", "count": {"$sum": 1}}}]

        result = {}
        async for doc in await self.sagas.aggregate(pipeline):
            result[doc["_id"]] = doc["count"]

        return result

    async def find_timed_out_sagas(
        self,
        cutoff_time: datetime,
        states: list[SagaState] | None = None,
        limit: int = 100,
    ) -> list[Saga]:
        states = states or [SagaState.RUNNING, SagaState.COMPENSATING]
        query = {
            "state": {"$in": [s.value for s in states]},
            "created_at": {"$lt": cutoff_time},
        }
        cursor = self.sagas.find(query)
        docs = await cursor.to_list(length=limit)
        return [self.mapper.from_mongo(doc) for doc in docs]

    async def get_saga_statistics(self, saga_filter: SagaFilter | None = None) -> dict[str, object]:
        query = self.filter_mapper.to_mongodb_query(saga_filter) if saga_filter else {}

        # Basic counts
        total = await self.sagas.count_documents(query)

        # State distribution
        state_pipeline = [{"$match": query}, {"$group": {"_id": "$state", "count": {"$sum": 1}}}]

        states = {}
        async for doc in await self.sagas.aggregate(state_pipeline):
            states[doc["_id"]] = doc["count"]

        # Average duration for completed sagas
        duration_pipeline = [
            {"$match": {**query, "state": "completed", "completed_at": {"$ne": None}}},
            {"$project": {"duration": {"$subtract": ["$completed_at", "$created_at"]}}},
            {"$group": {"_id": None, "avg_duration": {"$avg": "$duration"}}},
        ]

        avg_duration = 0.0
        async for doc in await self.sagas.aggregate(duration_pipeline):
            # Convert milliseconds to seconds
            avg_duration = doc["avg_duration"] / 1000.0 if doc["avg_duration"] else 0.0

        return {"total": total, "by_state": states, "average_duration_seconds": avg_duration}
