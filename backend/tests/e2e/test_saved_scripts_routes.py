
import pytest
from app.schemas_pydantic.saved_script import (
    SavedScriptCreateRequest,
    SavedScriptResponse,
    SavedScriptUpdate,
)
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e]


class TestCreateSavedScript:
    """Tests for POST /api/v1/scripts."""

    @pytest.mark.asyncio
    async def test_create_saved_script(
        self, test_user: AsyncClient, new_script_request: SavedScriptCreateRequest
    ) -> None:
        """Create a new saved script."""
        response = await test_user.post(
            "/api/v1/scripts", json=new_script_request.model_dump()
        )

        assert response.status_code == 200
        script = SavedScriptResponse.model_validate(response.json())

        assert script.script_id is not None
        assert script.name == new_script_request.name
        assert script.script == new_script_request.script
        assert script.lang == "python"
        assert script.created_at is not None
        assert script.updated_at is not None

    @pytest.mark.asyncio
    async def test_create_saved_script_minimal(
        self, test_user: AsyncClient, new_script_request: SavedScriptCreateRequest
    ) -> None:
        """Create script with minimal required fields."""
        response = await test_user.post(
            "/api/v1/scripts", json=new_script_request.model_dump()
        )

        assert response.status_code == 200
        script = SavedScriptResponse.model_validate(response.json())
        assert script.name == new_script_request.name

    @pytest.mark.asyncio
    async def test_create_saved_script_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.post(
            "/api/v1/scripts",
            json={
                "name": "Unauthorized Script",
                "script": "pass",
                "lang": "python",
            },
        )
        assert response.status_code == 401


class TestListSavedScripts:
    """Tests for GET /api/v1/scripts."""

    @pytest.mark.asyncio
    async def test_list_saved_scripts(
        self, test_user: AsyncClient, new_script_request: SavedScriptCreateRequest
    ) -> None:
        """List user's saved scripts."""
        await test_user.post("/api/v1/scripts", json=new_script_request.model_dump())

        response = await test_user.get("/api/v1/scripts")

        assert response.status_code == 200
        scripts = [
            SavedScriptResponse.model_validate(s) for s in response.json()
        ]

        assert len(scripts) >= 1
        assert any(new_script_request.name in s.name for s in scripts)

    @pytest.mark.asyncio
    async def test_list_saved_scripts_only_own(
        self, test_user: AsyncClient, another_user: AsyncClient,
        new_script_request: SavedScriptCreateRequest
    ) -> None:
        """User only sees their own scripts."""
        await test_user.post("/api/v1/scripts", json=new_script_request.model_dump())

        response = await another_user.get("/api/v1/scripts")
        assert response.status_code == 200
        scripts = response.json()

        # Should not contain test_user's script
        assert not any(new_script_request.name in s["name"] for s in scripts)


class TestGetSavedScript:
    """Tests for GET /api/v1/scripts/{script_id}."""

    @pytest.mark.asyncio
    async def test_get_saved_script(
        self, test_user: AsyncClient, new_script_request: SavedScriptCreateRequest
    ) -> None:
        """Get a specific saved script."""
        create_response = await test_user.post(
            "/api/v1/scripts", json=new_script_request.model_dump()
        )
        created = SavedScriptResponse.model_validate(create_response.json())

        response = await test_user.get(f"/api/v1/scripts/{created.script_id}")

        assert response.status_code == 200
        script = SavedScriptResponse.model_validate(response.json())
        assert script.script_id == created.script_id
        assert script.name == new_script_request.name
        assert script.script == new_script_request.script

    @pytest.mark.asyncio
    async def test_get_nonexistent_script(
        self, test_user: AsyncClient
    ) -> None:
        """Get nonexistent script returns 404."""
        response = await test_user.get("/api/v1/scripts/nonexistent-id")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_other_users_script_forbidden(
        self, test_user: AsyncClient, another_user: AsyncClient,
        new_script_request: SavedScriptCreateRequest
    ) -> None:
        """Cannot get another user's script."""
        create_response = await test_user.post(
            "/api/v1/scripts", json=new_script_request.model_dump()
        )
        script_id = create_response.json()["script_id"]

        response = await another_user.get(f"/api/v1/scripts/{script_id}")
        assert response.status_code == 404


class TestUpdateSavedScript:
    """Tests for PUT /api/v1/scripts/{script_id}."""

    @pytest.mark.asyncio
    async def test_update_saved_script(
        self, test_user: AsyncClient, new_script_request: SavedScriptCreateRequest
    ) -> None:
        """Update a saved script."""
        create_response = await test_user.post(
            "/api/v1/scripts", json=new_script_request.model_dump()
        )
        script = SavedScriptResponse.model_validate(create_response.json())

        update_request = SavedScriptUpdate(
            name="Updated Name",
            script="new content",
        )
        response = await test_user.put(
            f"/api/v1/scripts/{script.script_id}",
            json=update_request.model_dump(exclude_unset=True),
        )

        assert response.status_code == 200
        updated = SavedScriptResponse.model_validate(response.json())
        assert updated.name == "Updated Name"
        assert updated.script == "new content"
        assert updated.updated_at > script.updated_at

    @pytest.mark.asyncio
    async def test_update_other_users_script_forbidden(
        self, test_user: AsyncClient, another_user: AsyncClient,
        new_script_request: SavedScriptCreateRequest
    ) -> None:
        """Cannot update another user's script."""
        create_response = await test_user.post(
            "/api/v1/scripts", json=new_script_request.model_dump()
        )
        script_id = create_response.json()["script_id"]

        update_request = SavedScriptUpdate(name="Hacked")
        response = await another_user.put(
            f"/api/v1/scripts/{script_id}",
            json=update_request.model_dump(exclude_unset=True),
        )
        assert response.status_code == 404


class TestDeleteSavedScript:
    """Tests for DELETE /api/v1/scripts/{script_id}."""

    @pytest.mark.asyncio
    async def test_delete_saved_script(
        self, test_user: AsyncClient, new_script_request: SavedScriptCreateRequest
    ) -> None:
        """Delete a saved script returns 204."""
        create_response = await test_user.post(
            "/api/v1/scripts", json=new_script_request.model_dump()
        )
        script_id = create_response.json()["script_id"]

        response = await test_user.delete(f"/api/v1/scripts/{script_id}")
        assert response.status_code == 204

        get_response = await test_user.get(f"/api/v1/scripts/{script_id}")
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_other_users_script_forbidden(
        self, test_user: AsyncClient, another_user: AsyncClient,
        new_script_request: SavedScriptCreateRequest
    ) -> None:
        """Cannot delete another user's script."""
        create_response = await test_user.post(
            "/api/v1/scripts", json=new_script_request.model_dump()
        )
        assert create_response.status_code == 200
        script_id = create_response.json()["script_id"]

        response = await another_user.delete(f"/api/v1/scripts/{script_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_script(
        self, test_user: AsyncClient
    ) -> None:
        """Deleting nonexistent script returns 404."""
        response = await test_user.delete("/api/v1/scripts/nonexistent-id")
        assert response.status_code == 404
