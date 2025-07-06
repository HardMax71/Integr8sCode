from datetime import datetime, timezone
from typing import Optional

from app.api.dependencies import get_db_dependency
from app.core.logging import logger
from app.schemas.execution import ExecutionInDB
from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase


class ExecutionRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection: AsyncIOMotorCollection = self.db.get_collection("executions")

    async def create_execution(self, execution: ExecutionInDB) -> str:
        execution_dict = execution.dict(by_alias=True)
        await self.collection.insert_one(execution_dict)
        return str(execution.id)

    async def get_execution(self, execution_id: str) -> Optional[ExecutionInDB]:
        try:
            document = await self.collection.find_one({"id": execution_id})
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
                {"id": execution_id}, update_payload
            )
            return result.matched_count > 0
        except Exception as e:
            logger.error(f"Database error updating execution {execution_id}: {type(e).__name__}", exc_info=True)
            return False


def get_execution_repository(
        db: AsyncIOMotorDatabase = Depends(get_db_dependency),
) -> ExecutionRepository:
    return ExecutionRepository(db)
