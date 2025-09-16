import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.exceptions import ServiceError
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.kafka import GroupId, KafkaTopic
from app.domain.enums.storage import ExecutionErrorType, StorageType
from app.domain.execution.models import DomainExecution, ExecutionResultDomain, ResourceUsageDomain
from app.events.core import UnifiedProducer
from app.infrastructure.kafka.events.execution import (
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
)
from app.infrastructure.kafka.events.metadata import EventMetadata
# ResourceUsage is imported from ResourceUsageDomain
from app.services.idempotency import IdempotencyManager
from app.services.result_processor.processor import (
    ProcessingState,
    ResultProcessor,
    ResultProcessorConfig,
    run_result_processor,
)


pytestmark = pytest.mark.unit


class TestResultProcessorConfig:
    def test_default_values(self):
        config = ResultProcessorConfig()
        assert config.consumer_group == GroupId.RESULT_PROCESSOR
        assert KafkaTopic.EXECUTION_COMPLETED in config.topics
        assert KafkaTopic.EXECUTION_FAILED in config.topics
        assert KafkaTopic.EXECUTION_TIMEOUT in config.topics
        assert config.result_topic == KafkaTopic.EXECUTION_RESULTS
        assert config.batch_size == 10
        assert config.processing_timeout == 300

    def test_custom_values(self):
        config = ResultProcessorConfig(
            batch_size=20,
            processing_timeout=600
        )
        assert config.batch_size == 20
        assert config.processing_timeout == 600


