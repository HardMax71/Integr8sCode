import uuid

import pytest
from app.domain.saved_script import (
    DomainSavedScript,
    DomainSavedScriptCreate,
    DomainSavedScriptUpdate,
    SavedScriptNotFoundError,
)
from app.services.saved_script_service import SavedScriptService
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.mongodb]


def _unique_user_id() -> str:
    return f"script_user_{uuid.uuid4().hex[:8]}"


def _create_payload(
    name: str = "test_script",
    description: str | None = None,
    script: str = "print('hello world')",
) -> DomainSavedScriptCreate:
    return DomainSavedScriptCreate(
        name=name,
        description=description,
        script=script,
    )


class TestCreateSavedScript:
    """Tests for create_saved_script method."""

    @pytest.mark.asyncio
    async def test_create_saved_script_basic(self, scope: AsyncContainer) -> None:
        """Create a basic saved script."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        payload = _create_payload(name="Basic Script")
        created = await service.create_saved_script(payload, user_id)

        assert isinstance(created, DomainSavedScript)
        assert created.script_id is not None
        assert created.user_id == user_id
        assert created.name == "Basic Script"
        assert created.script == "print('hello world')"
        assert created.created_at is not None
        assert created.updated_at is not None

    @pytest.mark.asyncio
    async def test_create_saved_script_with_description(
        self, scope: AsyncContainer
    ) -> None:
        """Create saved script with description."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        payload = _create_payload(
            name="Described Script",
            description="This script does something useful",
        )
        created = await service.create_saved_script(payload, user_id)

        assert created.description == "This script does something useful"

    @pytest.mark.asyncio
    async def test_create_saved_script_multiline(self, scope: AsyncContainer) -> None:
        """Create saved script with multiline code."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        multiline_script = """def hello():
    print('Hello World')

if __name__ == '__main__':
    hello()
"""
        payload = _create_payload(name="Multiline", script=multiline_script)
        created = await service.create_saved_script(payload, user_id)

        assert created.script == multiline_script
        assert "def hello():" in created.script

    @pytest.mark.asyncio
    async def test_create_multiple_scripts_same_user(
        self, scope: AsyncContainer
    ) -> None:
        """User can create multiple scripts."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        scripts = []
        for i in range(3):
            payload = _create_payload(name=f"Script {i}", script=f"print({i})")
            created = await service.create_saved_script(payload, user_id)
            scripts.append(created)

        # All should have unique IDs
        script_ids = [s.script_id for s in scripts]
        assert len(set(script_ids)) == 3

    @pytest.mark.asyncio
    async def test_create_scripts_different_users_isolated(
        self, scope: AsyncContainer
    ) -> None:
        """Scripts from different users are isolated."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user1 = _unique_user_id()
        user2 = _unique_user_id()

        # Create scripts for each user
        payload1 = _create_payload(name="User1 Script")
        script1 = await service.create_saved_script(payload1, user1)

        payload2 = _create_payload(name="User2 Script")
        script2 = await service.create_saved_script(payload2, user2)

        # List each user's scripts
        user1_result = await service.list_saved_scripts(user1)
        user2_result = await service.list_saved_scripts(user2)

        # Should only see their own
        assert any(s.script_id == script1.script_id for s in user1_result.scripts)
        assert not any(s.script_id == script2.script_id for s in user1_result.scripts)

        assert any(s.script_id == script2.script_id for s in user2_result.scripts)
        assert not any(s.script_id == script1.script_id for s in user2_result.scripts)


class TestGetSavedScript:
    """Tests for get_saved_script method."""

    @pytest.mark.asyncio
    async def test_get_saved_script_success(self, scope: AsyncContainer) -> None:
        """Get saved script by ID."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        # Create
        payload = _create_payload(name="To Retrieve")
        created = await service.create_saved_script(payload, user_id)

        # Get
        retrieved = await service.get_saved_script(str(created.script_id), user_id)

        assert retrieved is not None
        assert retrieved.script_id == created.script_id
        assert retrieved.name == "To Retrieve"
        assert retrieved.user_id == user_id

    @pytest.mark.asyncio
    async def test_get_saved_script_not_found(self, scope: AsyncContainer) -> None:
        """Get nonexistent script raises error."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        with pytest.raises(SavedScriptNotFoundError):
            await service.get_saved_script("nonexistent-script-id", user_id)

    @pytest.mark.asyncio
    async def test_get_saved_script_wrong_user(self, scope: AsyncContainer) -> None:
        """Cannot get another user's script."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        owner = _unique_user_id()
        other_user = _unique_user_id()

        # Create as owner
        payload = _create_payload(name="Private Script")
        created = await service.create_saved_script(payload, owner)

        # Try to get as other user
        with pytest.raises(SavedScriptNotFoundError):
            await service.get_saved_script(str(created.script_id), other_user)


