import structlog

from app.db import SavedScriptRepository
from app.db.docs import SavedScriptDocument
from app.domain.execution import RuntimeNotSupportedError
from app.domain.saved_script import SavedScriptChanges, SavedScriptNotFoundError
from app.runtime_registry import RUNTIME_REGISTRY


class SavedScriptService:
    def __init__(self, saved_script_repo: SavedScriptRepository, logger: structlog.stdlib.BoundLogger):
        self.saved_script_repo = saved_script_repo
        self.logger = logger

    # --8<-- [start:create_saved_script]
    async def create_saved_script(
        self,
        *,
        user_id: str,
        name: str,
        script: str,
        lang: str,
        lang_version: str,
        description: str | None,
    ) -> SavedScriptDocument:
        self.logger.info(
            "Creating new saved script",
            user_id=user_id,
            script_name=name,
            script_length=len(script),
        )
        self._ensure_runtime_offered(lang, lang_version)

        created_script = SavedScriptDocument(
            user_id=user_id,
            name=name,
            script=script,
            lang=lang,
            lang_version=lang_version,
            description=description,
        )
        await self.saved_script_repo.create_saved_script(created_script)

        self.logger.info(
            "Successfully created saved script",
            script_id=str(created_script.script_id),
            user_id=user_id,
            script_name=created_script.name,
        )
        return created_script

    # --8<-- [end:create_saved_script]

    async def get_saved_script(self, script_id: str, user_id: str) -> SavedScriptDocument:
        self.logger.info(
            "Retrieving saved script",
            user_id=user_id,
            script_id=script_id,
        )

        script = await self.saved_script_repo.get_saved_script(script_id, user_id)
        if not script:
            self.logger.warning(
                "Script not found for user",
                user_id=user_id,
                script_id=script_id,
            )
            raise SavedScriptNotFoundError(script_id)

        self.logger.info(
            "Successfully retrieved script",
            script_id=script.script_id,
            script_name=script.name,
        )
        return script

    async def update_saved_script(
        self, script_id: str, user_id: str, changes: SavedScriptChanges
    ) -> SavedScriptDocument:
        self.logger.info(
            "Updating saved script",
            user_id=user_id,
            script_id=script_id,
            script_name=changes.get("name"),
            script_length=len(changes["script"]) if "script" in changes else None,
        )
        stored = await self.saved_script_repo.get_saved_script(script_id, user_id)
        if not stored:
            raise SavedScriptNotFoundError(script_id)
        if "lang" in changes or "lang_version" in changes:
            self._ensure_runtime_offered(
                changes.get("lang", stored.lang), changes.get("lang_version", stored.lang_version)
            )

        updated_script = await self.saved_script_repo.update_saved_script(stored, changes)

        self.logger.info(
            "Successfully updated script",
            script_id=script_id,
            script_name=updated_script.name,
        )
        return updated_script

    async def delete_saved_script(self, script_id: str, user_id: str) -> None:
        self.logger.info(
            "Deleting saved script",
            user_id=user_id,
            script_id=script_id,
        )

        deleted = await self.saved_script_repo.delete_saved_script(script_id, user_id)
        if not deleted:
            self.logger.warning(
                "Script not found for user",
                user_id=user_id,
                script_id=script_id,
            )
            raise SavedScriptNotFoundError(script_id)

        self.logger.info(
            "Successfully deleted script",
            script_id=script_id,
            user_id=user_id,
        )

    async def list_saved_scripts(self, user_id: str) -> list[SavedScriptDocument]:
        self.logger.info(
            "Listing saved scripts",
            user_id=user_id,
        )

        scripts = await self.saved_script_repo.list_saved_scripts(user_id)

        self.logger.info(
            "Successfully retrieved saved scripts",
            user_id=user_id,
            script_count=len(scripts),
        )
        return scripts

    def _ensure_runtime_offered(self, lang: str, lang_version: str) -> None:
        if lang_version in RUNTIME_REGISTRY.get(lang, {}):
            return
        self.logger.warning("Saved script runtime not supported", lang=lang, lang_version=lang_version)
        raise RuntimeNotSupportedError(lang, lang_version)
