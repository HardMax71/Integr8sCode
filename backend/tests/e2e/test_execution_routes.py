"""E2E tests for execution routes.

Tests validate full execution lifecycle including waiting for terminal states.
E2E tests use the shared database (integr8scode_db) that workers also use,
enabling complete end-to-end validation of execution creation through completion.
"""

import asyncio

import pytest
from app.domain.enums import EventType, ExecutionStatus
from app.domain.events import ExecutionDomainEvent
from app.schemas_pydantic.execution import (
    CancelExecutionRequest,
    CancelResponse,
    DeleteResponse,
    ExampleScripts,
    ExecutionListResponse,
    ExecutionRequest,
    ExecutionResponse,
    ExecutionResult,
    ResourceLimits,
    RetryExecutionRequest,
)
from httpx import AsyncClient
from pydantic import TypeAdapter

from tests.e2e.conftest import EventWaiter

pytestmark = [pytest.mark.e2e, pytest.mark.k8s]

# TypeAdapter for parsing list of execution events from API response
ExecutionEventsAdapter = TypeAdapter(list[ExecutionDomainEvent])

# Initial states when execution is created
INITIAL_STATES = {
    ExecutionStatus.QUEUED,
    ExecutionStatus.SCHEDULED,
    ExecutionStatus.RUNNING,
}

# Terminal states that indicate execution has finished
TERMINAL_STATES = {
    ExecutionStatus.COMPLETED,
    ExecutionStatus.FAILED,
    ExecutionStatus.TIMEOUT,
    ExecutionStatus.CANCELLED,
    ExecutionStatus.ERROR,
}


async def submit_and_wait(
    client: AsyncClient,
    waiter: EventWaiter,
    request: ExecutionRequest,
    *,
    timeout: float = 30.0,
) -> tuple[ExecutionResponse, ExecutionResult]:
    """Submit script and wait for result via Kafka event — no polling."""
    resp = await client.post("/api/v1/execute", json=request.model_dump())
    assert resp.status_code == 200
    execution = ExecutionResponse.model_validate(resp.json())
    await waiter.wait_for_result(execution.execution_id, timeout=timeout)
    result_resp = await client.get(f"/api/v1/executions/{execution.execution_id}/result")
    assert result_resp.status_code == 200
    return execution, ExecutionResult.model_validate(result_resp.json())


class TestExecutionAuthentication:
    """Authentication requirement tests."""

    @pytest.mark.asyncio
    async def test_execute_requires_authentication(self, client: AsyncClient) -> None:
        """Unauthenticated request returns 401."""
        request = ExecutionRequest(script="print('test')", lang="python", lang_version="3.11")
        response = await client.post("/api/v1/execute", json=request.model_dump())

        assert response.status_code == 401


class TestExecutionHappyPath:
    """Tests for successful execution scenarios."""

    @pytest.mark.asyncio
    async def test_execute_simple_script_completes(
        self, test_user: AsyncClient, event_waiter: EventWaiter, simple_execution_request: ExecutionRequest
    ) -> None:
        """Simple script executes and completes successfully."""
        exec_response, result = await submit_and_wait(test_user, event_waiter, simple_execution_request)

        assert exec_response.execution_id
        assert result.status == ExecutionStatus.COMPLETED
        assert result.execution_id == exec_response.execution_id
        assert result.lang == "python"
        assert result.lang_version == "3.11"
        assert result.stdout is not None
        assert result.stdout.strip() == "test"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_execute_multiline_output(self, test_user: AsyncClient, event_waiter: EventWaiter) -> None:
        """Script with multiple print statements produces correct output."""
        request = ExecutionRequest(
            script="print('Line 1')\nprint('Line 2')\nprint('Line 3')",
            lang="python",
            lang_version="3.11",
        )

        _, result = await submit_and_wait(test_user, event_waiter, request)

        assert result.status == ExecutionStatus.COMPLETED
        assert result.stdout is not None
        assert result.stdout.strip() == "Line 1\nLine 2\nLine 3"

    @pytest.mark.asyncio
    async def test_execute_tracks_resource_usage(self, test_user: AsyncClient, event_waiter: EventWaiter) -> None:
        """Execution tracks resource usage metrics."""
        request = ExecutionRequest(
            script="import time; data = list(range(10000)); time.sleep(0.1); print('done')",
            lang="python",
            lang_version="3.11",
        )

        _, result = await submit_and_wait(test_user, event_waiter, request)

        assert result.status == ExecutionStatus.COMPLETED
        assert result.resource_usage is not None
        assert result.resource_usage.execution_time_wall_seconds >= 0.1
        assert result.resource_usage.peak_memory_kb > 0
        assert result.resource_usage.cpu_time_jiffies >= 0
        assert result.resource_usage.clk_tck_hertz > 0
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_execute_large_output(self, test_user: AsyncClient, event_waiter: EventWaiter) -> None:
        """Script with large output completes successfully."""
        request = ExecutionRequest(
            script="for i in range(500): print(f'Line {i}: ' + 'x' * 50)\nprint('END')",
            lang="python",
            lang_version="3.11",
        )

        _, result = await submit_and_wait(test_user, event_waiter, request, timeout=120)

        assert result.status == ExecutionStatus.COMPLETED
        assert result.stdout is not None
        assert "END" in result.stdout
        assert len(result.stdout) > 10000
        assert result.exit_code == 0
        assert "Line 0:" in result.stdout