class TestUpdateSavedScript:
    """Tests for update_saved_script method."""

    @pytest.mark.asyncio
    async def test_update_saved_script_name(self, scope: AsyncContainer) -> None:
        """Update script name."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        # Create
        payload = _create_payload(name="Original Name")
        created = await service.create_saved_script(payload, user_id)

        # Update
        update = DomainSavedScriptUpdate(name="Updated Name", script=created.script)
        updated = await service.update_saved_script(
            str(created.script_id), user_id, update
        )

        assert updated is not None
        assert updated.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_update_saved_script_content(self, scope: AsyncContainer) -> None:
        """Update script content."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        # Create
        payload = _create_payload(script="print('original')")
        created = await service.create_saved_script(payload, user_id)

        # Update
        update = DomainSavedScriptUpdate(name=created.name, script="print('updated')")
        updated = await service.update_saved_script(
            str(created.script_id), user_id, update
        )

        assert updated.script == "print('updated')"

    @pytest.mark.asyncio
    async def test_update_saved_script_description(
        self, scope: AsyncContainer
    ) -> None:
        """Update script description."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        # Create without description
        payload = _create_payload(name="No Desc")
        created = await service.create_saved_script(payload, user_id)
        assert created.description is None

        # Update with description
        update = DomainSavedScriptUpdate(
            name=created.name,
            script=created.script,
            description="Now has description",
        )
        updated = await service.update_saved_script(
            str(created.script_id), user_id, update
        )

        assert updated.description == "Now has description"

    @pytest.mark.asyncio
    async def test_update_saved_script_not_found(self, scope: AsyncContainer) -> None:
        """Update nonexistent script raises error."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        update = DomainSavedScriptUpdate(name="New Name", script="print(1)")
        with pytest.raises(SavedScriptNotFoundError):
            await service.update_saved_script("nonexistent-id", user_id, update)

    @pytest.mark.asyncio
    async def test_update_saved_script_wrong_user(self, scope: AsyncContainer) -> None:
        """Cannot update another user's script."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        owner = _unique_user_id()
        other_user = _unique_user_id()

        # Create as owner
        payload = _create_payload(name="Owner Script")
        created = await service.create_saved_script(payload, owner)

        # Try to update as other user
        update = DomainSavedScriptUpdate(name="Hacked Name", script="print('hacked')")
        with pytest.raises(SavedScriptNotFoundError):
            await service.update_saved_script(str(created.script_id), other_user, update)


class TestDeleteSavedScript:
    """Tests for delete_saved_script method."""

    @pytest.mark.asyncio
    async def test_delete_saved_script_success(self, scope: AsyncContainer) -> None:
        """Delete saved script successfully."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        # Create
        payload = _create_payload(name="To Delete")
        created = await service.create_saved_script(payload, user_id)

        # Delete
        await service.delete_saved_script(str(created.script_id), user_id)

        # Verify it's gone
        with pytest.raises(SavedScriptNotFoundError):
            await service.get_saved_script(str(created.script_id), user_id)

    @pytest.mark.asyncio
    async def test_delete_saved_script_not_found(self, scope: AsyncContainer) -> None:
        """Delete nonexistent script raises error."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        with pytest.raises(SavedScriptNotFoundError):
            await service.delete_saved_script("nonexistent-id", user_id)

    @pytest.mark.asyncio
    async def test_delete_saved_script_wrong_user(self, scope: AsyncContainer) -> None:
        """Cannot delete another user's script."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        owner = _unique_user_id()
        other_user = _unique_user_id()

        # Create as owner
        payload = _create_payload(name="Owner Script")
        created = await service.create_saved_script(payload, owner)

        # Try to delete as other user
        with pytest.raises(SavedScriptNotFoundError):
            await service.delete_saved_script(str(created.script_id), other_user)

        # Should still exist for owner
        retrieved = await service.get_saved_script(str(created.script_id), owner)
        assert retrieved is not None


