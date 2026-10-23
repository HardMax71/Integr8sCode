import asyncio

import pytest
from httpx2 import AsyncClient
from pydantic import TypeAdapter

from app.domain.enums import EventType, ExecutionStatus
from app.domain.events import DomainEvent
from app.infrastructure.kafka.topics import RESULT_TYPES
from app.runtime_registry import DEFAULT_LANG, DEFAULT_LANG_VERSION, at_least
from app.schemas_pydantic.execution import (
    CancelResponse,
    DeleteResponse,
    ExampleScripts,
    ExecutionListResponse,
    ExecutionRequest,
    ExecutionResponse,
    ExecutionResult,
    LanguageLimits,
    ResourceLimits,
)
from tests.e2e.conftest import create_execution, store_execution, wait_for_event

pytestmark = [pytest.mark.e2e]

# TypeAdapter for parsing list of execution events from API response
ExecutionEventsAdapter = TypeAdapter(list[DomainEvent])

# Initial states when execution is created
INITIAL_STATES = {
    ExecutionStatus.QUEUED,
    ExecutionStatus.SCHEDULED,
    ExecutionStatus.RUNNING,
}


async def submit_and_wait(
    client: AsyncClient, request: ExecutionRequest, *, timeout: float = 30.0
) -> tuple[ExecutionResponse, ExecutionResult]:
    """Submit a script and wait until its result is stored."""
    execution = await create_execution(client, request)
    await wait_for_event(execution.execution_id, *RESULT_TYPES, timeout=timeout)
    result_resp = await client.get(f"/api/v1/executions/{execution.execution_id}/result")
    assert result_resp.status_code == 200
    return execution, ExecutionResult.model_validate(result_resp.json())


class TestExecutionAuthentication:
    """Authentication requirement tests."""

    async def test_execute_requires_authentication(self, client: AsyncClient) -> None:
        """Unauthenticated request returns 401."""
        request = ExecutionRequest(script="print('test')")
        response = await client.post("/api/v1/execute", json=request.model_dump())

        assert response.status_code == 401


class TestExecutionHappyPath:
    """Tests for successful execution scenarios."""

    async def test_execute_simple_script_completes(
        self, test_user: AsyncClient, exec_request: ExecutionRequest
    ) -> None:
        """Simple script executes and completes successfully."""
        exec_response, result = await submit_and_wait(test_user, exec_request)

        assert exec_response.execution_id
        assert result.status == ExecutionStatus.COMPLETED
        assert result.execution_id == exec_response.execution_id
        assert (result.lang, result.lang_version) == (DEFAULT_LANG, DEFAULT_LANG_VERSION)
        assert result.stdout is not None
        assert result.stdout.strip() == "test"
        assert result.exit_code == 0

    async def test_execute_multiline_output(self, test_user: AsyncClient) -> None:
        """Script with multiple print statements produces correct output."""
        request = ExecutionRequest(
            script="print('Line 1')\nprint('Line 2')\nprint('Line 3')",
        )

        _, result = await submit_and_wait(test_user, request)

        assert result.status == ExecutionStatus.COMPLETED
        assert result.stdout is not None
        assert result.stdout.strip() == "Line 1\nLine 2\nLine 3"

    async def test_execute_tracks_resource_usage(self, test_user: AsyncClient) -> None:
        """Execution tracks resource usage metrics."""
        request = ExecutionRequest(
            script="import time; data = list(range(10000)); time.sleep(0.1); print('done')",
        )

        _, result = await submit_and_wait(test_user, request)

        assert result.status == ExecutionStatus.COMPLETED
        assert result.resource_usage is not None
        assert result.resource_usage.execution_time_wall_seconds >= 0.1
        assert result.resource_usage.peak_memory_kb > 0
        assert result.resource_usage.cpu_time_jiffies >= 0
        assert result.resource_usage.clk_tck_hertz > 0
        assert result.exit_code == 0

    async def test_execute_large_output(self, test_user: AsyncClient) -> None:
        """Script with large output completes successfully."""
        request = ExecutionRequest(
            script="for i in range(500): print(f'Line {i}: ' + 'x' * 50)\nprint('END')",
        )

        _, result = await submit_and_wait(test_user, request, timeout=60)

        assert result.status == ExecutionStatus.COMPLETED
        assert result.stdout is not None
        assert "END" in result.stdout
        assert len(result.stdout) > 10000
        assert result.exit_code == 0
        assert "Line 0:" in result.stdout


