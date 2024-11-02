from datetime import datetime
from typing import List
from app.db.repositories.saved_script_repository import (
    SavedScriptRepository,
    get_saved_script_repository,
)
from app.models.saved_script import (
    SavedScriptCreate,
    SavedScriptInDB,
    SavedScriptUpdate,
)
from fastapi import Depends


class SavedScriptService:
    def __init__(self, saved_script_repo: SavedScriptRepository):
        self.saved_script_repo = saved_script_repo

    async def create_saved_script(
        self, saved_script_create: SavedScriptCreate, user_id: str
    ) -> SavedScriptInDB:
        saved_script_in_db = SavedScriptInDB(
            **saved_script_create.dict(), user_id=user_id
        )
        await self.saved_script_repo.create_saved_script(saved_script_in_db)
        return saved_script_in_db

    async def get_saved_script(self, script_id: str, user_id: str) -> SavedScriptInDB:
        return await self.saved_script_repo.get_saved_script(script_id, user_id)

    async def update_saved_script(
        self, script_id: str, user_id: str, update_data: SavedScriptUpdate
    ):
        update_dict = update_data.dict(exclude_unset=True)
        update_dict["updated_at"] = datetime.utcnow()
        await self.saved_script_repo.update_saved_script(
            script_id, user_id, update_dict
        )

    async def delete_saved_script(self, script_id: str, user_id: str):
        await self.saved_script_repo.delete_saved_script(script_id, user_id)

    async def list_saved_scripts(self, user_id: str) -> List[SavedScriptInDB]:
        return await self.saved_script_repo.list_saved_scripts(user_id)


def get_saved_script_service(
    saved_script_repo: SavedScriptRepository = Depends(get_saved_script_repository),
) -> SavedScriptService:
    return SavedScriptService(saved_script_repo)
