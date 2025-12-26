"""Tests for execution API mapper."""

import pytest

from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.storage import ExecutionErrorType
from app.domain.execution import DomainExecution, ResourceUsageDomain
from app.infrastructure.mappers.execution_api_mapper import ExecutionApiMapper


@pytest.fixture
def sample_execution():
    """Create a sample domain execution."""
    return DomainExecution(
        execution_id="exec-123",
        status=ExecutionStatus.COMPLETED,
        lang="python",
        lang_version="3.11",
        stdout="Hello, World!",
        stderr="",
        exit_code=0,
        error_type=None,
        resource_usage=ResourceUsageDomain(
            execution_time_wall_seconds=1.5,
            cpu_time_jiffies=150,
            clk_tck_hertz=100,
            peak_memory_kb=2048,
        ),
    )


class TestExecutionApiMapper:
    """Test execution API mapper."""

    def test_to_response(self, sample_execution):
        """Test converting domain execution to response."""
        response = ExecutionApiMapper.to_response(sample_execution)

        assert response.execution_id == "exec-123"
        assert response.status == ExecutionStatus.COMPLETED

    def test_to_response_minimal(self):
        """Test converting minimal domain execution to response."""
        execution = DomainExecution(
            execution_id="exec-456",
            status=ExecutionStatus.RUNNING,
        )

        response = ExecutionApiMapper.to_response(execution)

        assert response.execution_id == "exec-456"
        assert response.status == ExecutionStatus.RUNNING

    def test_to_result_with_resource_usage(self, sample_execution):
        """Test converting domain execution to result with resource usage."""
        result = ExecutionApiMapper.to_result(sample_execution)

        assert result.execution_id == "exec-123"
        assert result.status == ExecutionStatus.COMPLETED
        assert result.stdout == "Hello, World!"
        assert result.stderr == ""
        assert result.lang == "python"
        assert result.lang_version == "3.11"
        assert result.exit_code == 0
        assert result.error_type is None
        assert result.resource_usage is not None
        assert result.resource_usage.execution_time_wall_seconds == 1.5
        assert result.resource_usage.cpu_time_jiffies == 150
        assert result.resource_usage.clk_tck_hertz == 100
        assert result.resource_usage.peak_memory_kb == 2048

    def test_to_result_without_resource_usage(self):
        """Test converting domain execution to result without resource usage."""
        execution = DomainExecution(
            execution_id="exec-789",
            status=ExecutionStatus.FAILED,
            lang="javascript",
            lang_version="20",
            stdout="",
            stderr="Error occurred",
            exit_code=1,
            error_type=ExecutionErrorType.SCRIPT_ERROR,
            resource_usage=None,
        )

        result = ExecutionApiMapper.to_result(execution)

        assert result.execution_id == "exec-789"
        assert result.status == ExecutionStatus.FAILED
        assert result.stdout == ""
        assert result.stderr == "Error occurred"
        assert result.lang == "javascript"
        assert result.lang_version == "20"
        assert result.exit_code == 1
        assert result.error_type == ExecutionErrorType.SCRIPT_ERROR
        assert result.resource_usage is None

    def test_to_result_with_script_error(self):
        """Test converting domain execution with script error."""
        execution = DomainExecution(
            execution_id="exec-001",
            status=ExecutionStatus.FAILED,
            error_type=ExecutionErrorType.SCRIPT_ERROR,
        )

        result = ExecutionApiMapper.to_result(execution)

        assert result.error_type == ExecutionErrorType.SCRIPT_ERROR

    def test_to_result_with_timeout_error(self):
        """Test converting domain execution with timeout error."""
        execution = DomainExecution(
            execution_id="exec-002",
            status=ExecutionStatus.FAILED,
            error_type=ExecutionErrorType.TIMEOUT,
        )

        result = ExecutionApiMapper.to_result(execution)

        assert result.error_type == ExecutionErrorType.TIMEOUT

    def test_to_result_with_resource_limit_error(self):
        """Test converting domain execution with resource limit error."""
        execution = DomainExecution(
            execution_id="exec-003",
            status=ExecutionStatus.FAILED,
            error_type=ExecutionErrorType.RESOURCE_LIMIT,
        )

        result = ExecutionApiMapper.to_result(execution)

        assert result.error_type == ExecutionErrorType.RESOURCE_LIMIT

    def test_to_result_with_system_error(self):
        """Test converting domain execution with system error."""
        execution = DomainExecution(
            execution_id="exec-004",
            status=ExecutionStatus.FAILED,
            error_type=ExecutionErrorType.SYSTEM_ERROR,
        )

        result = ExecutionApiMapper.to_result(execution)

        assert result.error_type == ExecutionErrorType.SYSTEM_ERROR

    def test_to_result_with_permission_denied_error(self):
        """Test converting domain execution with permission denied error."""
        execution = DomainExecution(
            execution_id="exec-005",
            status=ExecutionStatus.FAILED,
            error_type=ExecutionErrorType.PERMISSION_DENIED,
        )

        result = ExecutionApiMapper.to_result(execution)

        assert result.error_type == ExecutionErrorType.PERMISSION_DENIED

    def test_to_result_with_no_error_type(self):
        """Test converting domain execution with no error type."""
        execution = DomainExecution(
            execution_id="exec-006",
            status=ExecutionStatus.COMPLETED,
            error_type=None,
        )

        result = ExecutionApiMapper.to_result(execution)

        assert result.error_type is None

    def test_to_result_minimal(self):
        """Test converting minimal domain execution to result."""
        execution = DomainExecution(
            execution_id="exec-minimal",
            status=ExecutionStatus.QUEUED,
            lang="python",  # Required field in ExecutionResult
            lang_version="3.11",  # Required field in ExecutionResult
        )

        result = ExecutionApiMapper.to_result(execution)

        assert result.execution_id == "exec-minimal"
        assert result.status == ExecutionStatus.QUEUED
        assert result.stdout is None
        assert result.stderr is None
        assert result.lang == "python"
        assert result.lang_version == "3.11"
        assert result.exit_code is None
        assert result.error_type is None
        assert result.resource_usage is None

    def test_to_result_all_fields_populated(self):
        """Test converting fully populated domain execution to result."""
        resource_usage = ResourceUsageDomain(
            execution_time_wall_seconds=2.5,
            cpu_time_jiffies=250,
            clk_tck_hertz=100,
            peak_memory_kb=4096,
        )

        execution = DomainExecution(
            execution_id="exec-full",
            status=ExecutionStatus.COMPLETED,
            lang="python",
            lang_version="3.11",
            stdout="Success output",
            stderr="Debug info",
            exit_code=0,
            error_type=None,
            resource_usage=resource_usage,
        )

        result = ExecutionApiMapper.to_result(execution)

        assert result.execution_id == "exec-full"
        assert result.status == ExecutionStatus.COMPLETED
        assert result.stdout == "Success output"
        assert result.stderr == "Debug info"
        assert result.lang == "python"
        assert result.lang_version == "3.11"
        assert result.exit_code == 0
        assert result.error_type is None
        assert result.resource_usage is not None
        assert result.resource_usage.execution_time_wall_seconds == 2.5
        assert result.resource_usage.cpu_time_jiffies == 250
        assert result.resource_usage.clk_tck_hertz == 100
        assert result.resource_usage.peak_memory_kb == 4096