class TestExecutionErrors:
    """Tests for execution error handling."""

    async def test_execute_syntax_error(self, test_user: AsyncClient) -> None:
        """Script with syntax error fails with proper error info."""
        request = ExecutionRequest(
            script="def broken(\n    pass",  # Missing closing paren
        )

        _, result = await submit_and_wait(test_user, request)

        # Script errors result in COMPLETED status with non-zero exit code
        # FAILED is reserved for infrastructure/timeout failures
        assert result.status == ExecutionStatus.COMPLETED
        assert result.stderr is not None
        assert "SyntaxError" in result.stderr
        assert result.exit_code != 0

    async def test_execute_runtime_error(self, test_user: AsyncClient) -> None:
        """Script with runtime error fails with traceback."""
        request = ExecutionRequest(
            script="print('before')\nraise ValueError('test error')\nprint('after')",
        )

        _, result = await submit_and_wait(test_user, request)

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

    async def test_cancel_running_execution(
        self, test_user: AsyncClient, long_running_execution_request: ExecutionRequest
    ) -> None:
        """A cancelled execution ends as cancelled at once, instead of running its 30 seconds to completion."""
        response = await test_user.post("/api/v1/execute", json=long_running_execution_request.model_dump())
        assert response.status_code == 200

        exec_response = ExecutionResponse.model_validate(response.json())

        await wait_for_event(exec_response.execution_id, EventType.POD_CREATED)

        cancel_response = await test_user.post(f"/api/v1/executions/{exec_response.execution_id}/cancel")
        assert cancel_response.status_code == 200

        cancel_result = CancelResponse.model_validate(cancel_response.json())
        assert cancel_result.execution_id == exec_response.execution_id
        assert cancel_result.status == "cancellation_requested"
        assert cancel_result.message

        await wait_for_event(exec_response.execution_id, EventType.RESULT_STORED, timeout=15.0)
        result_response = await test_user.get(f"/api/v1/executions/{exec_response.execution_id}/result")
        assert result_response.status_code == 200
        assert ExecutionResult.model_validate(result_response.json()).status == ExecutionStatus.CANCELLED

    async def test_cancel_completed_execution_fails(self, test_user: AsyncClient) -> None:
        """Cannot cancel already completed execution."""
        request = ExecutionRequest(script="print('quick')")
        exec_response, _ = await submit_and_wait(test_user, request)

        cancel_response = await test_user.post(f"/api/v1/executions/{exec_response.execution_id}/cancel")

        assert cancel_response.status_code == 400
        assert "cannot cancel" in cancel_response.json()["detail"].lower()