class TestExecutionErrors:
    """Tests for execution error handling."""

    @pytest.mark.asyncio
    async def test_execute_syntax_error(self, test_user: AsyncClient, event_waiter: EventWaiter) -> None:
        """Script with syntax error fails with proper error info."""
        request = ExecutionRequest(
            script="def broken(\n    pass",  # Missing closing paren
            lang="python",
            lang_version="3.11",
        )

        _, result = await submit_and_wait(test_user, event_waiter, request)

        # Script errors result in COMPLETED status with non-zero exit code
        # FAILED is reserved for infrastructure/timeout failures
        assert result.status == ExecutionStatus.COMPLETED
        assert result.stderr is not None
        assert "SyntaxError" in result.stderr
        assert result.exit_code != 0

    @pytest.mark.asyncio
    async def test_execute_runtime_error(self, test_user: AsyncClient, event_waiter: EventWaiter) -> None:
        """Script with runtime error fails with traceback."""
        request = ExecutionRequest(
            script="print('before')\nraise ValueError('test error')\nprint('after')",
            lang="python",
            lang_version="3.11",
        )

        _, result = await submit_and_wait(test_user, event_waiter, request)

        # Script errors result in COMPLETED status with non-zero exit code
        # FAILED is reserved for infrastructure/timeout failures
        assert result.status == ExecutionStatus.COMPLETED
        assert result.stdout is not None
        assert "before" in result.stdout
        assert "after" not in result.stdout
        assert result.stderr is not None
        assert "ValueError" in result.stderr
        assert "test error" in result.stderr


