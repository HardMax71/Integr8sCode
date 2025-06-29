import asyncio
import time

import pytest
from app.schemas.user import UserCreate
from httpx import AsyncClient, HTTPStatusError
from motor.motor_asyncio import AsyncIOMotorDatabase

# Define polling parameters
POLL_INTERVAL = 2  # seconds
EXECUTION_TIMEOUT = 120  # seconds


@pytest.mark.integration
class TestExecutionAPI:

    @pytest.fixture(autouse=True)
    async def setup(self, client: AsyncClient, db: AsyncIOMotorDatabase) -> None:
        """Setup user and authentication for execution tests."""
        self.client = client
        self.db = db
        self.test_username = f"testuser_exec_{int(time.time() * 1000)}"
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
            pytest.fail(f"Exec setup: Registration failed: {reg_response.status_code} {reg_response.text}")
        # Login
        login_response = await self.client.post(
            "/api/v1/login",
            data={"username": self.test_username, "password": self.test_password},
        )
        if login_response.status_code != 200:
            pytest.fail(f"Exec setup: Login failed: {login_response.status_code} {login_response.text}")
        login_data = login_response.json()
        assert "access_token" in login_data
        self.token = login_data["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @pytest.mark.asyncio
    async def test_execute_script_success_workflow(self) -> None:
        """Test successful script execution and result retrieval."""
        script_content = "import time\nimport sys\nprint('Hello from integration test')\nsys.stdout.flush()\ntime.sleep(1)\nprint('Execution complete')"
        execution_request = {
            "script": script_content,
            "lang": "python",
            "lang_version": "3.11",
        }

        # 1. Execute Script
        execute_response = await self.client.post("/api/v1/execute", json=execution_request, headers=self.headers)
        assert execute_response.status_code == 200, f"Execute failed: {execute_response.text}"
        execution_data = execute_response.json()
        assert "execution_id" in execution_data
        assert execution_data["status"] in ["queued", "running"]
        execution_id = execution_data["execution_id"]

        # 2. Poll for Result
        start_time = time.time()
        final_status = None
        result_data = None
        while time.time() - start_time < EXECUTION_TIMEOUT:
            try:
                result_response = await self.client.get(f"/api/v1/result/{execution_id}", headers=self.headers)
                result_response.raise_for_status()  # Raise HTTP errors
                result_data = result_response.json()
                final_status = result_data.get("status")
                if final_status not in ["queued", "running"]: break
            except HTTPStatusError as e:
                pytest.fail(f"Polling failed with HTTP error: {e.response.status_code} {e.response.text}")
            except Exception as e:
                pytest.fail(f"Polling failed with unexpected error: {e}")
            await asyncio.sleep(POLL_INTERVAL)
        else:
            pytest.fail(
                f"Execution did not complete within timeout ({EXECUTION_TIMEOUT}s). Last status: {final_status}")

        # 3. Assert Final Result
        assert final_status == "completed", f"Expected status 'completed', got '{final_status}'"
        assert result_data is not None
        assert "Hello from integration test" in result_data.get("output", "")
        assert "Execution complete" in result_data.get("output", "")
        assert result_data.get("errors") is None or result_data.get("errors") == ""
        assert result_data.get("lang_version") == execution_request["lang_version"]

    @pytest.mark.asyncio
    async def test_execute_script_with_error(self) -> None:
        """Test script execution that results in a Python error."""
        script_content = "import sys\nprint('Start')\nsys.stdout.flush()\nresult = 1 / 0\nprint('End')"
        execution_request = {"script": script_content}

        # 1. Execute Script
        execute_response = await self.client.post("/api/v1/execute", json=execution_request, headers=self.headers)
        assert execute_response.status_code == 200
        execution_id = execute_response.json()["execution_id"]

        # 2. Poll for Result
        start_time = time.time()
        final_status = None
        result_data = None
        while time.time() - start_time < EXECUTION_TIMEOUT:
            result_response = await self.client.get(f"/api/v1/result/{execution_id}", headers=self.headers)
            if result_response.status_code == 200:
                result_data = result_response.json()
                final_status = result_data.get("status")
                if final_status not in ["queued", "running"]: break
            elif result_response.status_code != 404:  # Allow 404 briefly
                pytest.fail(f"Polling failed with HTTP error: {result_response.status_code} {result_response.text}")
            await asyncio.sleep(POLL_INTERVAL)
        else:
            pytest.fail(f"Error script execution did not finish within timeout. Last status: {final_status}")

        # 3. Assert Final Result indicates failure
        assert final_status == "error", f"Expected status 'error', got '{final_status}'"
        assert result_data is not None
        assert "Start" in result_data.get("errors", "")
        assert "End" not in result_data.get("output", "")
        assert result_data.get("errors") is not None
        assert "Script failed with exit code 1" in result_data["errors"]

    @pytest.mark.asyncio
    async def test_get_nonexistent_result(self) -> None:
        """Test getting a result for an ID that doesn't exist."""
        response = await self.client.get("/api/v1/result/nonexistent_id_12345", headers=self.headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_k8s_resource_limits(self) -> None:
        """Verify the K8s resource limits endpoint."""
        response = await self.client.get("/api/v1/k8s-limits", headers=self.headers)
        assert response.status_code == 200
        limits = response.json()
        expected_keys = ["cpu_limit", "memory_limit", "cpu_request", "memory_request", "execution_timeout",
                         "supported_runtimes"]
        assert all(key in limits for key in expected_keys)
        assert isinstance(limits["supported_runtimes"], dict)

    @pytest.mark.asyncio
    async def test_execute_endpoint_without_auth(self) -> None:
        """Test accessing execute endpoint without authentication (should succeed)."""
        execution_request = {"script": "print('no auth test should pass')"}
        response = await self.client.post("/api/v1/execute", json=execution_request)  # No headers
        # Expect 200 OK because the endpoint is public
        assert response.status_code == 200
        assert "execution_id" in response.json()
        assert "status" in response.json()

    @pytest.mark.asyncio
    async def test_result_endpoint_without_auth(self) -> None:
        non_existent_id = "nonexistent-public-id-999"
        response = await self.client.get(f"/api/v1/result/{non_existent_id}")  # No headers
        # Expect 404 Not Found because the ID doesn't exist, *not* 401 because the endpoint is public
        assert response.status_code == 404
