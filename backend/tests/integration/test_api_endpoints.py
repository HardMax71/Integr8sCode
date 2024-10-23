# tests/integration/test_api_endpoints.py
import pytest
from app.models.user import UserCreate
from httpx import AsyncClient


class TestAPIEndpoints:
    @pytest.fixture(autouse=True)
    async def setup(self, app, client: AsyncClient, db):
        self.app = app
        self.client = client
        self.db = db

        # Create a test user
        test_user = UserCreate(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        # Register the user and get token
        register_response = await self.client.post("/api/v1/register", json=test_user.dict())
        login_response = await self.client.post(
            "/api/v1/login",
            data={"username": test_user.username, "password": test_user.password}
        )
        self.token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @pytest.mark.asyncio
    async def test_health_check(self):
        response = await self.client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    @pytest.mark.asyncio
    async def test_execute_script_workflow(self):
        # Test script execution
        execution_request = {
            "script": "print('Hello, Integration Test!')",
            "python_version": "3.11"
        }
        execute_response = await self.client.post(
            "/api/v1/execute",
            json=execution_request,
            headers=self.headers
        )
        assert execute_response.status_code == 200
        execution_data = execute_response.json()
        assert "execution_id" in execution_data
        assert "status" in execution_data

        # Test getting execution result
        result_response = await self.client.get(
            f"/api/v1/result/{execution_data['execution_id']}",
            headers=self.headers
        )
        assert result_response.status_code == 200
        result_data = result_response.json()
        assert result_data["execution_id"] == execution_data["execution_id"]
        assert "output" in result_data
        assert "python_version" in result_data

    @pytest.mark.asyncio
    async def test_k8s_resource_limits(self):
        response = await self.client.get("/api/v1/k8s-limits", headers=self.headers)
        assert response.status_code == 200
        limits = response.json()
        assert all(key in limits for key in [
            "cpu_limit",
            "memory_limit",
            "cpu_request",
            "memory_request",
            "execution_timeout",
            "supported_python_versions"
        ])

    @pytest.mark.asyncio
    async def test_saved_scripts_crud(self):
        # Create script
        script_data = {
            "name": "Test Script",
            "script": "print('Hello from saved script')",
            "description": "Test description"
        }
        create_response = await self.client.post(
            "/api/v1/scripts",
            json=script_data,
            headers=self.headers
        )
        assert create_response.status_code == 200
        created_script = create_response.json()
        script_id = created_script["id"]

        # Get script
        get_response = await self.client.get(
            f"/api/v1/scripts/{script_id}",
            headers=self.headers
        )
        assert get_response.status_code == 200
        assert get_response.json()["name"] == script_data["name"]

        # Update script
        update_data = {
            "name": "Updated Script",
            "script": "print('Updated!')",
            "description": "Updated description"
        }
        update_response = await self.client.put(
            f"/api/v1/scripts/{script_id}",
            json=update_data,
            headers=self.headers
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == update_data["name"]

        # List scripts
        list_response = await self.client.get("/api/v1/scripts", headers=self.headers)
        assert list_response.status_code == 200
        scripts = list_response.json()
        assert len(scripts) > 0
        assert any(s["id"] == script_id for s in scripts)

        # Delete script
        delete_response = await self.client.delete(
            f"/api/v1/scripts/{script_id}",
            headers=self.headers
        )
        assert delete_response.status_code == 204

        # Verify deletion
        get_deleted = await self.client.get(
            f"/api/v1/scripts/{script_id}",
            headers=self.headers
        )
        assert get_deleted.status_code == 404

    @pytest.mark.asyncio
    async def test_error_handling(self):
        # Test invalid script execution
        invalid_request = {
            "script": "invalid python code!!!",
            "python_version": "3.11"
        }
        response = await self.client.post(
            "/api/v1/execute",
            json=invalid_request,
            headers=self.headers
        )
        assert response.status_code in [400, 500]

        # Test non-existent execution result
        response = await self.client.get(
            "/api/v1/result/nonexistent_id",
            headers=self.headers
        )
        assert response.status_code == 404

        # Test invalid script creation
        invalid_script = {
            "name": "",  # Invalid empty name
            "script": "print('test')"
        }
        response = await self.client.post(
            "/api/v1/scripts",
            json=invalid_script,
            headers=self.headers
        )
        assert response.status_code in [400, 422]