class TestExecutionRetry:
    """Tests for execution retry."""

    async def test_retry_completed_execution(self, test_user: AsyncClient) -> None:
        """Completed execution can be retried."""
        request = ExecutionRequest(script="print('original')")
        original, _ = await submit_and_wait(test_user, request)

        retry_response = await test_user.post(
            f"/api/v1/executions/{original.execution_id}/retry",
        )
        assert retry_response.status_code == 200

        retried = ExecutionResponse.model_validate(retry_response.json())
        assert retried.execution_id != original.execution_id

        # Wait for retried execution to complete
        await wait_for_event(retried.execution_id, *RESULT_TYPES)
        result_resp = await test_user.get(f"/api/v1/executions/{retried.execution_id}/result")
        assert result_resp.status_code == 200
        result = ExecutionResult.model_validate(result_resp.json())
        assert result.status == ExecutionStatus.COMPLETED
        assert result.stdout is not None
        assert result.stdout.strip() == "original"

    async def test_retry_running_execution_fails(self, test_user: AsyncClient) -> None:
        """Cannot retry execution that is still running."""
        execution_id = await store_execution(test_user, status=ExecutionStatus.RUNNING)

        retry_response = await test_user.post(f"/api/v1/executions/{execution_id}/retry")

        assert retry_response.status_code == 400
        body = retry_response.json()
        assert body["status"] == 400
        assert body["detail"].startswith("Cannot retry execution in ")

    async def test_retry_other_users_execution_forbidden(
        self, test_user: AsyncClient, another_user: AsyncClient
    ) -> None:
        """Cannot retry another user's execution."""
        request = ExecutionRequest(script="print('owned')")
        original, _ = await submit_and_wait(test_user, request)

        retry_response = await another_user.post(
            f"/api/v1/executions/{original.execution_id}/retry",
        )

        assert retry_response.status_code == 403
        assert retry_response.json() == {
            "detail": f"Access denied to execution '{original.execution_id}'",
            "status": 403,
        }


class TestExecutionEvents:
    """Tests for execution events."""

    async def test_get_execution_events(self, test_user: AsyncClient) -> None:
        """Get events for completed execution."""
        request = ExecutionRequest(script="print('events test')")
        exec_response, _ = await submit_and_wait(test_user, request)

        events_response = await test_user.get(f"/api/v1/executions/{exec_response.execution_id}/events")
        assert events_response.status_code == 200

        events = ExecutionEventsAdapter.validate_python(events_response.json())
        assert len(events) >= 2
        event_types = {e.event_type for e in events}
        assert {EventType.EXECUTION_REQUESTED, EventType.EXECUTION_COMPLETED} <= event_types

    async def test_get_events_filtered_by_type(self, test_user: AsyncClient) -> None:
        """Filter events by event type."""
        request = ExecutionRequest(script="print('filter test')")
        exec_response, _ = await submit_and_wait(test_user, request)

        events_response = await test_user.get(
            f"/api/v1/executions/{exec_response.execution_id}/events",
            params={"event_types": [EventType.EXECUTION_REQUESTED]},
        )
        assert events_response.status_code == 200

        events = ExecutionEventsAdapter.validate_python(events_response.json())
        for event in events:
            assert event.event_type == EventType.EXECUTION_REQUESTED

    async def test_get_events_access_denied(self, test_user: AsyncClient, another_user: AsyncClient) -> None:
        """Cannot access another user's execution events."""
        execution_id = await store_execution(test_user)

        events_response = await another_user.get(f"/api/v1/executions/{execution_id}/events")
        assert events_response.status_code == 403
        assert events_response.json() == {
            "detail": f"Access denied to execution '{execution_id}'",
            "status": 403,
        }


class TestExecutionDelete:
    """Tests for execution deletion (admin only)."""

    async def test_admin_delete_execution(self, test_user: AsyncClient, test_admin: AsyncClient) -> None:
        """Admin can delete an execution."""
        execution_id = await store_execution(test_user)

        delete_response = await test_admin.delete(f"/api/v1/executions/{execution_id}")
        assert delete_response.status_code == 200

        result = DeleteResponse.model_validate(delete_response.json())
        assert result.execution_id == execution_id
        assert result.message == "Execution deleted successfully"

        get_response = await test_admin.get(f"/api/v1/executions/{execution_id}/result")
        assert get_response.status_code == 404

    async def test_user_cannot_delete_execution(self, test_user: AsyncClient) -> None:
        """Regular user cannot delete execution."""
        execution_id = await store_execution(test_user)

        delete_response = await test_user.delete(f"/api/v1/executions/{execution_id}")
        assert delete_response.status_code == 403

    async def test_delete_nonexistent_execution(self, test_admin: AsyncClient) -> None:
        """Deleting nonexistent execution returns 404."""
        delete_response = await test_admin.delete("/api/v1/executions/nonexistent-id-xyz")
        assert delete_response.status_code == 404


