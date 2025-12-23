from app.core.exceptions import ServiceError
from app.core.logging import logger
from app.db.repositories import SavedScriptRepository
from app.domain.saved_script import (
    DomainSavedScript,
    DomainSavedScriptCreate,
    DomainSavedScriptUpdate,
)


class SavedScriptService:
    def __init__(self, saved_script_repo: SavedScriptRepository):
        self.saved_script_repo = saved_script_repo

    async def create_saved_script(
        self, saved_script_create: DomainSavedScriptCreate, user_id: str
    ) -> DomainSavedScript:
        logger.info(
            "Creating new saved script",
            extra={
                "user_id": user_id,
                "script_name": saved_script_create.name,
                "script_length": len(saved_script_create.script),
            },
        )

        created_script = await self.saved_script_repo.create_saved_script(saved_script_create, user_id)

        logger.info(
            "Successfully created saved script",
            extra={
                "script_id": str(created_script.script_id),
                "user_id": user_id,
                "script_name": created_script.name,
            },
        )
        return created_script

    async def get_saved_script(self, script_id: str, user_id: str) -> DomainSavedScript:
        logger.info(
            "Retrieving saved script",
            extra={
                "user_id": user_id,
                "script_id": script_id,
            },
        )

        script = await self.saved_script_repo.get_saved_script(script_id, user_id)
        if not script:
            logger.warning(
                "Script not found for user",
                extra={"user_id": user_id, "script_id": script_id},
            )

            raise ServiceError("Script not found", status_code=404)

        logger.info(
            "Successfully retrieved script",
            extra={"script_id": script.script_id, "script_name": script.name},
        )
        return script

    async def update_saved_script(
        self, script_id: str, user_id: str, update_data: DomainSavedScriptUpdate
    ) -> DomainSavedScript:
        logger.info(
            "Updating saved script",
            extra={
                "user_id": user_id,
                "script_id": script_id,
                "script_name": update_data.name,
                "script_length": len(update_data.script) if update_data.script else None,
            },
        )

        await self.saved_script_repo.update_saved_script(script_id, user_id, update_data)
        updated_script = await self.saved_script_repo.get_saved_script(script_id, user_id)
        if not updated_script:
            raise ServiceError("Script not found", status_code=404)

        logger.info(
            "Successfully updated script",
            extra={"script_id": script_id, "script_name": updated_script.name},
        )
        return updated_script

    async def delete_saved_script(self, script_id: str, user_id: str) -> None:
        logger.info(
            "Deleting saved script",
            extra={
                "user_id": user_id,
                "script_id": script_id,
            },
        )

        await self.saved_script_repo.delete_saved_script(script_id, user_id)

        logger.info(
            "Successfully deleted script",
            extra={"script_id": script_id, "user_id": user_id},
        )

    async def list_saved_scripts(self, user_id: str) -> list[DomainSavedScript]:
        logger.info(
            "Listing saved scripts",
            extra={
                "user_id": user_id,
            },
        )

        scripts = await self.saved_script_repo.list_saved_scripts(user_id)

        logger.info(
            "Successfully retrieved saved scripts",
            extra={"user_id": user_id, "script_count": len(scripts)},
        )
        return scripts
