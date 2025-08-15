from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.logging import logger
from app.schemas_pydantic.execution import ExecutionInDB


class ExecutionRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection: AsyncIOMotorCollection = self.db.get_collection("executions")

    async def create_execution(self, execution: ExecutionInDB) -> ExecutionInDB:
        try:
            execution_dict = execution.model_dump()
            await self.collection.insert_one(execution_dict)
            return execution
        except Exception as e:
            logger.error(f"Database error creating execution {execution.execution_id}: {type(e).__name__}",
                         exc_info=True)
            raise

    async def get_execution(self, execution_id: str) -> ExecutionInDB | None:
        try:
            document = await self.collection.find_one({"execution_id": execution_id})
            logger.info(f"Retrieved execution {execution_id}, retrieved document: {document}")
            if document:
                return ExecutionInDB.model_validate(document)
            return None
        except Exception as e:
            logger.error(f"Database error fetching execution {execution_id}: {type(e).__name__}", exc_info=True)
            return None

    async def update_execution(self, execution_id: str, update_data: dict) -> bool:
        try:
            update_data.setdefault("updated_at", datetime.now(timezone.utc))
            update_payload = {"$set": update_data}

            result = await self.collection.update_one(
                {"execution_id": execution_id}, update_payload
            )
            return result.matched_count > 0
        except Exception as e:
            logger.error(f"Database error updating execution {execution_id}: {type(e).__name__}", exc_info=True)
            return False

    async def get_executions(
            self,
            query: dict,
            limit: int = 50,
            skip: int = 0,
            sort: list | None = None
    ) -> list[ExecutionInDB]:
        try:
            cursor = self.collection.find(query)
            if sort:
                cursor = cursor.sort(sort)
            cursor = cursor.skip(skip).limit(limit)

            executions = []
            async for doc in cursor:
                executions.append(ExecutionInDB.model_validate(doc))

            return executions
        except Exception as e:
            logger.error(f"Database error fetching executions: {type(e).__name__}", exc_info=True)
            return []

    async def count_executions(self, query: dict) -> int:
        try:
            return await self.collection.count_documents(query)
        except Exception as e:
            logger.error(f"Database error counting executions: {type(e).__name__}", exc_info=True)
            return 0

    async def delete_execution(self, execution_id: str) -> bool:
        try:
            result = await self.collection.delete_one({"execution_id": execution_id})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Database error deleting execution {execution_id}: {type(e).__name__}", exc_info=True)
            return False
