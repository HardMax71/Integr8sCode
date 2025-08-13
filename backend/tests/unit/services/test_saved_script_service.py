import asyncio
from collections.abc import AsyncGenerator

import pytest
from app.core.security import security_service
from app.db.repositories.saved_script_repository import get_saved_script_repository
from app.schemas_pydantic.saved_script import SavedScriptCreate
from app.services.saved_script_service import SavedScriptService


class TestSavedScriptService:
    @pytest.fixture(autouse=True)
    async def setup(self, db: AsyncGenerator) -> None:
        self.db = db
        self.saved_script_repo = get_saved_script_repository(db)
        self.service = SavedScriptService(self.saved_script_repo)
        self.security_service = security_service

    def test_saved_script_service_initialization(self) -> None:
        assert self.service is not None
        assert hasattr(self.service, 'saved_script_repo')

    @pytest.mark.asyncio
    async def test_create_saved_script_success(self) -> None:
        # Create unique script name
        script_name = f"test_script_{int(asyncio.get_event_loop().time())}"

        script_data = SavedScriptCreate(
            name=script_name,
            script="print('Hello from saved script')",
            lang="python",
            lang_version="3.11",
            description="Test script for unit testing"
        )

        result = await self.service.create_saved_script(script_data, "test_user")

        assert result is not None
        assert result.name == script_name
        assert result.script == script_data.script
        assert result.lang == "python"
        assert result.lang_version == "3.11"
        assert result.user_id == "test_user"
        assert result.created_at is not None

    @pytest.mark.asyncio
    async def test_get_saved_script_by_id(self) -> None:
        # Create a script first
        script_name = f"get_test_{int(asyncio.get_event_loop().time())}"
        script_data = SavedScriptCreate(
            name=script_name,
            script="print('Get test')",
            lang="python",
            lang_version="3.11"
        )

        created_script = await self.service.create_saved_script(script_data, "test_user")

        # Get the script by ID
        retrieved_script = await self.service.get_saved_script(created_script.id, "test_user")

        assert retrieved_script is not None
        assert retrieved_script.id == created_script.id
        assert retrieved_script.name == script_name
        assert retrieved_script.script == script_data.script

    @pytest.mark.asyncio
    async def test_get_saved_script_nonexistent(self) -> None:
        result = await self.service.get_saved_script("nonexistent_id_12345", "test_user")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_saved_scripts(self) -> None:
        username = f"list_user_{int(asyncio.get_event_loop().time())}"

        # Create multiple scripts for the user
        scripts = []
        for i in range(3):
            script_data = SavedScriptCreate(
                name=f"user_script_{i}_{username}",
                script=f"print('User script {i}')",
                lang="python",
                lang_version="3.11"
            )

            created_script = await self.service.create_saved_script(script_data, username)
            scripts.append(created_script)

        # Get all scripts for the user
        user_scripts = await self.service.list_saved_scripts(username)

        assert len(user_scripts) >= 3

        # Check that our created scripts are in the list
        script_names = [script.name for script in user_scripts]
        for script in scripts:
            assert script.name in script_names

    @pytest.mark.asyncio
    async def test_update_saved_script(self) -> None:
        # Create a script first
        script_name = f"update_test_{int(asyncio.get_event_loop().time())}"
        script_data = SavedScriptCreate(
            name=script_name,
            script="print('Original script')",
            lang="python",
            lang_version="3.11"
        )

        created_script = await self.service.create_saved_script(script_data, "test_user")

        # Update the script
        update_data = SavedScriptCreate(
            name=f"{script_name}_updated",
            script="print('Updated script')",
            lang="python",
            lang_version="3.11",
            description="Updated description"
        )

        await self.service.update_saved_script(created_script.id, "test_user", update_data)

        # Get the updated script to verify changes
        updated_script = await self.service.get_saved_script(created_script.id, "test_user")

        assert updated_script is not None
        assert updated_script.id == created_script.id
        assert updated_script.name == f"{script_name}_updated"
        assert updated_script.script == "print('Updated script')"
        assert updated_script.description == "Updated description"
        assert updated_script.updated_at > created_script.updated_at

    @pytest.mark.asyncio
    async def test_delete_saved_script(self) -> None:
        # Create a script first
        script_name = f"delete_test_{int(asyncio.get_event_loop().time())}"
        script_data = SavedScriptCreate(
            name=script_name,
            script="print('To be deleted')",
            lang="python",
            lang_version="3.11"
        )

        created_script = await self.service.create_saved_script(script_data, "test_user")

        # Delete the script
        await self.service.delete_saved_script(created_script.id, "test_user")

        # Verify the script is deleted
        deleted_script = await self.service.get_saved_script(created_script.id, "test_user")
        assert deleted_script is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_script(self) -> None:
        # This should not raise an exception for nonexistent script
        await self.service.delete_saved_script("nonexistent_id_12345", "test_user")

    @pytest.mark.asyncio
    async def test_script_ownership_validation(self) -> None:
        user1 = f"owner1_{int(asyncio.get_event_loop().time())}"
        user2 = f"owner2_{int(asyncio.get_event_loop().time())}"

        # Create scripts for different users
        script1_data = SavedScriptCreate(
            name=f"user1_script_{user1}",
            script="print('User 1 script')",
            lang="python",
            lang_version="3.11"
        )

        script2_data = SavedScriptCreate(
            name=f"user2_script_{user2}",
            script="print('User 2 script')",
            lang="python",
            lang_version="3.11"
        )

        script1 = await self.service.create_saved_script(script1_data, user1)
        script2 = await self.service.create_saved_script(script2_data, user2)

        # Get scripts for each user
        user1_scripts = await self.service.list_saved_scripts(user1)
        user2_scripts = await self.service.list_saved_scripts(user2)

        # User1 should have script1 but not script2
        user1_script_ids = [script.id for script in user1_scripts]
        assert script1.id in user1_script_ids
        assert script2.id not in user1_script_ids

        # User2 should have script2 but not script1
        user2_script_ids = [script.id for script in user2_scripts]
        assert script2.id in user2_script_ids
        assert script1.id not in user2_script_ids

    @pytest.mark.asyncio
    async def test_script_with_different_languages(self) -> None:
        timestamp = int(asyncio.get_event_loop().time())
        test_cases = [
            ("python", "3.11", "print('Python script')"),
            ("node", "18", "console.log('JavaScript script');"),
            ("bash", "5", "echo 'Bash script'"),
        ]

        created_scripts = []

        for lang, version, script_code in test_cases:
            script_data = SavedScriptCreate(
                name=f"multi_lang_{lang}_{timestamp}",
                script=script_code,
                lang=lang,
                lang_version=version
            )

            created_script = await self.service.create_saved_script(script_data, "multi_lang_user")
            created_scripts.append(created_script)

            assert created_script.lang == lang
            assert created_script.lang_version == version
            assert created_script.script == script_code

        # Should have created all scripts
        assert len(created_scripts) == len(test_cases)

    @pytest.mark.asyncio
    async def test_script_validation(self) -> None:

        # Test with valid data (empty name is allowed)
        valid_script = SavedScriptCreate(
            name="",  # Empty name is allowed
            script="print('test')",
            lang="python",
            lang_version="3.11"
        )
        result = await self.service.create_saved_script(valid_script, "test_user")
        assert result is not None
        assert result.name == ""

    @pytest.mark.asyncio
    async def test_concurrent_script_operations(self) -> None:
        username = f"concurrent_user_{int(asyncio.get_event_loop().time())}"

        # Create multiple scripts concurrently
        tasks = []
        for i in range(3):
            script_data = SavedScriptCreate(
                name=f"concurrent_script_{i}_{username}",
                script=f"print('Concurrent script {i}')",
                lang="python",
                lang_version="3.11"
            )
            task = self.service.create_saved_script(script_data, username)
            tasks.append(task)

        results = await asyncio.gather(*tasks)

        # All should succeed
        assert len(results) == 3
        for result in results:
            assert result is not None
            assert result.user_id == username

        # All should have unique IDs
        script_ids = [result.id for result in results]
        assert len(set(script_ids)) == 3

    def test_saved_script_service_can_be_instantiated(self, db: AsyncGenerator) -> None:
        from app.db.repositories.saved_script_repository import get_saved_script_repository

        saved_script_repo = get_saved_script_repository(db)
        service = SavedScriptService(saved_script_repo)

        assert service is not None
        assert isinstance(service, SavedScriptService)
        assert service.saved_script_repo is saved_script_repo
