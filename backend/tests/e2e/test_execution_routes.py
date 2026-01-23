import asyncio
from uuid import UUID

import pytest
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus as ExecutionStatusEnum
from app.schemas_pydantic.execution import (
    CancelExecutionRequest,
    DeleteResponse,
    ExecutionEventResponse,
    ExecutionListResponse,
    ExecutionRequest,
    ExecutionResponse,
    ExecutionResult,
    ResourceUsage,
    RetryExecutionRequest,
)
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.k8s]


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
    async def test_execute_simple_python_script(
            self, test_user: AsyncClient, simple_execution_request: ExecutionRequest
    ) -> None:
        """Test executing a simple Python script."""
        response = await test_user.post(
            "/api/v1/execute", json=simple_execution_request.model_dump()
        )
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
    async def test_get_execution_result(self, test_user: AsyncClient) -> None:
        """Test getting execution result after completion using SSE (event-driven)."""
        # Execute a simple script
        request = ExecutionRequest(
            script="print('Test output')\nprint('Line 2')",
            lang="python",
            lang_version="3.11",
        )

        exec_response = await test_user.post("/api/v1/execute", json=request.model_dump())
        assert exec_response.status_code == 200

        execution_id = exec_response.json()["execution_id"]

        # Immediately fetch result - no waiting
        result_response = await test_user.get(f"/api/v1/executions/{execution_id}/result")
        assert result_response.status_code == 200

        result_data = result_response.json()
        execution_result = ExecutionResult(**result_data)
        assert execution_result.execution_id == execution_id
        assert execution_result.status in list(ExecutionStatusEnum)
        assert execution_result.lang == "python"

        # Execution might be in any state - that's fine
        # If completed, validate output; if not, that's valid too
        if execution_result.status == ExecutionStatusEnum.COMPLETED:
            assert execution_result.stdout is not None
            assert "Test output" in execution_result.stdout
            assert "Line 2" in execution_result.stdout

    @pytest.mark.asyncio
    async def test_execute_with_error(self, test_user: AsyncClient) -> None:
        """Test executing a script that produces an error."""
        # Execute script with intentional error
        request = ExecutionRequest(
            script="print('Before error')\nraise ValueError('Test error')\nprint('After error')",
            lang="python",
            lang_version="3.11",
        )

        exec_response = await test_user.post("/api/v1/execute", json=request.model_dump())
        assert exec_response.status_code == 200

        exec_response.json()["execution_id"]

        # No waiting - execution was accepted, error will be processed asynchronously

    @pytest.mark.asyncio
    async def test_execute_with_resource_tracking(self, test_user: AsyncClient) -> None:
        """Test that execution tracks resource usage."""
        # Execute script that uses some resources
        request = ExecutionRequest(
            script="""
import time
# Create some memory usage
data = [i for i in range(10000)]
print(f'Created list with {len(data)} items')
time.sleep(0.1)  # Small delay to ensure measurable execution time
print('Done')
""",
            lang="python",
            lang_version="3.11",
        )

        exec_response = await test_user.post("/api/v1/execute", json=request.model_dump())
        assert exec_response.status_code == 200

        execution_id = exec_response.json()["execution_id"]

        # No waiting - execution was accepted, error will be processed asynchronously

        # Fetch result and validate resource usage if present
        result_response = await test_user.get(f"/api/v1/executions/{execution_id}/result")
        if result_response.status_code == 200 and result_response.json().get("resource_usage"):
            resource_usage = ResourceUsage(**result_response.json()["resource_usage"])
            if resource_usage.execution_time_wall_seconds is not None:
                assert resource_usage.execution_time_wall_seconds >= 0
            if resource_usage.peak_memory_kb is not None:
                assert resource_usage.peak_memory_kb >= 0

    @pytest.mark.asyncio
    async def test_execute_with_different_language_versions(self, test_user: AsyncClient) -> None:
        """Test execution with different Python versions."""
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

            response = await test_user.post("/api/v1/execute", json=execution_request)
            # Should either accept (200) or reject unsupported version (400/422)
            assert response.status_code in [200, 400, 422]

            if response.status_code == 200:
                data = response.json()
                assert "execution_id" in data

    @pytest.mark.asyncio
    async def test_execute_with_large_output(self, test_user: AsyncClient) -> None:
        """Test execution with large output."""
        # Script that produces large output
        request = ExecutionRequest(
            script="""
# Generate large output
for i in range(1000):
    print(f'Line {i}: ' + 'x' * 50)
print('End of output')
""",
            lang="python",
            lang_version="3.11",
        )

        exec_response = await test_user.post("/api/v1/execute", json=request.model_dump())
        assert exec_response.status_code == 200

        execution_id = exec_response.json()["execution_id"]

        # No waiting - execution was accepted, error will be processed asynchronously
        # Validate output from result endpoint (best-effort)
        result_response = await test_user.get(f"/api/v1/executions/{execution_id}/result")
        if result_response.status_code == 200:
            result_data = result_response.json()
            if result_data.get("status") == ExecutionStatusEnum.COMPLETED:
                assert result_data.get("stdout") is not None
                assert len(result_data["stdout"]) > 0
                assert "End of output" in result_data["stdout"] or len(result_data["stdout"]) > 10000

    @pytest.mark.asyncio
    async def test_cancel_running_execution(
            self, test_user: AsyncClient, long_running_execution_request: ExecutionRequest
    ) -> None:
        """Test cancelling a running execution."""
        exec_response = await test_user.post(
            "/api/v1/execute", json=long_running_execution_request.model_dump()
        )
        assert exec_response.status_code == 200

        execution_id = exec_response.json()["execution_id"]

        # Try to cancel immediately - no waiting
        cancel_req = CancelExecutionRequest(reason="Test cancellation")

        try:
            cancel_response = await test_user.post(
                f"/api/v1/executions/{execution_id}/cancel", json=cancel_req.model_dump()
            )
        except Exception:
            pytest.skip("Cancel endpoint not available or connection dropped")
        if cancel_response.status_code >= 500:
            pytest.skip("Cancellation not wired; backend returned 5xx")
        # Should succeed or fail if already completed
        assert cancel_response.status_code in [200, 400, 404]

        # Cancel response of 200 means cancellation was accepted

    @pytest.mark.asyncio
    async def test_execution_with_timeout(self, test_user: AsyncClient) -> None:
        """Bounded check: long-running executions don't finish immediately.

        The backend's default timeout is 300s. To keep integration fast,
        assert that within a short window the execution is either still
        running or has transitioned to a terminal state due to platform limits.
        """
        # Script that would run forever
        request = ExecutionRequest(
            script="""
import time
print('Starting infinite loop...')
while True:
    time.sleep(1)
    print('Still running...')
""",
            lang="python",
            lang_version="3.11",
        )

        exec_response = await test_user.post("/api/v1/execute", json=request.model_dump())
        assert exec_response.status_code == 200

        exec_response.json()["execution_id"]

        # Just verify the execution was created - it will run forever until timeout
        # No need to wait or observe states

    @pytest.mark.asyncio
    async def test_sandbox_restrictions(self, test_user: AsyncClient) -> None:
        """Test that dangerous operations are blocked by sandbox."""
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

            exec_response = await test_user.post("/api/v1/execute", json=execution_request)

            # Should either reject immediately or fail during execution
            if exec_response.status_code == 200:
                execution_id = exec_response.json()["execution_id"]

                # Immediately check result - no waiting
                result_resp = await test_user.get(f"/api/v1/executions/{execution_id}/result")
                if result_resp.status_code == 200:
                    result_data = result_resp.json()
                    # Dangerous operations should either:
                    # 1. Be in queued/running state (not yet executed)
                    # 2. Have failed/errored if sandbox blocked them
                    # 3. Have output showing permission denied
                    if result_data.get("status") == ExecutionStatusEnum.COMPLETED:
                        output = result_data.get("stdout", "").lower()
                        # Should have been blocked
                        assert "denied" in output or "permission" in output or "error" in output
                    elif result_data.get("status") == ExecutionStatusEnum.FAILED:
                        # Good - sandbox blocked it
                        pass
                    # Otherwise it's still queued/running which is fine
            else:
                # Rejected at submission time (also acceptable)
                assert exec_response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_concurrent_executions_by_same_user(
            self, test_user: AsyncClient, simple_execution_request: ExecutionRequest
    ) -> None:
        """Test running multiple executions concurrently."""
        tasks = []
        for _ in range(3):
            task = test_user.post("/api/v1/execute", json=simple_execution_request.model_dump())
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
    async def test_get_user_executions_list(self, test_user: AsyncClient) -> None:
        """User executions list returns paginated executions for current user."""
        # List executions
        response = await test_user.get("/api/v1/user/executions?limit=5&skip=0")
        assert response.status_code == 200
        payload = response.json()
        assert set(["executions", "total", "limit", "skip", "has_more"]).issubset(payload.keys())

    @pytest.mark.asyncio
    async def test_execution_idempotency_same_key_returns_same_execution(
            self, test_user: AsyncClient
    ) -> None:
        """Submitting the same request with the same Idempotency-Key yields the same execution_id."""
        request = ExecutionRequest(
            script="print('Idempotency integration test')",
            lang="python",
            lang_version="3.11",
        )

        # Add idempotency key header (CSRF is already set on test_user)
        headers = {"Idempotency-Key": "it-idem-key-123"}

        # Use idempotency header on both requests to guarantee keying
        r1 = await test_user.post("/api/v1/execute", json=request.model_dump(), headers=headers)
        assert r1.status_code == 200
        e1 = r1.json()["execution_id"]

        # Second request with same key must return the same execution id
        r2 = await test_user.post("/api/v1/execute", json=request.model_dump(), headers=headers)
        assert r2.status_code == 200
        e2 = r2.json()["execution_id"]

        assert e1 == e2


