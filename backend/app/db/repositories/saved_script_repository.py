import dataclasses

from app.db.docs import SavedScriptDocument
from app.domain.saved_script import DomainSavedScript, DomainSavedScriptCreate, DomainSavedScriptUpdate

_script_fields = set(DomainSavedScript.__dataclass_fields__)


class SavedScriptRepository:
    async def create_saved_script(self, create_data: DomainSavedScriptCreate, user_id: str) -> DomainSavedScript:
        doc = SavedScriptDocument(**dataclasses.asdict(create_data), user_id=user_id)
        await doc.insert()
        return DomainSavedScript(**doc.model_dump(include=_script_fields))

    async def get_saved_script(self, script_id: str, user_id: str) -> DomainSavedScript | None:
        doc = await SavedScriptDocument.find_one(
            SavedScriptDocument.script_id == script_id,
            SavedScriptDocument.user_id == user_id,
        )
        return DomainSavedScript(**doc.model_dump(include=_script_fields)) if doc else None

    async def update_saved_script(
        self,
        script_id: str,
        user_id: str,
        update_data: DomainSavedScriptUpdate,
    ) -> DomainSavedScript | None:
        doc = await SavedScriptDocument.find_one(
            SavedScriptDocument.script_id == script_id,
            SavedScriptDocument.user_id == user_id,
        )
        if not doc:
            return None

        update_dict = {k: v for k, v in dataclasses.asdict(update_data).items() if v is not None}
        await doc.set(update_dict)
        return DomainSavedScript(**doc.model_dump(include=_script_fields))

    async def delete_saved_script(self, script_id: str, user_id: str) -> bool:
        doc = await SavedScriptDocument.find_one(
            SavedScriptDocument.script_id == script_id,
            SavedScriptDocument.user_id == user_id,
        )
        if not doc:
            return False
        await doc.delete()
        return True

    async def list_saved_scripts(self, user_id: str) -> list[DomainSavedScript]:
        docs = await SavedScriptDocument.find(SavedScriptDocument.user_id == user_id).to_list()
        return [DomainSavedScript(**d.model_dump(include=_script_fields)) for d in docs]
