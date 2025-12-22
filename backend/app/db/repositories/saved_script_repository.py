from app.core.database_context import Collection, Database
from app.domain.events.event_models import CollectionNames
from app.domain.saved_script import (
    DomainSavedScript,
    DomainSavedScriptCreate,
    DomainSavedScriptUpdate,
)
from app.infrastructure.mappers import SavedScriptMapper


class SavedScriptRepository:
    def __init__(self, database: Database):
        self.db = database
        self.collection: Collection = self.db.get_collection(CollectionNames.SAVED_SCRIPTS)
        self.mapper = SavedScriptMapper()

    async def create_saved_script(self, saved_script: DomainSavedScriptCreate, user_id: str) -> DomainSavedScript:
        # Build DB document with defaults
        doc = self.mapper.to_insert_document(saved_script, user_id)

        result = await self.collection.insert_one(doc)
        if result.inserted_id is None:
            raise ValueError("Insert not acknowledged")
        return self.mapper.from_mongo_document(doc)

    async def get_saved_script(
            self, script_id: str, user_id: str
    ) -> DomainSavedScript | None:
        saved_script = await self.collection.find_one(
            {"script_id": script_id, "user_id": user_id}
        )
        if not saved_script:
            return None
        return self.mapper.from_mongo_document(saved_script)

    async def update_saved_script(
            self, script_id: str, user_id: str, update_data: DomainSavedScriptUpdate
    ) -> None:
        update = self.mapper.to_update_dict(update_data)

        await self.collection.update_one(
            {"script_id": script_id, "user_id": user_id}, {"$set": update}
        )

    async def delete_saved_script(self, script_id: str, user_id: str) -> None:
        await self.collection.delete_one({"script_id": script_id, "user_id": user_id})

    async def list_saved_scripts(self, user_id: str) -> list[DomainSavedScript]:
        cursor = self.collection.find({"user_id": user_id})
        scripts: list[DomainSavedScript] = []
        async for script in cursor:
            scripts.append(self.mapper.from_mongo_document(script))
        return scripts