class TestExecutionList:
    """Tests for execution listing."""

    async def test_get_user_executions(self, test_user: AsyncClient) -> None:
        """User can list their executions."""
        execution_id = await store_execution(test_user)

        list_response = await test_user.get("/api/v1/user/executions", params={"limit": 10, "skip": 0})
        assert list_response.status_code == 200

        result = ExecutionListResponse.model_validate(list_response.json())
        assert (result.limit, result.skip, result.total) == (10, 0, 1)
        assert [e.execution_id for e in result.executions] == [execution_id]

    async def test_list_executions_pagination(self, test_user: AsyncClient) -> None:
        """Pagination works for execution list."""
        stored = {await store_execution(test_user) for _ in range(3)}

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
        assert {e.execution_id for e in page1.executions + page2.executions} == stored

    async def test_list_executions_filter_by_language(self, test_user: AsyncClient) -> None:
        """Filter executions by language."""
        python_id = await store_execution(test_user)
        await store_execution(test_user, lang="bash")

        list_response = await test_user.get("/api/v1/user/executions", params={"lang": DEFAULT_LANG})
        assert list_response.status_code == 200

        result = ExecutionListResponse.model_validate(list_response.json())
        assert [e.execution_id for e in result.executions] == [python_id]


class TestExecutionIdempotency:
    """Tests for idempotency."""

    async def test_same_idempotency_key_returns_same_execution(self, test_user: AsyncClient) -> None:
        """Same idempotency key returns same execution ID."""
        request = ExecutionRequest(script="print('idempotent')")
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

    async def test_concurrent_executions(self, test_user: AsyncClient) -> None:
        """Multiple concurrent executions work correctly."""
        tasks = []
        for i in range(3):
            request = ExecutionRequest(script=f"print('concurrent {i}')")
            tasks.append(test_user.post("/api/v1/execute", json=request.model_dump()))

        responses = await asyncio.gather(*tasks)

        execution_ids = set()
        for response in responses:
            assert response.status_code == 200
            exec_response = ExecutionResponse.model_validate(response.json())
            execution_ids.add(exec_response.execution_id)

        # All IDs should be unique
        assert len(execution_ids) == 3

        # Wait for all to complete — parallel subscriptions, not sequential polling
        await asyncio.gather(*(wait_for_event(eid, *RESULT_TYPES) for eid in execution_ids))
        for exec_id in execution_ids:
            result_resp = await test_user.get(f"/api/v1/executions/{exec_id}/result")
            assert result_resp.status_code == 200
            result = ExecutionResult.model_validate(result_resp.json())
            assert result.status == ExecutionStatus.COMPLETED
            assert result.exit_code == 0
            assert result.stdout is not None


class TestPublicEndpoints:
    """Tests for public (unauthenticated) endpoints."""

    async def test_get_example_scripts(self, client: AsyncClient) -> None:
        """Example scripts endpoint returns scripts."""
        response = await client.get("/api/v1/example-scripts")
        assert response.status_code == 200

        result = ExampleScripts.model_validate(response.json())
        assert len(result.scripts) >= 1
        assert "python" in result.scripts
        assert len(result.scripts["python"]) > 0

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
        assert result.language_limits.keys() == result.supported_runtimes.keys()
        assert result.language_limits["python"] == LanguageLimits(
            cpu_limit=result.cpu_limit, memory_limit=result.memory_limit, execution_timeout=result.execution_timeout
        )
        assert result.language_limits["go"] == LanguageLimits(
            cpu_limit=at_least(result.cpu_limit, "1000m"),
            memory_limit=at_least(result.memory_limit, "320Mi"),
            execution_timeout=max(result.execution_timeout, 30),
        )
