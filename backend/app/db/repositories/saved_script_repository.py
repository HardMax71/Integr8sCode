from datetime import datetime, timezone

import structlog

from app.db.docs import SavedScriptDocument
from app.domain.saved_script import SavedScriptChanges


class SavedScriptRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger) -> None:
        self.logger = logger

    async def create_saved_script(self, script: SavedScriptDocument) -> SavedScriptDocument:
        await script.insert()
        return script

    async def get_saved_script(self, script_id: str, user_id: str) -> SavedScriptDocument | None:
        return await SavedScriptDocument.find_one(
            SavedScriptDocument.script_id == script_id,
            SavedScriptDocument.user_id == user_id,
        )

    async def update_saved_script(
        self, script: SavedScriptDocument, changes: SavedScriptChanges
    ) -> SavedScriptDocument:
        await script.set({**changes, "updated_at": datetime.now(timezone.utc)})
        return script

    async def delete_saved_script(self, script_id: str, user_id: str) -> bool:
        doc = await SavedScriptDocument.find_one(
            SavedScriptDocument.script_id == script_id,
            SavedScriptDocument.user_id == user_id,
        )
        if not doc:
            return False
        await doc.delete()
        return True

    async def list_saved_scripts(self, user_id: str) -> list[SavedScriptDocument]:
        return await SavedScriptDocument.find(SavedScriptDocument.user_id == user_id).to_list()
