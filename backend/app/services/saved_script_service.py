import structlog

from app.db import SavedScriptRepository
from app.domain.execution import RuntimeNotSupportedError
from app.domain.saved_script import (
    DomainSavedScript,
    DomainSavedScriptCreate,
    DomainSavedScriptListResult,
    DomainSavedScriptUpdate,
    SavedScriptNotFoundError,
)
from app.runtime_registry import RUNTIME_REGISTRY


class SavedScriptService:
    def __init__(self, saved_script_repo: SavedScriptRepository, logger: structlog.stdlib.BoundLogger):
        self.saved_script_repo = saved_script_repo
        self.logger = logger

    # --8<-- [start:create_saved_script]
    async def create_saved_script(
        self, saved_script_create: DomainSavedScriptCreate, user_id: str
    ) -> DomainSavedScript:
        self.logger.info(
            "Creating new saved script",
            user_id=user_id,
            script_name=saved_script_create.name,
            script_length=len(saved_script_create.script),
        )
        self._ensure_runtime_offered(saved_script_create.lang, saved_script_create.lang_version)

        created_script = await self.saved_script_repo.create_saved_script(saved_script_create, user_id)

        self.logger.info(
            "Successfully created saved script",
            script_id=str(created_script.script_id),
            user_id=user_id,
            script_name=created_script.name,
        )
        return created_script

    # --8<-- [end:create_saved_script]

    async def get_saved_script(self, script_id: str, user_id: str) -> DomainSavedScript:
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
        self, script_id: str, user_id: str, update_data: DomainSavedScriptUpdate
    ) -> DomainSavedScript:
        self.logger.info(
            "Updating saved script",
            user_id=user_id,
            script_id=script_id,
            script_name=update_data.name,
            script_length=len(update_data.script) if update_data.script else None,
        )
        await self._ensure_updated_runtime_offered(script_id, user_id, update_data)

        await self.saved_script_repo.update_saved_script(script_id, user_id, update_data)
        updated_script = await self.saved_script_repo.get_saved_script(script_id, user_id)
        if not updated_script:
            raise SavedScriptNotFoundError(script_id)

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

    async def list_saved_scripts(self, user_id: str) -> DomainSavedScriptListResult:
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
        return DomainSavedScriptListResult(scripts=scripts)

    async def _ensure_updated_runtime_offered(
        self, script_id: str, user_id: str, update_data: DomainSavedScriptUpdate
    ) -> None:
        lang, lang_version = update_data.lang, update_data.lang_version
        if lang is None and lang_version is None:
            return
        if lang is None or lang_version is None:
            stored = await self.saved_script_repo.get_saved_script(script_id, user_id)
            if not stored:
                raise SavedScriptNotFoundError(script_id)
            lang = stored.lang if lang is None else lang
            lang_version = stored.lang_version if lang_version is None else lang_version
        self._ensure_runtime_offered(lang, lang_version)

    def _ensure_runtime_offered(self, lang: str, lang_version: str) -> None:
        if lang_version in RUNTIME_REGISTRY.get(lang, {}):
            return
        self.logger.warning("Saved script runtime not supported", lang=lang, lang_version=lang_version)
        raise RuntimeNotSupportedError(lang, lang_version)
