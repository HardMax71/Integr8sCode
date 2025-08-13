from unittest.mock import AsyncMock, Mock, patch

import pytest
from app.api.routes.execution import create_execution, get_result, get_example_scripts, get_k8s_resource_limits
from app.core.exceptions import IntegrationException
from app.schemas_pydantic.execution import ExecutionRequest
from fastapi import HTTPException, Request


class TestExecutionRoutesCoverage:

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.mock_request = Mock(spec=Request)
        self.mock_execution_service = AsyncMock()
        self.execution_request = ExecutionRequest(
            script="print('hello')",
            lang="python",
            lang_version="3.9"
        )

    def _setup_metrics_patches(self) -> dict:
        return {
            'active': patch('app.api.routes.execution.ACTIVE_EXECUTIONS'),
            'duration': patch('app.api.routes.execution.EXECUTION_DURATION'),
            'script': patch('app.api.routes.execution.SCRIPT_EXECUTIONS')
        }

    def _configure_metrics_mocks(self, mock_active: Mock, mock_duration: Mock, mock_script: Mock) -> None:
        mock_duration.labels.return_value.time.return_value.__enter__ = Mock()
        mock_duration.labels.return_value.time.return_value.__exit__ = Mock(return_value=False)

    @pytest.mark.asyncio
    async def test_create_execution_scenarios(self) -> None:
        execution_cases = [
            (IntegrationException(status_code=400, detail="Integration error"), 400, "Integration error",
             "integration_error"),
            (Exception("Unexpected error"), 500, "Internal server error during script execution", "error"),
            (Mock(id="test-id", status="pending"), None, None, "success")
        ]

        for exception_or_result, expected_status, expected_detail, expected_metric_status in execution_cases:
            self.mock_execution_service.reset_mock()

            if isinstance(exception_or_result, Exception):
                self.mock_execution_service.execute_script.side_effect = exception_or_result
            else:
                self.mock_execution_service.execute_script.side_effect = None
                self.mock_execution_service.execute_script.return_value = exception_or_result

            patches = self._setup_metrics_patches()

            with patch('app.api.routes.execution.get_remote_address', return_value="127.0.0.1"):
                with patches['active'] as mock_active:
                    with patches['duration'] as mock_duration:
                        with patches['script'] as mock_script:
                            self._configure_metrics_mocks(mock_active, mock_duration, mock_script)

                            if expected_status:
                                with pytest.raises(HTTPException) as exc_info:
                                    await create_execution(self.mock_request, self.execution_request,
                                                           self.mock_execution_service)

                                assert exc_info.value.status_code == expected_status
                                assert exc_info.value.detail == expected_detail
                            else:
                                result = await create_execution(self.mock_request, self.execution_request,
                                                                self.mock_execution_service)
                                assert result.execution_id == "test-id"
                                assert result.status == "pending"

                            mock_active.inc.assert_called_once()
                            mock_active.dec.assert_called_once()
                            mock_script.labels.assert_called_with(
                                status=expected_metric_status,
                                lang_and_version="python-3.9"
                            )

    @pytest.mark.asyncio
    async def test_get_result_scenarios(self) -> None:
        result_cases = [
            (None, 404, "Execution not found"),
            (Mock(id="test-id", status="completed", output="Hello World", errors="",
                  lang="python", lang_version="3.9",
                  resource_usage={"cpu_usage": 0.1, "memory_usage": 128.0, "execution_time": 2.5}), None, None),
            (Mock(id="test-id", status="completed", output="Hello World", errors="Some error",
                  lang="python", lang_version="3.9", resource_usage=None), None, None)
        ]

        for mock_result, expected_status, expected_detail in result_cases:
            self.mock_execution_service.get_execution_result.return_value = mock_result

            with patch('app.api.routes.execution.get_remote_address', return_value="127.0.0.1"):
                if expected_status:
                    with pytest.raises(HTTPException) as exc_info:
                        await get_result(self.mock_request, "test-id", self.mock_execution_service)

                    assert exc_info.value.status_code == expected_status
                    assert exc_info.value.detail == expected_detail
                else:
                    result = await get_result(self.mock_request, "test-id", self.mock_execution_service)

                    assert result.execution_id == "test-id"
                    assert result.status == "completed"
                    assert result.output == "Hello World"

                    if mock_result and mock_result.resource_usage:
                        assert result.resource_usage is not None
                    else:
                        assert result.resource_usage is None
                        assert result.errors == "Some error"

    @pytest.mark.asyncio
    async def test_get_example_scripts_successful(self) -> None:
        mock_scripts = {"python": "print('hello')", "node": "console.log('hello')"}
        self.mock_execution_service.get_example_scripts.return_value = mock_scripts

        result = await get_example_scripts(self.mock_execution_service)

        assert result.scripts == mock_scripts

    @pytest.mark.asyncio
    async def test_get_k8s_resource_limits_scenarios(self) -> None:
        limits_cases = [
            ({
                 "cpu_limit": "1000m",
                 "memory_limit": "1Gi",
                 "cpu_request": "100m",
                 "memory_request": "128Mi",
                 "execution_timeout": 300,
                 "supported_runtimes": {"python": ["3.9", "3.11"], "node": ["18", "20"]}
             }, None, None),
            (Exception("K8s error"), 500, "Failed to retrieve resource limits")
        ]

        for limits_or_exception, expected_status, expected_detail in limits_cases:
            if isinstance(limits_or_exception, Exception):
                self.mock_execution_service.get_k8s_resource_limits.side_effect = limits_or_exception
            else:
                self.mock_execution_service.get_k8s_resource_limits.side_effect = None
                self.mock_execution_service.get_k8s_resource_limits.return_value = limits_or_exception

            if expected_status:
                with pytest.raises(HTTPException) as exc_info:
                    await get_k8s_resource_limits(self.mock_execution_service)

                assert exc_info.value.status_code == expected_status
                assert exc_info.value.detail == expected_detail
            else:
                result = await get_k8s_resource_limits(self.mock_execution_service)

                assert result.cpu_limit == "1000m"
                assert result.memory_limit == "1Gi"

            self.mock_execution_service.reset_mock()
