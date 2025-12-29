from dataclasses import asdict

from beanie.operators import Eq

from app.db.docs import SavedScriptDocument
from app.domain.saved_script import DomainSavedScriptCreate, DomainSavedScriptUpdate


class SavedScriptRepository:
    async def create_saved_script(self, create_data: DomainSavedScriptCreate, user_id: str) -> SavedScriptDocument:
        doc = SavedScriptDocument(
            name=create_data.name,
            script=create_data.script,
            user_id=user_id,
            lang=create_data.lang,
            lang_version=create_data.lang_version,
            description=create_data.description,
        )
        await doc.insert()
        return doc

    async def get_saved_script(self, script_id: str, user_id: str) -> SavedScriptDocument | None:
        return await SavedScriptDocument.find_one(
            Eq(SavedScriptDocument.script_id, script_id),
            Eq(SavedScriptDocument.user_id, user_id),
        )

    async def update_saved_script(
        self,
        script_id: str,
        user_id: str,
        update_data: DomainSavedScriptUpdate,
    ) -> SavedScriptDocument | None:
        doc = await self.get_saved_script(script_id, user_id)
        if not doc:
            return None

        update_dict = {k: v for k, v in asdict(update_data).items() if v is not None}
        await doc.set(update_dict)
        return doc

    async def delete_saved_script(self, script_id: str, user_id: str) -> bool:
        doc = await self.get_saved_script(script_id, user_id)
        if not doc:
            return False
        await doc.delete()
        return True

    async def list_saved_scripts(self, user_id: str) -> list[SavedScriptDocument]:
        return await SavedScriptDocument.find(Eq(SavedScriptDocument.user_id, user_id)).to_list()
