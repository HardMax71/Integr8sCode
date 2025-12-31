from dataclasses import asdict

from beanie.operators import Eq

from app.db.docs import SavedScriptDocument
from app.domain.saved_script import DomainSavedScript, DomainSavedScriptCreate, DomainSavedScriptUpdate


class SavedScriptRepository:
    async def create_saved_script(self, create_data: DomainSavedScriptCreate, user_id: str) -> DomainSavedScript:
        doc = SavedScriptDocument(**asdict(create_data), user_id=user_id)
        await doc.insert()
        return DomainSavedScript(**doc.model_dump(exclude={"id", "revision_id"}))

    async def get_saved_script(self, script_id: str, user_id: str) -> DomainSavedScript | None:
        doc = await SavedScriptDocument.find_one(
            Eq(SavedScriptDocument.script_id, script_id),
            Eq(SavedScriptDocument.user_id, user_id),
        )
        return DomainSavedScript(**doc.model_dump(exclude={"id", "revision_id"})) if doc else None

    async def update_saved_script(
        self,
        script_id: str,
        user_id: str,
        update_data: DomainSavedScriptUpdate,
    ) -> DomainSavedScript | None:
        doc = await SavedScriptDocument.find_one(
            Eq(SavedScriptDocument.script_id, script_id),
            Eq(SavedScriptDocument.user_id, user_id),
        )
        if not doc:
            return None

        update_dict = {k: v for k, v in asdict(update_data).items() if v is not None}
        await doc.set(update_dict)
        return DomainSavedScript(**doc.model_dump(exclude={"id", "revision_id"}))

    async def delete_saved_script(self, script_id: str, user_id: str) -> bool:
        doc = await SavedScriptDocument.find_one(
            Eq(SavedScriptDocument.script_id, script_id),
            Eq(SavedScriptDocument.user_id, user_id),
        )
        if not doc:
            return False
        await doc.delete()
        return True

    async def list_saved_scripts(self, user_id: str) -> list[DomainSavedScript]:
        docs = await SavedScriptDocument.find(Eq(SavedScriptDocument.user_id, user_id)).to_list()
        return [DomainSavedScript(**d.model_dump(exclude={"id", "revision_id"})) for d in docs]
