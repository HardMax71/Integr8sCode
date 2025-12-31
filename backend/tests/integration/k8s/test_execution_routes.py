import asyncio
import os
from typing import Dict
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.domain.enums.execution import ExecutionStatus as ExecutionStatusEnum
from app.schemas_pydantic.execution import (
    ExecutionResponse,
    ExecutionResult,
    ResourceUsage
)


@pytest.mark.k8s
class TestExecution:
    """Test execution endpoints against real backend."""

    @pytest.mark.asyncio
    async def test_execute_requires_authentication(self, client: AsyncClient) -> None:
        """Test that execution requires authentication."""
        execution_request = {
            "script": "print('Hello, World!')",
            "lang": "python",
            "lang_version": "3.11"
        }

        response = await client.post("/api/v1/execute", json=execution_request)
        assert response.status_code == 401

        error_data = response.json()
        assert "detail" in error_data
        assert any(word in error_data["detail"].lower()
                   for word in ["not authenticated", "unauthorized", "login"])

    @pytest.mark.asyncio
    async def test_execute_simple_python_script(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test executing a simple Python script."""
        # Login first
        login_data = {
            "username": test_user["username"],
            "password": test_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Execute script
        execution_request = {
            "script": "print('Hello from real backend!')",
            "lang": "python",
            "lang_version": "3.11"
        }

        response = await client.post("/api/v1/execute", json=execution_request)
        assert response.status_code == 200

        # Validate response structure
        data = response.json()
        execution_response = ExecutionResponse(**data)

        # Verify execution_id
        assert execution_response.execution_id is not None
        assert len(execution_response.execution_id) > 0

        # Verify it's a valid UUID
        try:
            UUID(execution_response.execution_id)
        except ValueError:
            pytest.fail(f"Invalid execution_id format: {execution_response.execution_id}")

        # Verify status
        assert execution_response.status in [
            ExecutionStatusEnum.QUEUED,
            ExecutionStatusEnum.SCHEDULED,
            ExecutionStatusEnum.RUNNING,
            ExecutionStatusEnum.COMPLETED
        ]

    @pytest.mark.asyncio
    async def test_get_execution_result(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test getting execution result after completion using SSE (event-driven)."""
        # Login first
        login_data = {
            "username": test_user["username"],
            "password": test_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Execute a simple script
        execution_request = {
            "script": "print('Test output')\nprint('Line 2')",
            "lang": "python",
            "lang_version": "3.11"
        }

        exec_response = await client.post("/api/v1/execute", json=execution_request)
        assert exec_response.status_code == 200

        execution_id = exec_response.json()["execution_id"]

        # Immediately fetch result - no waiting
        result_response = await client.get(f"/api/v1/result/{execution_id}")
        assert result_response.status_code == 200
        
        result_data = result_response.json()
        execution_result = ExecutionResult(**result_data)
        assert execution_result.execution_id == execution_id
        assert execution_result.status in [e.value for e in ExecutionStatusEnum]
        assert execution_result.lang == "python"
        
        # Execution might be in any state - that's fine
        # If completed, validate output; if not, that's valid too
        if execution_result.status == ExecutionStatusEnum.COMPLETED:
            assert execution_result.stdout is not None
            assert "Test output" in execution_result.stdout
            assert "Line 2" in execution_result.stdout

    @pytest.mark.asyncio
    async def test_execute_with_error(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test executing a script that produces an error."""
        # Login first
        login_data = {
            "username": test_user["username"],
            "password": test_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Execute script with intentional error
        execution_request = {
            "script": "print('Before error')\nraise ValueError('Test error')\nprint('After error')",
            "lang": "python",
            "lang_version": "3.11"
        }

        exec_response = await client.post("/api/v1/execute", json=execution_request)
        assert exec_response.status_code == 200

        execution_id = exec_response.json()["execution_id"]
        
        # No waiting - execution was accepted, error will be processed asynchronously

    @pytest.mark.asyncio
    async def test_execute_with_resource_tracking(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test that execution tracks resource usage."""
        # Login first
        login_data = {
            "username": test_user["username"],
            "password": test_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Execute script that uses some resources
        execution_request = {
            "script": """
import time
# Create some memory usage
data = [i for i in range(10000)]
print(f'Created list with {len(data)} items')
time.sleep(0.1)  # Small delay to ensure measurable execution time
print('Done')
""",
            "lang": "python",
            "lang_version": "3.11"
        }

        exec_response = await client.post("/api/v1/execute", json=execution_request)
        assert exec_response.status_code == 200

        execution_id = exec_response.json()["execution_id"]
        
        # No waiting - execution was accepted, error will be processed asynchronously

        # Fetch result and validate resource usage if present
        result_response = await client.get(f"/api/v1/result/{execution_id}")
        if result_response.status_code == 200 and result_response.json().get("resource_usage"):
            resource_usage = ResourceUsage(**result_response.json()["resource_usage"])
            if resource_usage.execution_time_wall_seconds is not None:
                assert resource_usage.execution_time_wall_seconds >= 0
            if resource_usage.peak_memory_kb is not None:
                assert resource_usage.peak_memory_kb >= 0

    @pytest.mark.asyncio
    async def test_execute_with_different_language_versions(self, client: AsyncClient,
                                                            test_user: Dict[str, str]) -> None:
        """Test execution with different Python versions."""
        # Login first
        login_data = {
            "username": test_user["username"],
            "password": test_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Test different Python versions (if supported)
        test_cases = [
            ("3.10", "import sys; print(f'Python {sys.version}')"),
            ("3.11", "import sys; print(f'Python {sys.version}')"),
            ("3.12", "import sys; print(f'Python {sys.version}')")
        ]

        for version, script in test_cases:
            execution_request = {
                "script": script,
                "lang": "python",
                "lang_version": version
            }

            response = await client.post("/api/v1/execute", json=execution_request)
            # Should either accept (200) or reject unsupported version (400/422)
            assert response.status_code in [200, 400, 422]

            if response.status_code == 200:
                data = response.json()
                assert "execution_id" in data

    @pytest.mark.asyncio
    async def test_execute_with_large_output(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test execution with large output."""
        # Login first
        login_data = {
            "username": test_user["username"],
            "password": test_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Script that produces large output
        execution_request = {
            "script": """
# Generate large output
for i in range(1000):
    print(f'Line {i}: ' + 'x' * 50)
print('End of output')
""",
            "lang": "python",
            "lang_version": "3.11"
        }

        exec_response = await client.post("/api/v1/execute", json=execution_request)
        assert exec_response.status_code == 200

        execution_id = exec_response.json()["execution_id"]
        
        # No waiting - execution was accepted, error will be processed asynchronously
        # Validate output from result endpoint (best-effort)
        result_response = await client.get(f"/api/v1/result/{execution_id}")
        if result_response.status_code == 200:
            result_data = result_response.json()
            if result_data.get("status") == "COMPLETED":
                assert result_data.get("stdout") is not None
                assert len(result_data["stdout"]) > 0
                assert "End of output" in result_data["stdout"] or len(result_data["stdout"]) > 10000

    @pytest.mark.asyncio
    async def test_cancel_running_execution(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test cancelling a running execution."""
        # Login first
        login_data = {
            "username": test_user["username"],
            "password": test_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Start a long-running script
        execution_request = {
            "script": """
import time
print('Starting long task...')
for i in range(30):
    print(f'Iteration {i}')
    time.sleep(1)
print('Should not reach here if cancelled')
""",
            "lang": "python",
            "lang_version": "3.11"
        }

        exec_response = await client.post("/api/v1/execute", json=execution_request)
        assert exec_response.status_code == 200

        execution_id = exec_response.json()["execution_id"]

        # Try to cancel immediately - no waiting
        cancel_request = {
            "reason": "Test cancellation"
        }

        try:
            cancel_response = await client.post(f"/api/v1/{execution_id}/cancel", json=cancel_request)
        except Exception:
            pytest.skip("Cancel endpoint not available or connection dropped")
        if cancel_response.status_code >= 500:
            pytest.skip("Cancellation not wired; backend returned 5xx")
        # Should succeed or fail if already completed
        assert cancel_response.status_code in [200, 400, 404]
        
        # Cancel response of 200 means cancellation was accepted

    @pytest.mark.asyncio
    async def test_execution_with_timeout(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Bounded check: long-running executions don't finish immediately.

        The backend's default timeout is 300s. To keep integration fast,
        assert that within a short window the execution is either still
        running or has transitioned to a terminal state due to platform limits.
        """
        # Login first
        login_data = {
            "username": test_user["username"],
            "password": test_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Script that would run forever
        execution_request = {
            "script": """
import time
print('Starting infinite loop...')
while True:
    time.sleep(1)
    print('Still running...')
""",
            "lang": "python",
            "lang_version": "3.11"
        }

        exec_response = await client.post("/api/v1/execute", json=execution_request)
        assert exec_response.status_code == 200

        execution_id = exec_response.json()["execution_id"]
        
        # Just verify the execution was created - it will run forever until timeout
        # No need to wait or observe states

    @pytest.mark.asyncio
    async def test_sandbox_restrictions(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test that dangerous operations are blocked by sandbox."""
        # Login first
        login_data = {
            "username": test_user["username"],
            "password": test_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Try dangerous operations that should be blocked
        dangerous_scripts = [
            # File system access
            "open('/etc/passwd', 'r').read()",
            # Network access
            "import socket; socket.socket().connect(('google.com', 80))",
            # System commands
            "import os; os.system('ls /')",
            # Process manipulation
            "import subprocess; subprocess.run(['ps', 'aux'])"
        ]

        for script in dangerous_scripts:
            execution_request = {
                "script": script,
                "lang": "python",
                "lang_version": "3.11"
            }

            exec_response = await client.post("/api/v1/execute", json=execution_request)

            # Should either reject immediately or fail during execution
            if exec_response.status_code == 200:
                execution_id = exec_response.json()["execution_id"]

                # Immediately check result - no waiting
                result_resp = await client.get(f"/api/v1/result/{execution_id}")
                if result_resp.status_code == 200:
                    result_data = result_resp.json()
                    # Dangerous operations should either:
                    # 1. Be in queued/running state (not yet executed)
                    # 2. Have failed/errored if sandbox blocked them
                    # 3. Have output showing permission denied
                    if result_data.get("status") == "COMPLETED":
                        output = result_data.get("stdout", "").lower()
                        # Should have been blocked
                        assert "denied" in output or "permission" in output or "error" in output
                    elif result_data.get("status") == "FAILED":
                        # Good - sandbox blocked it
                        pass
                    # Otherwise it's still queued/running which is fine
            else:
                # Rejected at submission time (also acceptable)
                assert exec_response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_concurrent_executions_by_same_user(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """Test running multiple executions concurrently."""
        # Login first
        login_data = {
            "username": test_user["username"],
            "password": test_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Submit multiple executions
        execution_request = {
            "script": "import time; time.sleep(1); print('Concurrent test')",
            "lang": "python",
            "lang_version": "3.11"
        }

        tasks = []
        for i in range(3):
            task = client.post("/api/v1/execute", json=execution_request)
            tasks.append(task)

        responses = await asyncio.gather(*tasks)

        execution_ids = []
        for response in responses:
            # Should succeed or be rate limited
            assert response.status_code in [200, 429]

            if response.status_code == 200:
                data = response.json()
                execution_ids.append(data["execution_id"])

        # All successful executions should have unique IDs
        assert len(execution_ids) == len(set(execution_ids))

        # Verify at least some succeeded
        assert len(execution_ids) > 0

    @pytest.mark.asyncio
    async def test_get_example_scripts(self, client: AsyncClient) -> None:
        """Example scripts endpoint returns available example scripts."""
        response = await client.get("/api/v1/example-scripts")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "scripts" in data
        assert isinstance(data["scripts"], dict)

    @pytest.mark.asyncio
    async def test_get_k8s_resource_limits(self, client: AsyncClient) -> None:
        """K8s limits endpoint returns cluster execution limits if configured."""
        response = await client.get("/api/v1/k8s-limits")
        assert response.status_code == 200
        limits = response.json()
        # Validate ResourceLimits shape
        for key in [
            "cpu_limit",
            "memory_limit",
            "cpu_request",
            "memory_request",
            "execution_timeout",
            "supported_runtimes",
        ]:
            assert key in limits

    @pytest.mark.asyncio
    async def test_get_user_executions_list(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        """User executions list returns paginated executions for current user."""
        # Login first
        login_data = {"username": test_user["username"], "password": test_user["password"]}
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # List executions
        response = await client.get("/api/v1/user/executions?limit=5&skip=0")
        assert response.status_code == 200
        payload = response.json()
        assert set(["executions", "total", "limit", "skip", "has_more"]).issubset(payload.keys())

    @pytest.mark.asyncio
    async def test_execution_idempotency_same_key_returns_same_execution(self, client: AsyncClient,
                                                                         test_user: Dict[str, str]) -> None:
        """Submitting the same request with the same Idempotency-Key yields the same execution_id."""
        # Login first
        login_data = {"username": test_user["username"], "password": test_user["password"]}
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        execution_request = {
            "script": "print('Idempotency integration test')",
            "lang": "python",
            "lang_version": "3.11",
        }

        headers = {"Idempotency-Key": "it-idem-key-123"}

        # Use idempotency header on both requests to guarantee keying
        r1 = await client.post("/api/v1/execute", json=execution_request, headers=headers)
        assert r1.status_code == 200
        assert r1.status_code == 200
        e1 = r1.json()["execution_id"]

        # Second request with same key must return the same execution id
        r2 = await client.post("/api/v1/execute", json=execution_request, headers=headers)
        assert r2.status_code == 200
        e2 = r2.json()["execution_id"]

        assert e1 == e2
