from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import DESCENDING

from app.core.logging import logger
from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga, SagaFilter, SagaListResult
from app.infrastructure.mappers.saga_mapper import SagaFilterMapper, SagaMapper


class SagaRepository:
    """Repository for saga data access.
    
    This repository handles all database operations for sagas,
    following clean architecture principles with no business logic
    or HTTP-specific concerns.
    """

    def __init__(self, database: AsyncIOMotorDatabase):
        """Initialize saga repository.
        
        Args:
            database: MongoDB database instance
        """
        self.db = database
        self.collection: AsyncIOMotorCollection = self.db.get_collection("sagas")
        self.mapper = SagaMapper()
        self.filter_mapper = SagaFilterMapper()

    async def upsert_saga(self, saga: Saga) -> bool:
        """Create or update a saga document from domain.

        Args:
            saga: Domain saga to persist

        Returns:
            True if upsert acknowledged
        """
        try:
            doc = self.mapper.to_mongo(saga)
            _ = await self.collection.replace_one(
                {"saga_id": saga.saga_id},
                doc,
                upsert=True,
            )
            return True
        except Exception as e:
            logger.error(f"Error upserting saga {saga.saga_id}: {e}")
            return False

    async def get_saga_by_execution_and_name(self, execution_id: str, saga_name: str) -> Saga | None:
        """Fetch a saga by execution and saga name.

        Args:
            execution_id: Execution identifier
            saga_name: Saga type/name

        Returns:
            Saga if found, else None
        """
        try:
            doc = await self.collection.find_one({
                "execution_id": execution_id,
                "saga_name": saga_name,
            })
            return self.mapper.from_mongo(doc) if doc else None
        except Exception as e:
            logger.error(
                f"Error getting saga for execution {execution_id} and name {saga_name}: {e}"
            )
            return None

    async def get_saga(self, saga_id: str) -> Saga | None:
        """Get saga by ID.
        
        Args:
            saga_id: The saga identifier
            
        Returns:
            Saga domain model if found, None otherwise
        """
        try:
            doc = await self.collection.find_one({"saga_id": saga_id})
            return self.mapper.from_mongo(doc) if doc else None
        except Exception as e:
            logger.error(f"Error getting saga {saga_id}: {e}")
            return None

    async def get_sagas_by_execution(
            self,
            execution_id: str,
            state: str | None = None
    ) -> list[Saga]:
        """Get all sagas for an execution.
        
        Args:
            execution_id: The execution identifier
            state: Optional state filter
            
        Returns:
            List of saga domain models, sorted by created_at descending
        """
        try:
            query: dict[str, object] = {"execution_id": execution_id}
            if state:
                query["state"] = state

            cursor = self.collection.find(query).sort("created_at", DESCENDING)
            docs = await cursor.to_list(length=None)
            return [self.mapper.from_mongo(doc) for doc in docs]
        except Exception as e:
            logger.error(f"Error getting sagas for execution {execution_id}: {e}")
            return []

    async def list_sagas(
            self,
            filter: SagaFilter,
            limit: int = 100,
            skip: int = 0
    ) -> SagaListResult:
        """List sagas with filtering and pagination.
        
        Args:
            filter: Filter criteria for sagas
            limit: Maximum number of results
            skip: Number of results to skip
            
        Returns:
            SagaListResult with sagas and pagination info
        """
        try:
            query = self.filter_mapper.to_mongodb_query(filter)

            # Get total count
            total = await self.collection.count_documents(query)

            # Get sagas with pagination
            cursor = (self.collection.find(query)
                      .sort("created_at", DESCENDING)
                      .skip(skip)
                      .limit(limit))
            docs = await cursor.to_list(length=limit)

            sagas = [self.mapper.from_mongo(doc) for doc in docs]

            return SagaListResult(
                sagas=sagas,
                total=total,
                skip=skip,
                limit=limit
            )
        except Exception as e:
            logger.error(f"Error listing sagas: {e}")
            return SagaListResult(sagas=[], total=0, skip=skip, limit=limit)

    async def update_saga_state(
            self,
            saga_id: str,
            state: str,
            error_message: str | None = None
    ) -> bool:
        """Update saga state.
        
        Args:
            saga_id: The saga identifier
            state: New state value
            error_message: Optional error message
            
        Returns:
            True if updated successfully, False otherwise
        """
        try:
            from datetime import datetime, timezone

            update_data = {
                "state": state,
                "updated_at": datetime.now(timezone.utc)
            }

            if error_message:
                update_data["error_message"] = error_message

            result = await self.collection.update_one(
                {"saga_id": saga_id},
                {"$set": update_data}
            )

            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error updating saga {saga_id} state: {e}")
            return False

    async def get_user_execution_ids(self, user_id: str) -> list[str]:
        """Get execution IDs accessible by a user.
        
        This is a helper method that queries executions collection
        to find executions owned by a user.
        
        Args:
            user_id: The user identifier
            
        Returns:
            List of execution IDs
        """
        try:
            executions_collection = self.db.get_collection("executions")
            cursor = executions_collection.find(
                {"user_id": user_id},
                {"execution_id": 1}
            )
            docs = await cursor.to_list(length=None)
            return [doc["execution_id"] for doc in docs]
        except Exception as e:
            logger.error(f"Error getting user execution IDs: {e}")
            return []

    async def count_sagas_by_state(self) -> dict[str, int]:
        """Get count of sagas by state.
        
        Returns:
            Dictionary mapping state to count
        """
        try:
            pipeline = [
                {"$group": {
                    "_id": "$state",
                    "count": {"$sum": 1}
                }}
            ]

            result = {}
            async for doc in self.collection.aggregate(pipeline):
                result[doc["_id"]] = doc["count"]

            return result
        except Exception as e:
            logger.error(f"Error counting sagas by state: {e}")
            return {}

    async def find_timed_out_sagas(
            self,
            cutoff_time: datetime,
            states: list[SagaState] | None = None,
            limit: int = 100,
    ) -> list[Saga]:
        """Return sagas older than cutoff in provided states.

        Args:
            cutoff_time: datetime threshold for created_at
            states: filter states (defaults to RUNNING and COMPENSATING)
            limit: max items to return

        Returns:
            List of Saga domain objects
        """
        try:
            states = states or [SagaState.RUNNING, SagaState.COMPENSATING]
            query = {
                "state": {"$in": [s.value for s in states]},
                "created_at": {"$lt": cutoff_time},
            }
            cursor = self.collection.find(query)
            docs = await cursor.to_list(length=limit)
            return [self.mapper.from_mongo(doc) for doc in docs]
        except Exception as e:
            logger.error(f"Error finding timed out sagas: {e}")
            return []

    async def get_saga_statistics(
            self,
            filter: SagaFilter | None = None
    ) -> dict[str, object]:
        """Get saga statistics.
        
        Args:
            filter: Optional filter criteria
            
        Returns:
            Dictionary with statistics
        """
        try:
            query = self.filter_mapper.to_mongodb_query(filter) if filter else {}

            # Basic counts
            total = await self.collection.count_documents(query)

            # State distribution
            state_pipeline = [
                {"$match": query},
                {"$group": {
                    "_id": "$state",
                    "count": {"$sum": 1}
                }}
            ]

            states = {}
            async for doc in self.collection.aggregate(state_pipeline):
                states[doc["_id"]] = doc["count"]

            # Average duration for completed sagas
            duration_pipeline = [
                {"$match": {**query, "state": "completed", "completed_at": {"$ne": None}}},
                {"$project": {
                    "duration": {
                        "$subtract": ["$completed_at", "$created_at"]
                    }
                }},
                {"$group": {
                    "_id": None,
                    "avg_duration": {"$avg": "$duration"}
                }}
            ]

            avg_duration = 0.0
            async for doc in self.collection.aggregate(duration_pipeline):
                # Convert milliseconds to seconds
                avg_duration = doc["avg_duration"] / 1000.0 if doc["avg_duration"] else 0.0

            return {
                "total": total,
                "by_state": states,
                "average_duration_seconds": avg_duration
            }
        except Exception as e:
            logger.error(f"Error getting saga statistics: {e}")
            return {"total": 0, "by_state": {}, "average_duration_seconds": 0.0}