class TestExecutionCancel:
    """Tests for execution cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_running_execution(
        self, test_user: AsyncClient, event_waiter: EventWaiter, long_running_execution_request: ExecutionRequest
    ) -> None:
        """Running execution can be cancelled."""
        response = await test_user.post("/api/v1/execute", json=long_running_execution_request.model_dump())
        assert response.status_code == 200

        exec_response = ExecutionResponse.model_validate(response.json())

        # Wait for saga to start (pod creation command sent) instead of blind sleep
        await event_waiter.wait_for_saga_command(exec_response.execution_id)

        cancel_req = CancelExecutionRequest(reason="Test cancellation")
        cancel_response = await test_user.post(
            f"/api/v1/executions/{exec_response.execution_id}/cancel",
            json=cancel_req.model_dump(),
        )
        assert cancel_response.status_code == 200

        cancel_result = CancelResponse.model_validate(cancel_response.json())
        assert cancel_result.execution_id == exec_response.execution_id
        assert cancel_result.status == "cancellation_requested"
        assert cancel_result.message

    @pytest.mark.asyncio
    async def test_cancel_completed_execution_fails(
        self, test_user: AsyncClient, event_waiter: EventWaiter
    ) -> None:
        """Cannot cancel already completed execution."""
        request = ExecutionRequest(script="print('quick')", lang="python", lang_version="3.11")
        exec_response, _ = await submit_and_wait(test_user, event_waiter, request)

        cancel_req = CancelExecutionRequest(reason="Too late")
        cancel_response = await test_user.post(
            f"/api/v1/executions/{exec_response.execution_id}/cancel",
            json=cancel_req.model_dump(),
        )

        assert cancel_response.status_code == 400
        assert "cannot cancel" in cancel_response.json()["detail"].lower()


class TestExecutionRetry:
    """Tests for execution retry."""

    @pytest.mark.asyncio
    async def test_retry_completed_execution(
        self, test_user: AsyncClient, event_waiter: EventWaiter
    ) -> None:
        """Completed execution can be retried."""
        request = ExecutionRequest(script="print('original')", lang="python", lang_version="3.11")
        original, _ = await submit_and_wait(test_user, event_waiter, request)

        retry_req = RetryExecutionRequest()
        retry_response = await test_user.post(
            f"/api/v1/executions/{original.execution_id}/retry",
            json=retry_req.model_dump(),
        )
        assert retry_response.status_code == 200

        retried = ExecutionResponse.model_validate(retry_response.json())
        assert retried.execution_id != original.execution_id

        # Wait for retried execution to complete
        await event_waiter.wait_for_result(retried.execution_id)
        result_resp = await test_user.get(f"/api/v1/executions/{retried.execution_id}/result")
        assert result_resp.status_code == 200
        result = ExecutionResult.model_validate(result_resp.json())
        assert result.status == ExecutionStatus.COMPLETED
        assert result.stdout is not None
        assert result.stdout.strip() == "original"

    @pytest.mark.asyncio
    async def test_retry_running_execution_fails(
        self, test_user: AsyncClient, long_running_execution_request: ExecutionRequest
    ) -> None:
        """Cannot retry execution that is still running."""
        response = await test_user.post("/api/v1/execute", json=long_running_execution_request.model_dump())
        assert response.status_code == 200

        exec_response = ExecutionResponse.model_validate(response.json())

        retry_req = RetryExecutionRequest()
        retry_response = await test_user.post(
            f"/api/v1/executions/{exec_response.execution_id}/retry",
            json=retry_req.model_dump(),
        )

        assert retry_response.status_code == 400
        assert "detail" in retry_response.json()

    @pytest.mark.asyncio
    async def test_retry_other_users_execution_forbidden(
        self, test_user: AsyncClient, another_user: AsyncClient, event_waiter: EventWaiter
    ) -> None:
        """Cannot retry another user's execution."""
        request = ExecutionRequest(script="print('owned')", lang="python", lang_version="3.11")
        original, _ = await submit_and_wait(test_user, event_waiter, request)

        retry_req = RetryExecutionRequest()
        retry_response = await another_user.post(
            f"/api/v1/executions/{original.execution_id}/retry",
            json=retry_req.model_dump(),
        )

        assert retry_response.status_code == 403


class TestExecutionEvents:
    """Tests for execution events."""

    @pytest.mark.asyncio
    async def test_get_execution_events(self, test_user: AsyncClient, event_waiter: EventWaiter) -> None:
        """Get events for completed execution."""
        request = ExecutionRequest(script="print('events test')", lang="python", lang_version="3.11")
        exec_response, _ = await submit_and_wait(test_user, event_waiter, request)

        events_response = await test_user.get(f"/api/v1/executions/{exec_response.execution_id}/events")
        assert events_response.status_code == 200

        events = ExecutionEventsAdapter.validate_python(events_response.json())
        assert len(events) >= 2
        event_types = {e.event_type for e in events}
        assert {EventType.EXECUTION_REQUESTED, EventType.EXECUTION_COMPLETED} <= event_types

    @pytest.mark.asyncio
    async def test_get_events_filtered_by_type(self, test_user: AsyncClient, event_waiter: EventWaiter) -> None:
        """Filter events by event type."""
        request = ExecutionRequest(script="print('filter test')", lang="python", lang_version="3.11")
        exec_response, _ = await submit_and_wait(test_user, event_waiter, request)

        events_response = await test_user.get(
            f"/api/v1/executions/{exec_response.execution_id}/events",
            params={"event_types": [EventType.EXECUTION_REQUESTED]},
        )
        assert events_response.status_code == 200

        events = ExecutionEventsAdapter.validate_python(events_response.json())
        for event in events:
            assert event.event_type == EventType.EXECUTION_REQUESTED

    @pytest.mark.asyncio
    async def test_get_events_access_denied(self, test_user: AsyncClient, another_user: AsyncClient) -> None:
        """Cannot access another user's execution events."""
        request = ExecutionRequest(script="print('private')", lang="python", lang_version="3.11")

        response = await test_user.post("/api/v1/execute", json=request.model_dump())
        assert response.status_code == 200

        exec_response = ExecutionResponse.model_validate(response.json())

        events_response = await another_user.get(f"/api/v1/executions/{exec_response.execution_id}/events")
        assert events_response.status_code == 403


