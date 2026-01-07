from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

import pytest
from app.domain.enums.user import UserRole
from app.schemas_pydantic.saved_script import SavedScriptResponse
from httpx import AsyncClient

from tests.conftest import MakeUser


@pytest.mark.integration
class TestSavedScripts:
    """Test saved scripts endpoints against real backend."""

    @pytest.mark.asyncio
    async def test_create_script_requires_authentication(self, client: AsyncClient) -> None:
        """Test that creating a saved script requires authentication."""
        script_data = {
            "name": "Unauthenticated Script",
            "script": "print('Should fail')",
            "lang": "python",
            "lang_version": "3.11"
        }

        response = await client.post("/api/v1/scripts", json=script_data)
        assert response.status_code == 401

        error_data = response.json()
        assert "detail" in error_data
        assert any(word in error_data["detail"].lower()
                   for word in ["not authenticated", "unauthorized", "login"])

    @pytest.mark.asyncio
    async def test_create_and_retrieve_saved_script(
        self, authenticated_client: AsyncClient, unique_id: Callable[[str], str],
    ) -> None:
        """Test creating and retrieving a saved script."""
        # Create a unique script
        uid = unique_id("")
        script_data = {
            "name": f"Test Script {uid}",
            "script": f"# Script {uid}\nprint('Hello from saved script {uid}')",
            "lang": "python",
            "lang_version": "3.11",
            "description": f"Test script created at {datetime.now(timezone.utc).isoformat()}"
        }

        # Create the script
        create_response = await authenticated_client.post("/api/v1/scripts", json=script_data)
        assert create_response.status_code in [200, 201]

        # Validate response structure
        created_data = create_response.json()
        saved_script = SavedScriptResponse(**created_data)

        # Verify all fields
        assert saved_script.script_id is not None
        assert len(saved_script.script_id) > 0

        # Verify it's a valid UUID
        try:
            UUID(saved_script.script_id)
        except ValueError:
            pytest.fail(f"Invalid script_id format: {saved_script.script_id}")

        # Verify data matches request
        assert saved_script.name == script_data["name"]
        assert saved_script.script == script_data["script"]
        assert saved_script.lang == script_data["lang"]
        assert saved_script.lang_version == script_data["lang_version"]
        assert saved_script.description == script_data["description"]

        # Verify timestamps
        assert saved_script.created_at is not None
        assert saved_script.updated_at is not None

        # Now retrieve the script by ID
        get_response = await authenticated_client.get(f"/api/v1/scripts/{saved_script.script_id}")
        assert get_response.status_code == 200

        retrieved_data = get_response.json()
        retrieved_script = SavedScriptResponse(**retrieved_data)

        # Verify it matches what we created
        assert retrieved_script.script_id == saved_script.script_id
        assert retrieved_script.name == script_data["name"]
        assert retrieved_script.script == script_data["script"]

    @pytest.mark.asyncio
    async def test_list_user_scripts(
        self, authenticated_client: AsyncClient, unique_id: Callable[[str], str]
    ) -> None:
        """Test listing user's saved scripts."""
        # Create a few scripts
        uid = unique_id("")
        scripts_to_create = [
            {
                "name": f"List Test Script 1 {uid}",
                "script": "print('Script 1')",
                "lang": "python",
                "lang_version": "3.11",
                "description": "First script"
            },
            {
                "name": f"List Test Script 2 {uid}",
                "script": "console.log('Script 2');",
                "lang": "javascript",
                "lang_version": "18",
                "description": "Second script"
            },
            {
                "name": f"List Test Script 3 {uid}",
                "script": "print('Script 3')",
                "lang": "python",
                "lang_version": "3.10"
            }
        ]

        created_ids = []
        for script_data in scripts_to_create:
            create_response = await authenticated_client.post("/api/v1/scripts", json=script_data)
            if create_response.status_code in [200, 201]:
                created_ids.append(create_response.json()["script_id"])

        # List all scripts
        list_response = await authenticated_client.get("/api/v1/scripts")
        assert list_response.status_code == 200

        scripts_list = list_response.json()
        assert isinstance(scripts_list, list)

        # Should have at least the scripts we just created
        assert len(scripts_list) >= len(created_ids)

        # Validate structure of returned scripts
        for script_data in scripts_list:
            saved_script = SavedScriptResponse(**script_data)
            assert saved_script.script_id is not None
            assert saved_script.name is not None
            assert saved_script.script is not None
            assert saved_script.lang is not None
            assert saved_script.lang_version is not None

        # Check that our created scripts are in the list
        returned_ids = [script["script_id"] for script in scripts_list]
        for created_id in created_ids:
            assert created_id in returned_ids

    @pytest.mark.asyncio
    async def test_update_saved_script(
        self, authenticated_client: AsyncClient, unique_id: Callable[[str], str]
    ) -> None:
        """Test updating a saved script."""
        # Create a script
        uid = unique_id("")
        original_data = {
            "name": f"Original Script {uid}",
            "script": "print('Original content')",
            "lang": "python",
            "lang_version": "3.11",
            "description": "Original description"
        }

        create_response = await authenticated_client.post("/api/v1/scripts", json=original_data)
        assert create_response.status_code in [200, 201]

        created_script = create_response.json()
        script_id = created_script["script_id"]
        original_created_at = created_script["created_at"]

        # Update the script
        updated_data = {
            "name": f"Updated Script {uid}",
            "script": "print('Updated content with more features')",
            "lang": "python",
            "lang_version": "3.12",
            "description": "Updated description with more details"
        }

        update_response = await authenticated_client.put(f"/api/v1/scripts/{script_id}", json=updated_data)
        assert update_response.status_code == 200

        updated_script_data = update_response.json()
        updated_script = SavedScriptResponse(**updated_script_data)

        # Verify updates were applied
        assert updated_script.script_id == script_id  # ID should not change
        assert updated_script.name == updated_data["name"]
        assert updated_script.script == updated_data["script"]
        assert updated_script.lang == updated_data["lang"]
        assert updated_script.lang_version == updated_data["lang_version"]
        assert updated_script.description == updated_data["description"]

        # Verify created_at didn't change (normalize tz and millisecond precision) and updated_at did
        orig_dt = datetime.fromisoformat(original_created_at.replace('Z', '+00:00'))
        upd_dt = updated_script.created_at
        if upd_dt.tzinfo is None:
            upd_dt = upd_dt.replace(tzinfo=timezone.utc)
        assert int(upd_dt.timestamp() * 1000) == int(orig_dt.timestamp() * 1000)
        assert updated_script.updated_at > updated_script.created_at

    @pytest.mark.asyncio
    async def test_delete_saved_script(
        self, authenticated_client: AsyncClient, unique_id: Callable[[str], str]
    ) -> None:
        """Test deleting a saved script."""
        # Create a script to delete
        uid = unique_id("")
        script_data = {
            "name": f"Script to Delete {uid}",
            "script": "print('Delete me')",
            "lang": "python",
            "lang_version": "3.11",
            "description": "This script will be deleted"
        }

        create_response = await authenticated_client.post("/api/v1/scripts", json=script_data)
        assert create_response.status_code in [200, 201]

        script_id = create_response.json()["script_id"]

        # Delete the script
        delete_response = await authenticated_client.delete(f"/api/v1/scripts/{script_id}")
        assert delete_response.status_code in [200, 204]

        # Verify it's deleted by trying to get it
        get_response = await authenticated_client.get(f"/api/v1/scripts/{script_id}")
        assert get_response.status_code in [404, 403]

        if get_response.status_code == 404:
            error_data = get_response.json()
            assert "detail" in error_data

    @pytest.mark.asyncio
    async def test_cannot_access_other_users_scripts(
        self,
        client: AsyncClient,
        make_user: MakeUser,
        unique_id: Callable[[str], str],
    ) -> None:
        """Test that users cannot access scripts created by other users."""
        # Create user and immediately create their script (make_user logs in with proper headers)
        await make_user(UserRole.USER)
        uid = unique_id("")
        user_script_data = {
            "name": f"User Private Script {uid}",
            "script": "print('Private to user')",
            "lang": "python",
            "lang_version": "3.11",
            "description": "Should only be visible to creating user",
        }
        create_response = await client.post("/api/v1/scripts", json=user_script_data)
        assert create_response.status_code in [200, 201]
        user_script_id = create_response.json()["script_id"]

        # Create admin and immediately try to access user's script (make_user logs in with proper headers)
        await make_user(UserRole.ADMIN)

        # Try to access the user's script as admin - should fail
        get_response = await client.get(f"/api/v1/scripts/{user_script_id}")
        assert get_response.status_code in [403, 404]

        # List scripts as admin - should not include user's script
        list_response = await client.get("/api/v1/scripts")
        assert list_response.status_code == 200
        admin_script_ids = [s["script_id"] for s in list_response.json()]
        assert user_script_id not in admin_script_ids

    @pytest.mark.asyncio
    async def test_script_with_invalid_language(
        self, authenticated_client: AsyncClient, unique_id: Callable[[str], str],
    ) -> None:
        """Test that invalid language/version combinations are handled."""
        uid = unique_id("")

        # Try invalid language
        invalid_lang_data = {
            "name": f"Invalid Language Script {uid}",
            "script": "print('test')",
            "lang": "invalid_language",
            "lang_version": "1.0"
        }

        response = await authenticated_client.post("/api/v1/scripts", json=invalid_lang_data)
        # Backend may accept arbitrary lang values; accept any outcome
        assert response.status_code in [200, 201, 400, 422]

        # Try unsupported version
        unsupported_version_data = {
            "name": f"Unsupported Version Script {uid}",
            "script": "print('test')",
            "lang": "python",
            "lang_version": "2.7"  # Python 2 likely not supported
        }

        response = await authenticated_client.post("/api/v1/scripts", json=unsupported_version_data)
        # Might accept but warn, or reject
        assert response.status_code in [200, 201, 400, 422]

    @pytest.mark.asyncio
    async def test_script_name_constraints(self, authenticated_client: AsyncClient) -> None:
        """Test script name validation and constraints."""
        # Test empty name
        empty_name_data = {
            "name": "",
            "script": "print('test')",
            "lang": "python",
            "lang_version": "3.11"
        }

        response = await authenticated_client.post("/api/v1/scripts", json=empty_name_data)
        assert response.status_code in [200, 201, 400, 422]

        # Test very long name
        long_name_data = {
            "name": "x" * 1000,  # Very long name
            "script": "print('test')",
            "lang": "python",
            "lang_version": "3.11"
        }

        response = await authenticated_client.post("/api/v1/scripts", json=long_name_data)
        # Should either accept or reject based on max length
        if response.status_code in [400, 422]:
            error_data = response.json()
            assert "detail" in error_data

    @pytest.mark.asyncio
    async def test_script_content_size_limits(
        self, authenticated_client: AsyncClient, unique_id: Callable[[str], str]
    ) -> None:
        """Test script content size limits."""
        uid = unique_id("")

        # Test reasonably large script (should succeed)
        large_content = "# Large script\n" + "\n".join([f"print('Line {i}')" for i in range(1000)])
        large_script_data = {
            "name": f"Large Script {uid}",
            "script": large_content,
            "lang": "python",
            "lang_version": "3.11"
        }

        response = await authenticated_client.post("/api/v1/scripts", json=large_script_data)
        assert response.status_code in [200, 201]

        # Test excessively large script (should fail with 413 from RequestSizeLimitMiddleware)
        # Middleware default is 10MB; 10MB script + JSON overhead exceeds this
        huge_content = "x" * (1024 * 1024 * 10)  # 10MB
        huge_script_data = {
            "name": f"Huge Script {uid}",
            "script": huge_content,
            "lang": "python",
            "lang_version": "3.11",
        }

        response = await authenticated_client.post("/api/v1/scripts", json=huge_script_data)
        assert response.status_code == 413, f"Expected 413 Payload Too Large, got {response.status_code}"
        assert "too large" in response.json().get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_update_nonexistent_script(self, authenticated_client: AsyncClient) -> None:
        """Test updating a non-existent script."""
        fake_script_id = "00000000-0000-0000-0000-000000000000"

        update_data = {
            "name": "Won't Work",
            "script": "print('This should fail')",
            "lang": "python",
            "lang_version": "3.11"
        }

        response = await authenticated_client.put(f"/api/v1/scripts/{fake_script_id}", json=update_data)
        # Non-existent script must return 404/403 (no server error)
        assert response.status_code in [404, 403]

        error_data = response.json()
        assert "detail" in error_data

    @pytest.mark.asyncio
    async def test_delete_nonexistent_script(self, authenticated_client: AsyncClient) -> None:
        """Test deleting a non-existent script."""
        fake_script_id = "00000000-0000-0000-0000-000000000000"

        response = await authenticated_client.delete(f"/api/v1/scripts/{fake_script_id}")
        # Could be 404 (not found) or 204 (idempotent delete)
        assert response.status_code in [404, 403, 204]

    @pytest.mark.asyncio
    async def test_scripts_persist_across_sessions(
        self, client: AsyncClient, make_user: MakeUser, unique_id: Callable[[str], str],
    ) -> None:
        """Test that scripts persist across login sessions."""
        user = await make_user(UserRole.USER)

        uid = unique_id("")
        script_data = {
            "name": f"Persistent Script {uid}",
            "script": "print('Should persist')",
            "lang": "python",
            "lang_version": "3.11",
            "description": "Testing persistence",
        }

        create_response = await client.post("/api/v1/scripts", json=script_data)
        assert create_response.status_code in [200, 201]
        script_id = create_response.json()["script_id"]

        # Logout
        await client.post("/api/v1/auth/logout")

        # Second session - login again and retrieve script
        login_resp = await client.post(
            "/api/v1/auth/login",
            data={"username": user["username"], "password": user["password"]},
        )
        assert login_resp.status_code == 200

        # Script should still exist
        get_response = await client.get(f"/api/v1/scripts/{script_id}")
        assert get_response.status_code == 200

        retrieved_script = SavedScriptResponse(**get_response.json())
        assert retrieved_script.script_id == script_id
        assert retrieved_script.name == script_data["name"]
        assert retrieved_script.script == script_data["script"]