class TestListSavedScripts:
    """Tests for list_saved_scripts method."""

    @pytest.mark.asyncio
    async def test_list_saved_scripts_empty(self, scope: AsyncContainer) -> None:
        """List scripts for user with none returns empty list."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        result = await service.list_saved_scripts(user_id)

        assert isinstance(result.scripts, list)
        assert len(result.scripts) == 0

    @pytest.mark.asyncio
    async def test_list_saved_scripts_multiple(self, scope: AsyncContainer) -> None:
        """List multiple scripts for user."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        # Create multiple scripts
        script_names = ["Script A", "Script B", "Script C"]
        for name in script_names:
            payload = _create_payload(name=name)
            await service.create_saved_script(payload, user_id)

        # List
        result = await service.list_saved_scripts(user_id)

        assert len(result.scripts) >= 3
        names = [s.name for s in result.scripts]
        for expected_name in script_names:
            assert expected_name in names

    @pytest.mark.asyncio
    async def test_list_saved_scripts_user_isolated(
        self, scope: AsyncContainer
    ) -> None:
        """Each user only sees their own scripts."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user1 = _unique_user_id()
        user2 = _unique_user_id()

        # Create scripts for user1
        for i in range(2):
            payload = _create_payload(name=f"User1 Script {i}")
            await service.create_saved_script(payload, user1)

        # Create scripts for user2
        for i in range(3):
            payload = _create_payload(name=f"User2 Script {i}")
            await service.create_saved_script(payload, user2)

        # List user1's scripts
        user1_result = await service.list_saved_scripts(user1)
        assert len(user1_result.scripts) >= 2
        for script in user1_result.scripts:
            assert script.user_id == user1

        # List user2's scripts
        user2_result = await service.list_saved_scripts(user2)
        assert len(user2_result.scripts) >= 3
        for script in user2_result.scripts:
            assert script.user_id == user2


class TestSavedScriptIntegration:
    """Integration tests for saved script workflow."""

    @pytest.mark.asyncio
    async def test_full_crud_lifecycle(self, scope: AsyncContainer) -> None:
        """Test complete CRUD lifecycle."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        # Create
        payload = _create_payload(
            name="Lifecycle Script",
            description="Testing lifecycle",
            script="print('v1')",
        )
        created = await service.create_saved_script(payload, user_id)
        script_id = str(created.script_id)

        # Read
        retrieved = await service.get_saved_script(script_id, user_id)
        assert retrieved.name == "Lifecycle Script"

        # Update
        update = DomainSavedScriptUpdate(
            name="Updated Lifecycle Script",
            description="Updated description",
            script="print('v2')",
        )
        updated = await service.update_saved_script(script_id, user_id, update)
        assert updated.name == "Updated Lifecycle Script"
        assert updated.script == "print('v2')"

        # List - should include our script
        result = await service.list_saved_scripts(user_id)
        assert any(s.script_id == created.script_id for s in result.scripts)

        # Delete
        await service.delete_saved_script(script_id, user_id)

        # Verify deleted
        with pytest.raises(SavedScriptNotFoundError):
            await service.get_saved_script(script_id, user_id)

    @pytest.mark.asyncio
    async def test_script_with_special_characters(
        self, scope: AsyncContainer
    ) -> None:
        """Script content with special characters is preserved."""
        service: SavedScriptService = await scope.get(SavedScriptService)
        user_id = _unique_user_id()

        special_script = """
# Unicode: 你好世界 🌍
def greet(name: str) -> str:
    \"\"\"Greet someone with special chars: <>&'\\\"\"\"\"
    return f"Hello, {name}! 👋"

# Math symbols: ∑ ∫ √ ∞
print(greet("World"))
"""
        payload = _create_payload(name="Special Chars", script=special_script)
        created = await service.create_saved_script(payload, user_id)

        # Retrieve and verify
        retrieved = await service.get_saved_script(str(created.script_id), user_id)
        assert "你好世界" in retrieved.script
        assert "🌍" in retrieved.script
        assert "∑" in retrieved.script
