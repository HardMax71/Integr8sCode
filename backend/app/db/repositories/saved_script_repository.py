from datetime import datetime, timezone
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.domain.saved_script.models import (
    DomainSavedScript,
    DomainSavedScriptCreate,
    DomainSavedScriptUpdate,
)


class SavedScriptRepository:
    def __init__(self, database: AsyncIOMotorDatabase):
        self.db = database

    async def create_saved_script(self, saved_script: DomainSavedScriptCreate, user_id: str) -> DomainSavedScript:
        # Build DB document with defaults
        now = datetime.now(timezone.utc)
        doc = {
            "script_id": str(uuid4()),
            "user_id": user_id,
            "name": saved_script.name,
            "script": saved_script.script,
            "lang": saved_script.lang,
            "lang_version": saved_script.lang_version,
            "description": saved_script.description,
            "created_at": now,
            "updated_at": now,
        }

        result = await self.db.saved_scripts.insert_one(doc)

        saved_doc = await self.db.saved_scripts.find_one({"_id": result.inserted_id})
        if not saved_doc:
            raise ValueError("Could not find saved script after insert")

        return DomainSavedScript(
            script_id=str(saved_doc.get("script_id")),
            user_id=str(saved_doc.get("user_id")),
            name=str(saved_doc.get("name")),
            script=str(saved_doc.get("script")),
            lang=str(saved_doc.get("lang")),
            lang_version=str(saved_doc.get("lang_version")),
            description=saved_doc.get("description"),
            created_at=saved_doc.get("created_at", now),
            updated_at=saved_doc.get("updated_at", now),
        )

    async def get_saved_script(
            self, script_id: str, user_id: str
    ) -> DomainSavedScript | None:
        saved_script = await self.db.saved_scripts.find_one(
            {"script_id": str(script_id), "user_id": user_id}
        )
        if not saved_script:
            return None
        return DomainSavedScript(
            script_id=str(saved_script.get("script_id")),
            user_id=str(saved_script.get("user_id")),
            name=str(saved_script.get("name")),
            script=str(saved_script.get("script")),
            lang=str(saved_script.get("lang")),
            lang_version=str(saved_script.get("lang_version")),
            description=saved_script.get("description"),
            created_at=saved_script.get("created_at"),
            updated_at=saved_script.get("updated_at"),
        )

    async def update_saved_script(
            self, script_id: str, user_id: str, update_data: DomainSavedScriptUpdate
    ) -> None:
        update: dict = {}
        if update_data.name is not None:
            update["name"] = update_data.name
        if update_data.script is not None:
            update["script"] = update_data.script
        if update_data.lang is not None:
            update["lang"] = update_data.lang
        if update_data.lang_version is not None:
            update["lang_version"] = update_data.lang_version
        if update_data.description is not None:
            update["description"] = update_data.description
        update["updated_at"] = datetime.now(timezone.utc)

        await self.db.saved_scripts.update_one(
            {"script_id": str(script_id), "user_id": user_id}, {"$set": update}
        )

    async def delete_saved_script(self, script_id: str, user_id: str) -> None:
        await self.db.saved_scripts.delete_one({"script_id": str(script_id), "user_id": user_id})

    async def list_saved_scripts(self, user_id: str) -> list[DomainSavedScript]:
        cursor = self.db.saved_scripts.find({"user_id": user_id})
        scripts: list[DomainSavedScript] = []
        async for script in cursor:
            scripts.append(
                DomainSavedScript(
                    script_id=str(script.get("script_id")),
                    user_id=str(script.get("user_id")),
                    name=str(script.get("name")),
                    script=str(script.get("script")),
                    lang=str(script.get("lang")),
                    lang_version=str(script.get("lang_version")),
                    description=script.get("description"),
                    created_at=script.get("created_at"),
                    updated_at=script.get("updated_at"),
                )
            )
        return scripts
