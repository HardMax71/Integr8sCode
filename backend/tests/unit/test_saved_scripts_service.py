import asyncio

import pytest
from datetime import datetime
from app.services.saved_script_service import SavedScriptService
from app.db.repositories.saved_script_repository import SavedScriptRepository
from app.models.saved_script import SavedScriptCreate, SavedScriptUpdate


class TestSavedScriptService:
    @pytest.fixture(autouse=True)
    async def setup(self, db):
        self.saved_script_repo = SavedScriptRepository(db)
        self.saved_script_service = SavedScriptService(self.saved_script_repo)
        self.test_user_id = "test-user-123"

    @pytest.mark.asyncio
    async def test_create_saved_script(self):
        script_create = SavedScriptCreate(
            name="Test Python Script",
            script="print('Hello, World!')",
            description="A simple test script"
        )

        result = await self.saved_script_service.create_saved_script(
            script_create,
            self.test_user_id
        )

        assert result.name == script_create.name
        assert result.script == script_create.script
        assert result.description == script_create.description
        assert result.user_id == self.test_user_id
        assert isinstance(result.created_at, datetime)
        assert isinstance(result.updated_at, datetime)
        assert result.id is not None

    @pytest.mark.asyncio
    async def test_get_saved_script(self):
        # First create a script
        script_create = SavedScriptCreate(
            name="Test Get Script",
            script="print('Get Test')",
            description="Testing get functionality"
        )
        created_script = await self.saved_script_service.create_saved_script(
            script_create,
            self.test_user_id
        )

        # Then retrieve it
        retrieved_script = await self.saved_script_service.get_saved_script(
            created_script.id,
            self.test_user_id
        )

        assert retrieved_script.id == created_script.id
        assert retrieved_script.name == script_create.name
        assert retrieved_script.script == script_create.script

    @pytest.mark.asyncio
    async def test_update_saved_script(self):
        # First create a script
        script_create = SavedScriptCreate(
            name="Original Name",
            script="print('Original')",
            description="Original description"
        )
        created_script = await self.saved_script_service.create_saved_script(
            script_create,
            self.test_user_id
        )

        await asyncio.sleep(0.1)

        # Update the script
        update_data = SavedScriptUpdate(
            name="Updated Name",
            script="print('Updated')",
            description="Updated description"
        )

        await self.saved_script_service.update_saved_script(
            created_script.id,
            self.test_user_id,
            update_data
        )

        # Retrieve and verify the update
        updated_script = await self.saved_script_service.get_saved_script(
            created_script.id,
            self.test_user_id
        )

        assert updated_script.name == "Updated Name"
        assert updated_script.script == "print('Updated')"
        assert updated_script.description == "Updated description"
        assert updated_script.updated_at > created_script.updated_at

    @pytest.mark.asyncio
    async def test_delete_saved_script(self):
        # First create a script
        script_create = SavedScriptCreate(
            name="To Be Deleted",
            script="print('Delete Me')",
            description="Testing delete functionality"
        )
        created_script = await self.saved_script_service.create_saved_script(
            script_create,
            self.test_user_id
        )

        # Delete the script
        await self.saved_script_service.delete_saved_script(
            created_script.id,
            self.test_user_id
        )

        # Verify it's deleted
        retrieved_script = await self.saved_script_service.get_saved_script(
            created_script.id,
            self.test_user_id
        )
        assert retrieved_script is None

    @pytest.mark.asyncio
    async def test_list_saved_scripts(self):
        # Clear any existing scripts first
        await self.saved_script_repo.db.saved_scripts.delete_many(
            {"user_id": self.test_user_id})  # Changed from collection to db.saved_scripts

        # Create multiple scripts
        test_scripts = [
            SavedScriptCreate(
                name=f"Test Script {i}",
                script=f"print('Hello {i}')",
                description=f"Test Description {i}"
            ) for i in range(3)
        ]

        for script in test_scripts:
            await self.saved_script_service.create_saved_script(
                script,
                self.test_user_id
            )

        # List scripts
        saved_scripts = await self.saved_script_service.list_saved_scripts(
            self.test_user_id
        )

        assert len(saved_scripts) == 3
        assert all(s.user_id == self.test_user_id for s in saved_scripts)

        # Sort scripts by name to ensure consistent order
        saved_scripts.sort(key=lambda x: x.name)

        for i, script in enumerate(saved_scripts):
            assert script.id is not None
            assert isinstance(script.created_at, datetime)
            assert isinstance(script.updated_at, datetime)
            assert script.name == f"Test Script {i}"
            assert script.script == f"print('Hello {i}')"
            assert script.description == f"Test Description {i}"

    @pytest.mark.asyncio
    async def test_list_saved_scripts_empty(self):
        # Use a different user ID to ensure no scripts exist
        empty_user_id = "empty-user-123"

        saved_scripts = await self.saved_script_service.list_saved_scripts(
            empty_user_id
        )

        assert len(saved_scripts) == 0
        assert isinstance(saved_scripts, list)

    @pytest.mark.asyncio
    async def test_partial_update_saved_script(self):
        # First create a script
        script_create = SavedScriptCreate(
            name="Original Name",
            script="print('Original')",
            description="Original description"
        )
        created_script = await self.saved_script_service.create_saved_script(
            script_create,
            self.test_user_id
        )

        # Perform partial update (only name)
        partial_update = SavedScriptUpdate(
            name="Updated Name Only"
        )

        await self.saved_script_service.update_saved_script(
            created_script.id,
            self.test_user_id,
            partial_update
        )

        # Verify partial update
        updated_script = await self.saved_script_service.get_saved_script(
            created_script.id,
            self.test_user_id
        )

        assert updated_script.name == "Updated Name Only"
        assert updated_script.script == "print('Original')"  # Should remain unchanged
        assert updated_script.description == "Original description"  # Should remain unchanged
        assert updated_script.updated_at > created_script.updated_at