class TestExecutionDelete:
    """Tests for execution deletion (admin only)."""

    @pytest.mark.asyncio
    @pytest.mark.admin
    async def test_admin_delete_execution(
        self, test_user: AsyncClient, test_admin: AsyncClient, event_waiter: EventWaiter
    ) -> None:
        """Admin can delete an execution."""
        request = ExecutionRequest(script="print('to delete')", lang="python", lang_version="3.11")
        exec_response, _ = await submit_and_wait(test_user, event_waiter, request)

        delete_response = await test_admin.delete(f"/api/v1/executions/{exec_response.execution_id}")
        assert delete_response.status_code == 200

        result = DeleteResponse.model_validate(delete_response.json())
        assert result.execution_id == exec_response.execution_id
        assert result.message == "Execution deleted successfully"

        # Verify gone
        get_response = await test_admin.get(f"/api/v1/executions/{exec_response.execution_id}/result")
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_user_cannot_delete_execution(self, test_user: AsyncClient) -> None:
        """Regular user cannot delete execution."""
        request = ExecutionRequest(script="print('no delete')", lang="python", lang_version="3.11")

        response = await test_user.post("/api/v1/execute", json=request.model_dump())
        assert response.status_code == 200

        exec_response = ExecutionResponse.model_validate(response.json())

        delete_response = await test_user.delete(f"/api/v1/executions/{exec_response.execution_id}")
        assert delete_response.status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.admin
    async def test_delete_nonexistent_execution(self, test_admin: AsyncClient) -> None:
        """Deleting nonexistent execution returns 404."""
        delete_response = await test_admin.delete("/api/v1/executions/nonexistent-id-xyz")
        assert delete_response.status_code == 404


class TestExecutionList:
    """Tests for execution listing."""

    @pytest.mark.asyncio
    async def test_get_user_executions(self, test_user: AsyncClient, event_waiter: EventWaiter) -> None:
        """User can list their executions."""
        request = ExecutionRequest(script="print('list test')", lang="python", lang_version="3.11")
        exec_response, _ = await submit_and_wait(test_user, event_waiter, request)

        list_response = await test_user.get("/api/v1/user/executions", params={"limit": 10, "skip": 0})
        assert list_response.status_code == 200

        result = ExecutionListResponse.model_validate(list_response.json())
        assert result.limit == 10
        assert result.skip == 0
        assert result.total >= 1
        assert len(result.executions) >= 1
        exec_ids = {e.execution_id for e in result.executions}
        assert exec_response.execution_id in exec_ids

    @pytest.mark.asyncio
    async def test_list_executions_pagination(self, test_user: AsyncClient) -> None:
        """Pagination works for execution list."""
        # Create executions
        for i in range(3):
            request = ExecutionRequest(script=f"print('page {i}')", lang="python", lang_version="3.11")
            response = await test_user.post("/api/v1/execute", json=request.model_dump())
            assert response.status_code == 200

        # Get first page
        page1_response = await test_user.get("/api/v1/user/executions", params={"limit": 2, "skip": 0})
        assert page1_response.status_code == 200

        page1 = ExecutionListResponse.model_validate(page1_response.json())
        assert page1.limit == 2
        assert page1.skip == 0
        assert len(page1.executions) == 2

        # Get second page
        page2_response = await test_user.get("/api/v1/user/executions", params={"limit": 2, "skip": 2})
        assert page2_response.status_code == 200

        page2 = ExecutionListResponse.model_validate(page2_response.json())
        assert page2.skip == 2
        assert len(page2.executions) >= 1

        ids1 = {e.execution_id for e in page1.executions}
        ids2 = {e.execution_id for e in page2.executions}
        assert ids1.isdisjoint(ids2)

    @pytest.mark.asyncio
    async def test_list_executions_filter_by_language(self, test_user: AsyncClient) -> None:
        """Filter executions by language."""
        request = ExecutionRequest(script="print('python')", lang="python", lang_version="3.11")
        response = await test_user.post("/api/v1/execute", json=request.model_dump())
        assert response.status_code == 200

        list_response = await test_user.get("/api/v1/user/executions", params={"lang": "python"})
        assert list_response.status_code == 200

        result = ExecutionListResponse.model_validate(list_response.json())
        assert len(result.executions) >= 1
        for execution in result.executions:
            assert execution.lang == "python"


