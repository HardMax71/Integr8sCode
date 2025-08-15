from motor.motor_asyncio import AsyncIOMotorDatabase

from app.schemas_pydantic.saved_script import SavedScriptInDB


class SavedScriptRepository:
    def __init__(self, database: AsyncIOMotorDatabase):
        self.db = database

    async def create_saved_script(self, saved_script: SavedScriptInDB) -> SavedScriptInDB:
        saved_script_dict = saved_script.model_dump(by_alias=True)
        # Convert UUID to string for MongoDB storage
        saved_script_dict['script_id'] = str(saved_script.script_id)

        # Insert the document
        result = await self.db.saved_scripts.insert_one(saved_script_dict)

        # Retrieve the saved document to ensure consistency
        saved_doc = await self.db.saved_scripts.find_one({"_id": result.inserted_id})
        if saved_doc:
            return SavedScriptInDB(**saved_doc)

        raise ValueError("Could not find saved script with id {}".format(saved_script.script_id))

    async def get_saved_script(
            self, script_id: str, user_id: str
    ) -> SavedScriptInDB | None:
        saved_script = await self.db.saved_scripts.find_one(
            {"script_id": str(script_id), "user_id": user_id}
        )
        if saved_script:
            return SavedScriptInDB(**saved_script)
        return None

    async def update_saved_script(
            self, script_id: str, user_id: str, update_data: dict
    ) -> None:
        await self.db.saved_scripts.update_one(
            {"script_id": str(script_id), "user_id": user_id}, {"$set": update_data}
        )

    async def delete_saved_script(self, script_id: str, user_id: str) -> None:
        await self.db.saved_scripts.delete_one({"script_id": str(script_id), "user_id": user_id})

    async def list_saved_scripts(self, user_id: str) -> list[SavedScriptInDB]:
        cursor = self.db.saved_scripts.find({"user_id": user_id})
        scripts: list[SavedScriptInDB] = []
        async for script in cursor:
            scripts.append(SavedScriptInDB(**script))
        return scripts
