from typing import Optional

from app.api.dependencies import get_db_dependency
from app.schemas.execution import ExecutionInDB
from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase


class ExecutionRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def create_execution(self, execution: ExecutionInDB) -> str:
        execution_dict = execution.dict(by_alias=True)
        await self.db.executions.insert_one(execution_dict)
        return str(execution.id)

    async def get_execution(self, execution_id: str) -> Optional[ExecutionInDB]:
        execution = await self.db.executions.find_one({"_id": execution_id})
        if execution:
            return ExecutionInDB(**execution)
        return None

    async def update_execution(self, execution_id: str, update_data: dict) -> None:
        await self.db.executions.update_one(
            {"_id": execution_id}, {"$set": update_data}
        )


def get_execution_repository(
        db: AsyncIOMotorDatabase = Depends(get_db_dependency),
) -> ExecutionRepository:
    return ExecutionRepository(db)