class TestResultProcessor:
    @pytest.fixture
    def mock_execution_repo(self):
        return AsyncMock(spec=ExecutionRepository)

    @pytest.fixture
    def mock_producer(self):
        return AsyncMock(spec=UnifiedProducer)

    @pytest.fixture
    def mock_idempotency_manager(self):
        return AsyncMock(spec=IdempotencyManager)

    @pytest.fixture
    def processor(self, mock_execution_repo, mock_producer, mock_idempotency_manager):
        return ResultProcessor(
            execution_repo=mock_execution_repo,
            producer=mock_producer,
            idempotency_manager=mock_idempotency_manager
        )

    @pytest.mark.asyncio
    async def test_start_success(self, processor, mock_idempotency_manager):
        with patch.object(processor, '_create_dispatcher') as mock_create_dispatcher:
            with patch.object(processor, '_create_consumer') as mock_create_consumer:
                mock_create_dispatcher.return_value = MagicMock()
                mock_create_consumer.return_value = AsyncMock()

                await processor.start()

                assert processor._state == ProcessingState.PROCESSING
                mock_idempotency_manager.initialize.assert_awaited_once()
                mock_create_dispatcher.assert_called_once()
                mock_create_consumer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_already_processing(self, processor):
        processor._state = ProcessingState.PROCESSING
        await processor.start()
        # Should return early without doing anything

    @pytest.mark.asyncio
    async def test_stop(self, processor, mock_idempotency_manager, mock_producer):
        processor._state = ProcessingState.PROCESSING
        processor._consumer = AsyncMock()

        await processor.stop()

        assert processor._state == ProcessingState.STOPPED
        processor._consumer.stop.assert_awaited_once()
        mock_idempotency_manager.close.assert_awaited_once()
        mock_producer.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_already_stopped(self, processor):
        processor._state = ProcessingState.STOPPED
        await processor.stop()
        # Should return early

    def test_create_dispatcher(self, processor):
        dispatcher = processor._create_dispatcher()

        assert dispatcher is not None
        # Check handlers are registered
        assert EventType.EXECUTION_COMPLETED in dispatcher._handlers
        assert EventType.EXECUTION_FAILED in dispatcher._handlers
        assert EventType.EXECUTION_TIMEOUT in dispatcher._handlers

    @pytest.mark.asyncio
    async def test_create_consumer(self, processor):
        processor._dispatcher = MagicMock()

        with patch('app.services.result_processor.processor.get_settings') as mock_settings:
            with patch('app.services.result_processor.processor.UnifiedConsumer') as mock_consumer_class:
                with patch('app.services.result_processor.processor.IdempotentConsumerWrapper') as mock_wrapper_class:
                    mock_settings.return_value.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
                    mock_consumer = AsyncMock()
                    mock_consumer_class.return_value = mock_consumer
                    mock_wrapper = AsyncMock()
                    mock_wrapper_class.return_value = mock_wrapper

                    result = await processor._create_consumer()

                    assert result == mock_wrapper
                    mock_wrapper.start.assert_awaited_once_with(processor.config.topics)

    @pytest.mark.asyncio
    async def test_create_consumer_no_dispatcher(self, processor):
        processor._dispatcher = None

        with pytest.raises(RuntimeError, match="Event dispatcher not initialized"):
            await processor._create_consumer()

    @pytest.mark.asyncio
    async def test_handle_completed_wrapper(self, processor):
        event = ExecutionCompletedEvent(
            execution_id="exec1",
            exit_code=0,
            stdout="output",
            stderr="",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=1.0,
                cpu_time_jiffies=100,
                clk_tck_hertz=100,
                peak_memory_kb=1024
            ),
            metadata=EventMetadata(service_name="test", service_version="1.0")
        )

        with patch.object(processor, '_handle_completed') as mock_handle:
            await processor._handle_completed_wrapper(event)
            mock_handle.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_handle_failed_wrapper(self, processor):
        event = ExecutionFailedEvent(
            execution_id="exec1",
            exit_code=1,
            stdout="",
            stderr="error",
            error_type=ExecutionErrorType.SCRIPT_ERROR,
            error_message="Script failed with exit code 1",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=1.0,
                cpu_time_jiffies=100,
                clk_tck_hertz=100,
                peak_memory_kb=1024
            ),
            metadata=EventMetadata(service_name="test", service_version="1.0")
        )

        with patch.object(processor, '_handle_failed') as mock_handle:
            await processor._handle_failed_wrapper(event)
            mock_handle.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_handle_timeout_wrapper(self, processor):
        event = ExecutionTimeoutEvent(
            execution_id="exec1",
            timeout_seconds=30,
            stdout="partial output",
            stderr="",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=30.0,
                cpu_time_jiffies=3000,
                clk_tck_hertz=100,
                peak_memory_kb=2048
            ),
            metadata=EventMetadata(service_name="test", service_version="1.0")
        )

        with patch.object(processor, '_handle_timeout') as mock_handle:
            await processor._handle_timeout_wrapper(event)
            mock_handle.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_handle_completed_success(self, processor, mock_execution_repo, mock_producer):
        # Setup test data
        execution = DomainExecution(
            execution_id="exec1",
            user_id="user1",
            script="print('hello')",
            lang="python",
            lang_version="3.11",
            status=ExecutionStatus.RUNNING
        )
        mock_execution_repo.get_execution.return_value = execution

        event = ExecutionCompletedEvent(
            execution_id="exec1",
            exit_code=0,
            stdout="hello",
            stderr="",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=1.0,
                cpu_time_jiffies=100,
                clk_tck_hertz=100,
                peak_memory_kb=1024
            ),
            metadata=EventMetadata(service_name="test", service_version="1.0")
        )

        with patch('app.services.result_processor.processor.get_settings') as mock_settings:
            mock_settings.return_value.K8S_POD_MEMORY_LIMIT = "128Mi"

            await processor._handle_completed(event)

            # Verify repository called
            mock_execution_repo.get_execution.assert_awaited_once_with("exec1")
            mock_execution_repo.write_terminal_result.assert_awaited_once()

            # Verify result stored event published
            mock_producer.produce.assert_awaited()

    @pytest.mark.asyncio
    async def test_handle_completed_execution_not_found(self, processor, mock_execution_repo):
        mock_execution_repo.get_execution.return_value = None

        event = ExecutionCompletedEvent(
            execution_id="exec1",
            exit_code=0,
            stdout="hello",
            stderr="",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=1.0,
                cpu_time_jiffies=100,
                clk_tck_hertz=100,
                peak_memory_kb=1024
            ),
            metadata=EventMetadata(service_name="test", service_version="1.0")
        )

        with pytest.raises(ServiceError, match="Execution exec1 not found"):
            await processor._handle_completed(event)

    @pytest.mark.asyncio
    async def test_handle_completed_write_failure(self, processor, mock_execution_repo, mock_producer):
        execution = DomainExecution(
            execution_id="exec1",
            user_id="user1",
            script="print('hello')",
            lang="python",
            lang_version="3.11",
            status=ExecutionStatus.RUNNING
        )
        mock_execution_repo.get_execution.return_value = execution
        mock_execution_repo.write_terminal_result.side_effect = Exception("DB error")

        event = ExecutionCompletedEvent(
            execution_id="exec1",
            exit_code=0,
            stdout="hello",
            stderr="",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=1.0,
                cpu_time_jiffies=100,
                clk_tck_hertz=100,
                peak_memory_kb=1024
            ),
            metadata=EventMetadata(service_name="test", service_version="1.0")
        )

        with patch('app.services.result_processor.processor.get_settings') as mock_settings:
            mock_settings.return_value.K8S_POD_MEMORY_LIMIT = "128Mi"

            await processor._handle_completed(event)

            # Should publish result failed event
            calls = mock_producer.produce.await_args_list
            assert len(calls) == 1
            assert "ResultFailedEvent" in str(calls[0])

    @pytest.mark.asyncio
    async def test_handle_failed_success(self, processor, mock_execution_repo, mock_producer):
        execution = DomainExecution(
            execution_id="exec1",
            user_id="user1",
            script="print('hello')",
            lang="python",
            lang_version="3.11",
            status=ExecutionStatus.RUNNING
        )
        mock_execution_repo.get_execution.return_value = execution

        event = ExecutionFailedEvent(
            execution_id="exec1",
            exit_code=1,
            stdout="",
            stderr="error",
            error_type=ExecutionErrorType.SCRIPT_ERROR,
            error_message="Script error occurred",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=1.0,
                cpu_time_jiffies=100,
                clk_tck_hertz=100,
                peak_memory_kb=1024
            ),
            metadata=EventMetadata(service_name="test", service_version="1.0")
        )

        await processor._handle_failed(event)

        mock_execution_repo.get_execution.assert_awaited_once_with("exec1")
        mock_execution_repo.write_terminal_result.assert_awaited_once()
        mock_producer.produce.assert_awaited()

    @pytest.mark.asyncio
    async def test_handle_failed_execution_not_found(self, processor, mock_execution_repo):
        mock_execution_repo.get_execution.return_value = None

        event = ExecutionFailedEvent(
            execution_id="exec1",
            exit_code=1,
            stdout="",
            stderr="error",
            error_type=ExecutionErrorType.SCRIPT_ERROR,
            error_message="Script error occurred",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=1.0,
                cpu_time_jiffies=100,
                clk_tck_hertz=100,
                peak_memory_kb=1024
            ),
            metadata=EventMetadata(service_name="test", service_version="1.0")
        )

        with pytest.raises(ServiceError, match="Execution exec1 not found"):
            await processor._handle_failed(event)

    @pytest.mark.asyncio
    async def test_handle_failed_write_failure(self, processor, mock_execution_repo, mock_producer):
        execution = DomainExecution(
            execution_id="exec1",
            user_id="user1",
            script="print('hello')",
            lang="python",
            lang_version="3.11",
            status=ExecutionStatus.RUNNING
        )
        mock_execution_repo.get_execution.return_value = execution
        mock_execution_repo.write_terminal_result.side_effect = Exception("DB error")

        event = ExecutionFailedEvent(
            execution_id="exec1",
            exit_code=1,
            stdout="",
            stderr="error",
            error_type=ExecutionErrorType.SCRIPT_ERROR,
            error_message="Script error occurred",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=1.0,
                cpu_time_jiffies=100,
                clk_tck_hertz=100,
                peak_memory_kb=1024
            ),
            metadata=EventMetadata(service_name="test", service_version="1.0")
        )

        await processor._handle_failed(event)

        # Should publish result failed event
        calls = mock_producer.produce.await_args_list
        assert len(calls) == 1
        assert "ResultFailedEvent" in str(calls[0])

    @pytest.mark.asyncio
    async def test_handle_timeout_success(self, processor, mock_execution_repo, mock_producer):
        execution = DomainExecution(
            execution_id="exec1",
            user_id="user1",
            script="print('hello')",
            lang="python",
            lang_version="3.11",
            status=ExecutionStatus.RUNNING
        )
        mock_execution_repo.get_execution.return_value = execution

        event = ExecutionTimeoutEvent(
            execution_id="exec1",
            timeout_seconds=30,
            stdout="partial",
            stderr="",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=30.0,
                cpu_time_jiffies=3000,
                clk_tck_hertz=100,
                peak_memory_kb=2048
            ),
            metadata=EventMetadata(service_name="test", service_version="1.0")
        )

        await processor._handle_timeout(event)

        mock_execution_repo.get_execution.assert_awaited_once_with("exec1")
        mock_execution_repo.write_terminal_result.assert_awaited_once()
        mock_producer.produce.assert_awaited()

    @pytest.mark.asyncio
    async def test_handle_timeout_execution_not_found(self, processor, mock_execution_repo):
        mock_execution_repo.get_execution.return_value = None

        event = ExecutionTimeoutEvent(
            execution_id="exec1",
            timeout_seconds=30,
            stdout="partial",
            stderr="",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=30.0,
                cpu_time_jiffies=3000,
                clk_tck_hertz=100,
                peak_memory_kb=2048
            ),
            metadata=EventMetadata(service_name="test", service_version="1.0")
        )

        with pytest.raises(ServiceError, match="Execution exec1 not found"):
            await processor._handle_timeout(event)

    @pytest.mark.asyncio
    async def test_handle_timeout_write_failure(self, processor, mock_execution_repo, mock_producer):
        execution = DomainExecution(
            execution_id="exec1",
            user_id="user1",
            script="print('hello')",
            lang="python",
            lang_version="3.11",
            status=ExecutionStatus.RUNNING
        )
        mock_execution_repo.get_execution.return_value = execution
        mock_execution_repo.write_terminal_result.side_effect = Exception("DB error")

        event = ExecutionTimeoutEvent(
            execution_id="exec1",
            timeout_seconds=30,
            stdout="partial",
            stderr="",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=30.0,
                cpu_time_jiffies=3000,
                clk_tck_hertz=100,
                peak_memory_kb=2048
            ),
            metadata=EventMetadata(service_name="test", service_version="1.0")
        )

        await processor._handle_timeout(event)

        # Should publish result failed event
        calls = mock_producer.produce.await_args_list
        assert len(calls) == 1
        assert "ResultFailedEvent" in str(calls[0])

    @pytest.mark.asyncio
    async def test_publish_result_stored(self, processor, mock_producer):
        result = ExecutionResultDomain(
            execution_id="exec1",
            status=ExecutionStatus.COMPLETED,
            exit_code=0,
            stdout="hello world",
            stderr="warning",
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=1.0,
                cpu_time_jiffies=100,
                clk_tck_hertz=100,
                peak_memory_kb=1024
            ),
            metadata={}
        )

        await processor._publish_result_stored(result)

        mock_producer.produce.assert_awaited_once()
        call_args = mock_producer.produce.await_args
        assert call_args.kwargs['key'] == "exec1"
        event = call_args.kwargs['event_to_produce']
        assert event.execution_id == "exec1"
        assert event.storage_type == StorageType.DATABASE
        assert event.size_bytes == len("hello world") + len("warning")

    @pytest.mark.asyncio
    async def test_publish_result_failed(self, processor, mock_producer):
        await processor._publish_result_failed("exec1", "Something went wrong")

        mock_producer.produce.assert_awaited_once()
        call_args = mock_producer.produce.await_args
        assert call_args.kwargs['key'] == "exec1"
        event = call_args.kwargs['event_to_produce']
        assert event.execution_id == "exec1"
        assert event.error == "Something went wrong"

    @pytest.mark.asyncio
    async def test_get_status(self, processor):
        processor._state = ProcessingState.PROCESSING
        processor._consumer = MagicMock()

        status = await processor.get_status()

        assert status['state'] == "processing"
        assert status['consumer_active'] is True

    @pytest.mark.asyncio
    async def test_get_status_idle(self, processor):
        status = await processor.get_status()

        assert status['state'] == "idle"
        assert status['consumer_active'] is False