class TestExecutionIdempotency:
    """Tests for idempotency."""

    @pytest.mark.asyncio
    async def test_same_idempotency_key_returns_same_execution(self, test_user: AsyncClient) -> None:
        """Same idempotency key returns same execution ID."""
        request = ExecutionRequest(script="print('idempotent')", lang="python", lang_version="3.11")
        headers = {"Idempotency-Key": "unique-key-12345"}

        response1 = await test_user.post("/api/v1/execute", json=request.model_dump(), headers=headers)
        assert response1.status_code == 200
        exec1 = ExecutionResponse.model_validate(response1.json())

        response2 = await test_user.post("/api/v1/execute", json=request.model_dump(), headers=headers)
        assert response2.status_code == 200
        exec2 = ExecutionResponse.model_validate(response2.json())

        assert exec1.execution_id == exec2.execution_id


class TestExecutionConcurrency:
    """Tests for concurrent executions."""

    @pytest.mark.asyncio
    @pytest.mark.xdist_group("execution_concurrency")
    async def test_concurrent_executions(self, test_user: AsyncClient, event_waiter: EventWaiter) -> None:
        """Multiple concurrent executions work correctly."""
        tasks = []
        for i in range(3):
            request = ExecutionRequest(script=f"print('concurrent {i}')", lang="python", lang_version="3.11")
            tasks.append(test_user.post("/api/v1/execute", json=request.model_dump()))

        responses = await asyncio.gather(*tasks)

        execution_ids = set()
        for response in responses:
            assert response.status_code == 200
            exec_response = ExecutionResponse.model_validate(response.json())
            execution_ids.add(exec_response.execution_id)

        # All IDs should be unique
        assert len(execution_ids) == 3

        # Wait for all to complete — parallel futures, not sequential polling
        await asyncio.gather(*(event_waiter.wait_for_result(eid) for eid in execution_ids))
        for exec_id in execution_ids:
            result_resp = await test_user.get(f"/api/v1/executions/{exec_id}/result")
            assert result_resp.status_code == 200
            result = ExecutionResult.model_validate(result_resp.json())
            assert result.status == ExecutionStatus.COMPLETED
            assert result.exit_code == 0
            assert result.stdout is not None


class TestPublicEndpoints:
    """Tests for public (unauthenticated) endpoints."""

    @pytest.mark.asyncio
    async def test_get_example_scripts(self, client: AsyncClient) -> None:
        """Example scripts endpoint returns scripts."""
        response = await client.get("/api/v1/example-scripts")
        assert response.status_code == 200

        result = ExampleScripts.model_validate(response.json())
        assert len(result.scripts) >= 1
        assert "python" in result.scripts
        assert len(result.scripts["python"]) > 0

    @pytest.mark.asyncio
    async def test_get_k8s_resource_limits(self, client: AsyncClient) -> None:
        """K8s limits endpoint returns resource limits."""
        response = await client.get("/api/v1/k8s-limits")
        assert response.status_code == 200

        result = ResourceLimits.model_validate(response.json())
        assert result.cpu_limit
        assert result.memory_limit
        assert result.cpu_request
        assert result.memory_request
        assert result.execution_timeout > 0
        assert "python" in result.supported_runtimes
        assert len(result.supported_runtimes["python"].versions) >= 1