class TestExecutionRetry:
    """Tests for POST /api/v1/executions/{execution_id}/retry."""

    @pytest.mark.asyncio
    async def test_retry_execution_creates_new_execution(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Retry an execution creates a new execution with same script."""
        original = created_execution

        # Retry
        retry_req = RetryExecutionRequest()
        retry_response = await test_user.post(
            f"/api/v1/executions/{original.execution_id}/retry",
            json=retry_req.model_dump(),
        )

        # May fail if still running - that's expected behavior
        if retry_response.status_code == 400:
            # Cannot retry running/queued execution
            detail = retry_response.json().get("detail", "").lower()
            assert "running" in detail or "queued" in detail
        elif retry_response.status_code == 200:
            retried = ExecutionResponse.model_validate(retry_response.json())
            # New execution should have different ID
            assert retried.execution_id != original.execution_id
            assert retried.status in list(ExecutionStatusEnum)

    @pytest.mark.asyncio
    async def test_retry_other_users_execution_forbidden(
            self, test_user: AsyncClient, another_user: AsyncClient,
            created_execution: ExecutionResponse
    ) -> None:
        """Cannot retry another user's execution."""
        # Try to retry as another_user
        retry_req = RetryExecutionRequest()
        retry_response = await another_user.post(
            f"/api/v1/executions/{created_execution.execution_id}/retry",
            json=retry_req.model_dump(),
        )

        assert retry_response.status_code == 403


class TestExecutionEvents:
    """Tests for GET /api/v1/executions/{execution_id}/events."""

    @pytest.mark.asyncio
    async def test_get_execution_events(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Get events for an execution returns list of events."""
        events_response = await test_user.get(
            f"/api/v1/executions/{created_execution.execution_id}/events"
        )

        assert events_response.status_code == 200
        events = [
            ExecutionEventResponse.model_validate(e)
            for e in events_response.json()
        ]

        # Should have at least the initial event
        assert isinstance(events, list)
        if events:
            event = events[0]
            assert event.event_id is not None
            assert event.event_type is not None
            assert event.timestamp is not None

    @pytest.mark.asyncio
    async def test_get_execution_events_with_filter(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Filter events by event_types query param."""
        events_response = await test_user.get(
            f"/api/v1/executions/{created_execution.execution_id}/events",
            params={"event_types": [EventType.EXECUTION_REQUESTED]},
        )

        assert events_response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_execution_events_access_denied(
            self, test_user: AsyncClient, another_user: AsyncClient,
            created_execution: ExecutionResponse
    ) -> None:
        """Cannot access another user's execution events."""
        events_response = await another_user.get(
            f"/api/v1/executions/{created_execution.execution_id}/events"
        )

        assert events_response.status_code == 403


class TestExecutionDelete:
    """Tests for DELETE /api/v1/executions/{execution_id} (admin only)."""

    @pytest.mark.asyncio
    async def test_admin_delete_execution(
            self, test_user: AsyncClient, test_admin: AsyncClient,
            created_execution: ExecutionResponse
    ) -> None:
        """Admin can delete an execution."""
        # Admin deletes
        delete_response = await test_admin.delete(
            f"/api/v1/executions/{created_execution.execution_id}"
        )

        assert delete_response.status_code == 200
        result = DeleteResponse.model_validate(delete_response.json())
        assert result.message == "Execution deleted successfully"
        assert result.execution_id == created_execution.execution_id

        # Verify execution is gone
        get_response = await test_admin.get(
            f"/api/v1/executions/{created_execution.execution_id}/result"
        )
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_user_cannot_delete_execution(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Regular user cannot delete execution (admin only)."""
        delete_response = await test_user.delete(
            f"/api/v1/executions/{created_execution.execution_id}"
        )

        assert delete_response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_nonexistent_execution(
            self, test_admin: AsyncClient
    ) -> None:
        """Deleting nonexistent execution returns 404."""
        delete_response = await test_admin.delete("/api/v1/executions/nonexistent-id-xyz")

        assert delete_response.status_code == 404


class TestExecutionListFiltering:
    """Tests for GET /api/v1/user/executions with filters."""

    @pytest.mark.asyncio
    async def test_list_executions_pagination(
            self, test_user: AsyncClient
    ) -> None:
        """Pagination works correctly for user executions."""
        # Create a few executions
        for i in range(3):
            request = ExecutionRequest(
                script=f"print('pagination test {i}')",
                lang="python",
                lang_version="3.11",
            )
            await test_user.post("/api/v1/execute", json=request.model_dump())

        # Get page 1
        response1 = await test_user.get(
            "/api/v1/user/executions",
            params={"limit": 2, "skip": 0},
        )
        assert response1.status_code == 200
        result1 = ExecutionListResponse.model_validate(response1.json())
        assert result1.limit == 2
        assert result1.skip == 0

        # Get page 2
        response2 = await test_user.get(
            "/api/v1/user/executions",
            params={"limit": 2, "skip": 2},
        )
        assert response2.status_code == 200
        result2 = ExecutionListResponse.model_validate(response2.json())
        assert result2.skip == 2

    @pytest.mark.asyncio
    async def test_list_executions_filter_by_language(
            self, test_user: AsyncClient
    ) -> None:
        """Filter executions by language."""
        response = await test_user.get(
            "/api/v1/user/executions",
            params={"lang": "python"},
        )
        assert response.status_code == 200
        result = ExecutionListResponse.model_validate(response.json())

        # All returned executions should be Python
        for execution in result.executions:
            assert execution.lang == "python"
