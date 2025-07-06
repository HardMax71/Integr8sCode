import time

import pytest
from app.schemas.user import UserCreate
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase


@pytest.mark.integration
class TestSavedScriptsAPI:

    @pytest.fixture(autouse=True)
    async def setup(self, client: AsyncClient, db: AsyncIOMotorDatabase) -> None:
        """Setup user and authentication for saved script tests."""
        self.client = client
        self.db = db
        self.test_username = f"testuser_scripts_{int(time.time() * 1000)}"
        self.test_email = f"{self.test_username}@example.com"
        self.test_password = "testpass123"

        test_user = UserCreate(
            username=self.test_username,
            email=self.test_email,
            password=self.test_password
        )
        # Register
        reg_response = await self.client.post("/api/v1/register", json=test_user.model_dump())
        if reg_response.status_code not in [200, 400]:
            pytest.fail(f"Scripts setup: Registration failed: {reg_response.status_code} {reg_response.text}")
        # Login
        login_response = await self.client.post(
            "/api/v1/login",
            data={"username": self.test_username, "password": self.test_password},
        )
        if login_response.status_code != 200:
            pytest.fail(f"Scripts setup: Login failed: {login_response.status_code} {login_response.text}")
        login_data = login_response.json()
        assert "csrf_token" in login_data
        assert "message" in login_data
        self.csrf_token = login_data["csrf_token"]
        self.headers = {"X-CSRF-Token": self.csrf_token}

    @pytest.mark.asyncio
    async def test_saved_scripts_crud_workflow(self) -> None:
        """Test full CRUD operations for saved scripts via API."""
        # 1. Create Script
        script_data = {
            "name": "Integration Test Script CRUD",
            "script": "print('CRUD script content')",
            "description": "Desc for CRUD integration test",
        }
        create_response = await self.client.post("/api/v1/scripts", json=script_data, headers=self.headers)
        assert create_response.status_code == 200  # Or 201 if API returns that
        created_script = create_response.json()
        script_id = created_script["id"]
        assert created_script["name"] == script_data["name"]

        # 2. Get Script (Verify Creation)
        get_response = await self.client.get(f"/api/v1/scripts/{script_id}", headers=self.headers)
        assert get_response.status_code == 200
        fetched_script = get_response.json()
        assert fetched_script["id"] == script_id
        assert fetched_script["name"] == script_data["name"]

        # 3. Update Script
        update_payload = {
            "name": "Updated Integration Script CRUD",
            "script": "print('Updated CRUD content')",
            "description": "Updated CRUD desc",
        }
        update_response = await self.client.put(f"/api/v1/scripts/{script_id}", json=update_payload,
                                                headers=self.headers)
        assert update_response.status_code == 200, f"Update failed: {update_response.text}"
        updated_script_resp = update_response.json()
        assert updated_script_resp["name"] == update_payload["name"]
        assert updated_script_resp["script"] == update_payload["script"]
        assert updated_script_resp["updated_at"] > fetched_script["updated_at"]

        # 4. List Scripts (Verify Update)
        list_response = await self.client.get("/api/v1/scripts", headers=self.headers)
        assert list_response.status_code == 200
        scripts = list_response.json()
        found = any(s["id"] == script_id and s["name"] == update_payload["name"] for s in scripts)
        assert found, "Updated script not found in list"

        # 5. Delete Script
        delete_response = await self.client.delete(f"/api/v1/scripts/{script_id}", headers=self.headers)
        assert delete_response.status_code == 204  # Check your API's delete status code

        # 6. Get Script (Verify Deletion)
        get_deleted_response = await self.client.get(f"/api/v1/scripts/{script_id}", headers=self.headers)
        assert get_deleted_response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_script_invalid_data(self) -> None:
        """Test creating a script with invalid data (missing name)."""
        invalid_script = {"script": "print('test')"}
        response = await self.client.post("/api/v1/scripts", json=invalid_script, headers=self.headers)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_nonexistent_script(self) -> None:
        """Test getting a script that doesn't exist."""
        response = await self.client.get("/api/v1/scripts/nonexistent_script_id_6789", headers=self.headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_nonexistent_script(self) -> None:
        """Test updating a script that doesn't exist."""
        update_payload = {"name": "Nonexistent", "script": "print('no')"}
        response = await self.client.put("/api/v1/scripts/nonexistent_script_id_9876", json=update_payload,
                                         headers=self.headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_script(self) -> None:
        """Test deleting a script that doesn't exist."""
        response = await self.client.delete("/api/v1/scripts/nonexistent_script_id_1122", headers=self.headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_scripts_empty(self) -> None:
        """Test listing scripts when none have been created for the user."""
        # User is created in setup, but might not have scripts yet
        # Ensure no scripts exist (safer: use a different user, requires another setup)
        # For simplicity, assume setup user has no scripts unless created in a test
        list_response = await self.client.get("/api/v1/scripts", headers=self.headers)
        assert list_response.status_code == 200
        scripts = list_response.json()
        assert isinstance(scripts, list)

    @pytest.mark.asyncio
    async def test_scripts_endpoints_without_auth(self) -> None:
        """Test accessing scripts endpoints without authentication."""
        script_data = {"name": "No Auth", "script": "print('no')"}
        # Use empty cookies to simulate no authentication
        response_post = await self.client.post("/api/v1/scripts", json=script_data, cookies={})
        response_get_list = await self.client.get("/api/v1/scripts", cookies={})
        response_get_one = await self.client.get("/api/v1/scripts/some-id", cookies={})
        response_put = await self.client.put("/api/v1/scripts/some-id", json=script_data, cookies={})
        response_delete = await self.client.delete("/api/v1/scripts/some-id", cookies={})

        assert response_post.status_code == 401
        assert response_get_list.status_code == 401
        assert response_get_one.status_code == 401
        assert response_put.status_code == 401
        assert response_delete.status_code == 401
