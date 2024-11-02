from typing import List, Optional

from app.api.dependencies import get_db_dependency
from app.models.saved_script import SavedScriptInDB
from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase


class SavedScriptRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def create_saved_script(self, saved_script: SavedScriptInDB):
        saved_script_dict = saved_script.dict(by_alias=True)
        await self.db.saved_scripts.insert_one(saved_script_dict)
        return saved_script.id

    async def get_saved_script(
        self, script_id: str, user_id: str
    ) -> Optional[SavedScriptInDB]:
        saved_script = await self.db.saved_scripts.find_one(
            {"_id": script_id, "user_id": user_id}
        )
        if saved_script:
            return SavedScriptInDB(**saved_script)
        return None

    async def update_saved_script(
        self, script_id: str, user_id: str, update_data: dict
    ):
        await self.db.saved_scripts.update_one(
            {"_id": script_id, "user_id": user_id}, {"$set": update_data}
        )

    async def delete_saved_script(self, script_id: str, user_id: str):
        await self.db.saved_scripts.delete_one({"_id": script_id, "user_id": user_id})

    async def list_saved_scripts(self, user_id: str) -> List[SavedScriptInDB]:
        cursor = self.db.saved_scripts.find({"user_id": user_id})
        scripts = []
        async for script in cursor:
            scripts.append(SavedScriptInDB(**script))
        return scripts


def get_saved_script_repository(
    db: AsyncIOMotorDatabase = Depends(get_db_dependency),
) -> SavedScriptRepository:
    return SavedScriptRepository(db)
