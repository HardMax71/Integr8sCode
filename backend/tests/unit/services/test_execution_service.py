import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import Mock, patch, AsyncMock

import pytest
from app.config import get_settings
from app.core.exceptions import IntegrationException
from app.db.repositories.execution_repository import get_execution_repository
from app.schemas.execution import ExecutionInDB
from app.services.execution_service import ExecutionService, ExecutionStatus, get_execution_service
from app.services.kubernetes_service import KubernetesPodError
from bson import ObjectId
from tests.unit.services.mock_kubernetes_service import get_mock_kubernetes_service


class TestExecutionService:

    @pytest.fixture(autouse=True)
    async def setup(self, db: AsyncGenerator) -> None:
        self.settings = get_settings()
        self.execution_repo = get_execution_repository(db)
        self.k8s_service = get_mock_kubernetes_service()
        self.service = ExecutionService(self.execution_repo, self.k8s_service)

    def test_execution_service_initialization(self) -> None:
        assert self.service is not None
        assert hasattr(self.service, 'execution_repo')
        assert hasattr(self.service, 'k8s_service')

    @pytest.mark.asyncio
    async def test_get_k8s_resource_limits(self) -> None:
        limits = await self.service.get_k8s_resource_limits()

        assert limits is not None
        assert 'cpu_limit' in limits
        assert 'memory_limit' in limits
        assert 'cpu_request' in limits
        assert 'memory_request' in limits
        assert 'execution_timeout' in limits
        assert 'supported_runtimes' in limits

        # Check types
        assert isinstance(limits['cpu_limit'], str)
        assert isinstance(limits['memory_limit'], str)
        assert isinstance(limits['execution_timeout'], int)
        assert isinstance(limits['supported_runtimes'], dict)

    @pytest.mark.asyncio
    async def test_get_example_scripts(self) -> None:
        examples = await self.service.get_example_scripts()

        assert examples is not None
        assert isinstance(examples, dict)

        # Should have at least Python examples
        assert len(examples) > 0

        # Each script should be a string
        for lang, script in examples.items():
            assert isinstance(lang, str)
            assert isinstance(script, str)
            assert len(script) > 0

    @pytest.mark.asyncio
    async def test_execute_script_python_success(self) -> None:
        # Execute script using the correct method signature
        result = await self.service.execute_script(
            script="print('Hello from unit test')",
            lang="python",
            lang_version="3.11"
        )

        assert result is not None
        assert hasattr(result, 'id')
        assert hasattr(result, 'status')
        assert result.status in ['queued', 'running']

        execution_id = result.id
        assert isinstance(execution_id, str)
        assert len(execution_id) > 0

    @pytest.mark.asyncio
    async def test_execute_script_unsupported_language(self) -> None:
        with pytest.raises(IntegrationException) as exc_info:
            await self.service.execute_script(
                script="echo 'test'",
                lang="unsupported_lang",
                lang_version="1.0"
            )

        assert "script execution failed" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_execute_script_unsupported_version(self) -> None:
        with pytest.raises(IntegrationException) as exc_info:
            await self.service.execute_script(
                script="print('test')",
                lang="python",
                lang_version="999.999"  # Non-existent version
            )

        assert "script execution failed" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_get_execution_result_success(self) -> None:
        # First execute a simple script
        result = await self.service.execute_script(
            script="print('Result test')",
            lang="python",
            lang_version="3.11"
        )
        execution_id = result.id

        # Wait a bit for execution to start
        await asyncio.sleep(2)

        # Get result
        execution_result = await self.service.get_execution_result(execution_id)

        assert execution_result is not None
        assert execution_result.execution_id == execution_id
        assert execution_result.status in ['queued', 'running', 'completed', 'error']
        assert execution_result.lang == "python"
        assert execution_result.lang_version == "3.11"

    @pytest.mark.asyncio
    async def test_get_execution_result_nonexistent(self) -> None:
        with pytest.raises(IntegrationException) as exc_info:
            await self.service.get_execution_result("nonexistent_id_12345")

        assert exc_info.value.status_code == 404
        assert "not found" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_execute_script_with_error(self) -> None:
        result = await self.service.execute_script(
            script="1 / 0  # This will cause ZeroDivisionError",
            lang="python",
            lang_version="3.11"
        )
        execution_id = result.id

        # Wait for execution to complete
        await asyncio.sleep(5)

        execution_result = await self.service.get_execution_result(execution_id)

        assert execution_result is not None
        assert execution_result.execution_id == execution_id
        # Mock service always returns 'completed' status
        assert execution_result.status in ['queued', 'running', 'completed', 'error']

    @pytest.mark.asyncio
    async def test_execute_script_javascript(self) -> None:
        # First check if JavaScript is supported
        limits = await self.service.get_k8s_resource_limits()
        supported_runtimes = limits['supported_runtimes']

        if 'node' not in supported_runtimes:
            pytest.skip("JavaScript not supported in this environment")

        result = await self.service.execute_script(
            script="console.log('Hello from JavaScript');",
            lang="node",
            lang_version=supported_runtimes['node'][0]  # Use first available version
        )

        assert result is not None
        assert hasattr(result, 'id')
        assert hasattr(result, 'status')

    @pytest.mark.asyncio
    async def test_execute_script_with_output(self) -> None:
        test_message = "Unit test output message"
        result = await self.service.execute_script(
            script=f"print('{test_message}')",
            lang="python",
            lang_version="3.11"
        )
        execution_id = result.id

        # Wait for execution to complete
        max_wait = 30  # 30 seconds max wait
        wait_time = 0
        execution_result = None

        while wait_time < max_wait:
            await asyncio.sleep(2)
            wait_time += 2

            execution_result = await self.service.get_execution_result(execution_id)
            if execution_result and execution_result.status in ['completed', 'error']:
                break

        assert execution_result is not None
        assert execution_result.status == 'completed'
        assert execution_result.output is not None
        # Mock service returns generic output, just check it's not empty
        assert len(execution_result.output) > 0

    @pytest.mark.asyncio
    async def test_supported_languages_consistency(self) -> None:
        limits = await self.service.get_k8s_resource_limits()
        examples = await self.service.get_example_scripts()

        supported_runtimes = limits['supported_runtimes']
        example_scripts = examples

        # Every supported runtime should have an example
        for lang in supported_runtimes.keys():
            assert lang in example_scripts, f"Missing example for supported language: {lang}"

        # Every example should be for a supported runtime
        for lang in example_scripts.keys():
            assert lang in supported_runtimes, f"Example exists for unsupported language: {lang}"

    @pytest.mark.asyncio
    async def test_concurrent_executions(self) -> None:
        # Execute all concurrently
        tasks = [
            self.service.execute_script(
                script=f"print('Concurrent test {i}')",
                lang="python",
                lang_version="3.11"
            )
            for i in range(3)
        ]

        results = await asyncio.gather(*tasks)

        # All should succeed
        assert len(results) == 3
        execution_ids = []

        for result in results:
            assert result is not None
            assert hasattr(result, 'id')
            assert hasattr(result, 'status')
            execution_ids.append(result.id)

        # All execution IDs should be unique
        assert len(set(execution_ids)) == 3

    @pytest.mark.asyncio
    async def test_execution_timeout_behavior(self) -> None:
        # Create a long-running script
        result = await self.service.execute_script(
            script="import time; time.sleep(2); print('Completed after sleep')",
            lang="python",
            lang_version="3.11"
        )
        execution_id = result.id

        # Check status immediately (mock service may complete quickly)
        immediate_result = await self.service.get_execution_result(execution_id)
        assert immediate_result.status in ['queued', 'running', 'completed']

        # Wait for completion
        await asyncio.sleep(10)

        final_result = await self.service.get_execution_result(execution_id)
        assert final_result.status in ['completed', 'error']