@pytest.mark.asyncio
async def test_run_result_processor():
    with patch('app.services.result_processor.processor.create_result_processor_container') as mock_container:
        with patch('app.services.result_processor.processor.ResultProcessor') as mock_processor_class:
            # Setup mocks
            container = AsyncMock()
            container.get.side_effect = [
                AsyncMock(spec=UnifiedProducer),  # producer
                AsyncMock(spec=IdempotencyManager),  # idempotency_manager
                AsyncMock(spec=ExecutionRepository),  # execution_repo
            ]
            mock_container.return_value = container

            processor = AsyncMock()
            processor.get_status.return_value = {"state": "PROCESSING"}
            mock_processor_class.return_value = processor

            # Run briefly then cancel
            task = asyncio.create_task(run_result_processor())
            await asyncio.sleep(0.1)
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

            # Verify calls
            processor.start.assert_awaited_once()
            processor.stop.assert_awaited_once()
            container.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_result_processor_exception():
    with patch('app.services.result_processor.processor.create_result_processor_container') as mock_container:
        # Setup container to raise exception
        container = AsyncMock()
        container.get.side_effect = Exception("Container error")
        mock_container.return_value = container

        # Run and expect it to handle exception
        with pytest.raises(Exception, match="Container error"):
            await run_result_processor()

        container.close.assert_awaited_once()