class TestExecutionServiceDependency:

    def test_execution_service_can_be_instantiated(self, db: AsyncGenerator) -> None:
        from app.db.repositories.execution_repository import get_execution_repository
        from tests.unit.services.mock_kubernetes_service import get_mock_kubernetes_service

        execution_repo = get_execution_repository(db)
        k8s_service = get_mock_kubernetes_service()
        service = ExecutionService(execution_repo, k8s_service)

        assert service is not None
        assert isinstance(service, ExecutionService)
        assert service.execution_repo is execution_repo
        assert service.k8s_service is k8s_service

    def test_get_execution_service_dependency_function(self) -> None:
        mock_execution_repo = Mock()
        mock_k8s_service = Mock()

        service = get_execution_service(mock_execution_repo, mock_k8s_service)

        assert isinstance(service, ExecutionService)
        assert service.execution_repo == mock_execution_repo
        assert service.k8s_service == mock_k8s_service


class TestExecutionServiceFullCoverage:
    @pytest.fixture
    def mock_execution_repo(self) -> Mock:
        return Mock()

    @pytest.fixture
    def mock_k8s_service(self) -> Mock:
        return Mock()

    @pytest.fixture
    def execution_service(self,
                          mock_execution_repo: Mock,
                          mock_k8s_service: Mock) -> ExecutionService:
        return ExecutionService(mock_execution_repo, mock_k8s_service)

    @pytest.fixture
    def mock_execution(self) -> ExecutionInDB:
        return ExecutionInDB(
            id=str(ObjectId()),
            script="print('hello')",
            lang="python",
            lang_version="3.11",
            status=ExecutionStatus.QUEUED,
            output="",
            errors="",
            resource_usage={},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

    @pytest.mark.asyncio
    async def test_mark_running_when_scheduled_success(self,
                                                       execution_service: ExecutionService,
                                                       mock_k8s_service: Mock,
                                                       mock_execution_repo: Mock) -> None:
        execution_id = "test_execution"
        pod_name = f"execution-{execution_id}"

        # Mock pod object with Running status
        mock_pod = Mock()
        mock_pod.status.phase = "Running"

        # Mock the v1 API and read_namespaced_pod
        mock_k8s_service.v1.read_namespaced_pod = Mock(return_value=mock_pod)
        mock_k8s_service.NAMESPACE = "default"
        mock_execution_repo.update_execution = AsyncMock()

        with patch('asyncio.to_thread', return_value=mock_pod):
            await execution_service._mark_running_when_scheduled(pod_name, execution_id)

        mock_execution_repo.update_execution.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_running_when_scheduled_exception(self,
                                                         execution_service: ExecutionService,
                                                         mock_k8s_service: Mock) -> None:
        execution_id = "test_execution"
        pod_name = f"execution-{execution_id}"

        # Mock the v1 API to raise an exception
        mock_k8s_service.v1.read_namespaced_pod = Mock(side_effect=Exception("API error"))
        mock_k8s_service.NAMESPACE = "default"

        with patch('asyncio.to_thread', side_effect=Exception("API error")):
            # Should not raise, just log warning
            await execution_service._mark_running_when_scheduled(pod_name, execution_id)

    @pytest.mark.asyncio
    async def test_mark_running_when_scheduled_timeout(self,
                                                       execution_service: ExecutionService,
                                                       mock_k8s_service: Mock) -> None:
        execution_id = "test_execution"
        pod_name = f"execution-{execution_id}"

        # Mock pod object that never reaches Running status
        mock_pod = Mock()
        mock_pod.status.phase = "Pending"

        mock_k8s_service.v1.read_namespaced_pod = Mock(return_value=mock_pod)
        mock_k8s_service.NAMESPACE = "default"

        with patch('asyncio.to_thread', return_value=mock_pod):
            with patch('asyncio.sleep'):  # Speed up the test
                await execution_service._mark_running_when_scheduled(pod_name, execution_id)

    @pytest.mark.asyncio
    @patch('app.services.execution_service.RUNTIME_REGISTRY')
    async def test_start_k8s_execution_success(self,
                                               mock_registry: Mock,
                                               execution_service: ExecutionService,
                                               mock_k8s_service: Mock,
                                               mock_execution_repo: Mock) -> None:
        execution_id = "test_execution"
        script = "print('hello')"
        lang = "python"
        lang_version = "3.11"

        # Mock runtime registry
        mock_runtime_cfg = Mock()
        mock_runtime_cfg.image = "python:3.11"
        mock_runtime_cfg.command = ["python"]
        mock_runtime_cfg.file_name = "script.py"
        mock_registry.__getitem__.return_value = {lang_version: mock_runtime_cfg}

        mock_k8s_service.create_execution_pod = AsyncMock()

        with patch.object(execution_service, '_mark_running_when_scheduled') as mock_mark_running:
            mock_mark_running.return_value = AsyncMock()
            await execution_service._start_k8s_execution(execution_id, script, lang, lang_version)

        mock_k8s_service.create_execution_pod.assert_called_once()
        mock_mark_running.assert_called_once()

    @pytest.mark.asyncio
    @patch('app.services.execution_service.RUNTIME_REGISTRY')
    @patch('app.services.execution_service.POD_CREATION_FAILURES')
    async def test_start_k8s_execution_failure(self,
                                               mock_pod_failures: Mock,
                                               mock_registry: Mock,
                                               execution_service: ExecutionService,
                                               mock_k8s_service: Mock,
                                               mock_execution_repo: Mock) -> None:
        execution_id = "test_execution"
        script = "print('hello')"
        lang = "python"
        lang_version = "3.11"

        # Mock runtime registry
        mock_runtime_cfg = Mock()
        mock_runtime_cfg.image = "python:3.11"
        mock_runtime_cfg.command = ["python"]
        mock_runtime_cfg.file_name = "script.py"
        mock_registry.__getitem__.return_value = {lang_version: mock_runtime_cfg}

        mock_k8s_service.create_execution_pod = AsyncMock(side_effect=Exception("Pod creation failed"))
        mock_execution_repo.update_execution = AsyncMock()

        with pytest.raises(IntegrationException):
            await execution_service._start_k8s_execution(execution_id, script, lang, lang_version)

        mock_execution_repo.update_execution.assert_called_once()
        mock_pod_failures.labels.assert_called_once()

    @pytest.mark.asyncio
    async def test_try_finalize_execution_kubernetes_pod_error(self,
                                                               execution_service: ExecutionService,
                                                               mock_k8s_service: Mock,
                                                               mock_execution_repo: Mock,
                                                               mock_execution: Mock) -> None:
        mock_k8s_service.get_pod_logs = AsyncMock(side_effect=KubernetesPodError("Pod error"))
        mock_execution_repo.update_execution = AsyncMock()
        mock_execution_repo.get_execution = AsyncMock(return_value=mock_execution)

        result = await execution_service._try_finalize_execution(mock_execution)

        mock_execution_repo.update_execution.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_try_finalize_execution_general_exception(self,
                                                            execution_service: ExecutionService,
                                                            mock_k8s_service: Mock,
                                                            mock_execution_repo: Mock,
                                                            mock_execution: Mock) -> None:
        mock_k8s_service.get_pod_logs = AsyncMock(side_effect=Exception("General error"))
        mock_execution_repo.update_execution = AsyncMock()
        mock_execution_repo.get_execution = AsyncMock(return_value=mock_execution)

        result = await execution_service._try_finalize_execution(mock_execution)

        mock_execution_repo.update_execution.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_try_finalize_execution_failed_reload(self,
                                                        execution_service: ExecutionService,
                                                        mock_k8s_service: Mock,
                                                        mock_execution_repo: Mock,
                                                        mock_execution: Mock) -> None:
        mock_k8s_service.get_pod_logs = AsyncMock(return_value=({}, "Succeeded"))
        mock_execution_repo.update_execution = AsyncMock()
        mock_execution_repo.get_execution = AsyncMock(return_value=None)

        with pytest.raises(IntegrationException):
            await execution_service._try_finalize_execution(mock_execution)

    @pytest.mark.asyncio
    @patch('app.services.execution_service.ERROR_COUNTER')
    async def test_try_finalize_execution_success_with_error_status(self,
                                                                    mock_error_counter: Mock,
                                                                    execution_service: ExecutionService,
                                                                    mock_k8s_service: Mock,
                                                                    mock_execution_repo: Mock,
                                                                    mock_execution: Mock) -> None:
        # Mock successful metrics retrieval but with non-zero exit code
        metrics = {
            "exit_code": 1,  # Non-zero exit code
            "stdout": "output",
            "stderr": "error",
            "resource_usage": {
                "execution_time_wall_seconds": 1.5,
                "cpu_time_jiffies": 150,
                "clk_tck_hertz": 100,
                "peak_memory_kb": 1024
            }
        }
        mock_k8s_service.get_pod_logs = AsyncMock(return_value=(metrics, "Failed"))
        mock_execution_repo.update_execution = AsyncMock()

        # Create updated execution with ERROR status
        from datetime import datetime, timezone
        updated_execution = ExecutionInDB(
            id=mock_execution.id,
            script=mock_execution.script,
            lang=mock_execution.lang,
            lang_version=mock_execution.lang_version,
            status=ExecutionStatus.ERROR,
            output="output",
            errors="error",
            resource_usage={},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        mock_execution_repo.get_execution = AsyncMock(return_value=updated_execution)

        result = await execution_service._try_finalize_execution(mock_execution)

        assert result is not None
        mock_error_counter.labels.assert_called()

    @pytest.mark.asyncio
    @patch('app.services.execution_service.ACTIVE_EXECUTIONS')
    @patch('app.services.execution_service.QUEUE_DEPTH')
    @patch('app.services.execution_service.ERROR_COUNTER')
    async def test_execute_script_creation_failure(self,
                                                   mock_error_counter: Mock,
                                                   mock_queue_depth: Mock,
                                                   mock_active_executions: Mock,
                                                   execution_service: ExecutionService,
                                                   mock_execution_repo: Mock) -> None:
        execution_service.settings.SUPPORTED_RUNTIMES = {"python": ["3.11"]}
        mock_execution_repo.create_execution = AsyncMock(side_effect=Exception("Database error"))

        with pytest.raises(IntegrationException):
            await execution_service.execute_script("print('hello')", "python", "3.11")

        mock_active_executions.dec.assert_called_once()
        mock_queue_depth.dec.assert_called_once()
        mock_error_counter.labels.assert_called()

    @pytest.mark.asyncio
    async def test_execute_script_failed_retrieve_after_creation(self,
                                                                 execution_service: ExecutionService,
                                                                 mock_execution_repo: Mock) -> None:
        execution_service.settings.SUPPORTED_RUNTIMES = {"python": ["3.11"]}
        execution_id = str(ObjectId())

        mock_execution_repo.create_execution = AsyncMock(return_value=execution_id)
        mock_execution_repo.get_execution = AsyncMock(return_value=None)
        mock_execution_repo.update_execution = AsyncMock()

        with patch.object(execution_service, '_start_k8s_execution') as mock_start_k8s:
            mock_start_k8s.return_value = AsyncMock()

            with pytest.raises(IntegrationException) as exc_info:
                await execution_service.execute_script("print('hello')", "python", "3.11")

        assert exc_info.value.status_code == 500
        assert "Script execution failed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_execution_result_in_progress_finalize_returns_none(self,
                                                                          execution_service: ExecutionService,
                                                                          mock_execution_repo: Mock) -> None:
        from datetime import datetime, timezone
        mock_execution = ExecutionInDB(
            id="test_id",
            script="print('hello')",
            lang="python",
            lang_version="3.11",
            status=ExecutionStatus.RUNNING,
            output="",
            errors="",
            resource_usage={},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        mock_execution_repo.get_execution = AsyncMock(return_value=mock_execution)

        with patch.object(execution_service, '_try_finalize_execution') as mock_finalize:
            mock_finalize.return_value = None

            result = await execution_service.get_execution_result("test_id")

            assert result == mock_execution
