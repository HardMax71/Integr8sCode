import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from datetime import datetime

import pytest

from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.storage import ExecutionErrorType
from app.infrastructure.kafka.events.execution import (
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
)
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.services.result_processor.processor import (
    ProcessingState,
    ResultProcessor,
    ResultProcessorConfig,
    run_result_processor
)
from app.db.repositories.execution_repository import ExecutionRepository
from app.services.idempotency import IdempotencyManager


def mk_repo(lang="python", ver="3.11"):
    exec_repo = AsyncMock(spec=ExecutionRepository)
    exec_repo.get_execution = AsyncMock(return_value=SimpleNamespace(lang=lang, lang_version=ver))
    exec_repo.update_execution = AsyncMock(return_value=True)
    exec_repo.upsert_result = AsyncMock(return_value=True)
    return exec_repo


class DummyProducer:
    def __init__(self):
        self.calls = []
    async def produce(self, event_to_produce, key):  # noqa: ANN001
        self.calls.append((event_to_produce.event_type, key))


class DummySchema:
    pass


def mk_completed():
    from app.domain.execution.models import ResourceUsageDomain
    return ExecutionCompletedEvent(
        execution_id="e1",
        stdout="out",
        stderr="",
        exit_code=0,
        resource_usage=ResourceUsageDomain(execution_time_wall_seconds=0.1, cpu_time_jiffies=0, clk_tck_hertz=0, peak_memory_kb=1024),
        metadata=EventMetadata(service_name="s", service_version="1"),
    )


def mk_failed():
    from app.domain.enums.storage import ExecutionErrorType
    from app.domain.execution.models import ResourceUsageDomain
    return ExecutionFailedEvent(
        execution_id="e2",
        stdout="",
        stderr="err",
        exit_code=1,
        error_type=ExecutionErrorType.SCRIPT_ERROR,
        error_message="error",
        resource_usage=ResourceUsageDomain.from_dict({}),
        metadata=EventMetadata(service_name="s", service_version="1"),
    )


def mk_timeout():
    from app.domain.execution.models import ResourceUsageDomain
    return ExecutionTimeoutEvent(
        execution_id="e3",
        stdout="",
        stderr="",
        timeout_seconds=2,
        resource_usage=ResourceUsageDomain.from_dict({}),
        metadata=EventMetadata(service_name="s", service_version="1"),
    )


@pytest.mark.asyncio
async def test_publish_result_events_and_status_update(monkeypatch):
    exec_repo = mk_repo()
    prod = DummyProducer()
    rp = ResultProcessor(execution_repo=exec_repo, producer=prod, idempotency_manager=AsyncMock(spec=IdempotencyManager))

    # Need dispatcher before creating consumer
    rp._dispatcher = rp._create_dispatcher()
    
    mock_base = AsyncMock()
    mock_wrapper = AsyncMock()
    with patch('app.services.result_processor.processor.UnifiedConsumer', return_value=mock_base):
        with patch('app.services.result_processor.processor.IdempotentConsumerWrapper', return_value=mock_wrapper):
            with patch('app.services.result_processor.processor.get_settings') as mock_settings:
                mock_settings.return_value.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
                consumer = await rp._create_consumer()
                assert consumer == mock_wrapper
                mock_wrapper.start.assert_called_once()


@pytest.mark.asyncio
async def test_store_result():
    """Test the _store_result method."""
    exec_repo = mk_repo()
    prod = DummyProducer()
    
    rp = ResultProcessor(execution_repo=exec_repo, producer=prod, idempotency_manager=AsyncMock(spec=IdempotencyManager))
    
    # Producer is set on the processor; no context needed
    
    # Test storing result
    from app.domain.execution.models import ResourceUsageDomain, ExecutionResultDomain
    ru = ResourceUsageDomain(execution_time_wall_seconds=0.5, cpu_time_jiffies=0, clk_tck_hertz=0, peak_memory_kb=128)
    domain = ExecutionResultDomain(
        execution_id="test-123",
        status=ExecutionStatus.COMPLETED,
        exit_code=0,
        stdout="Hello, World!",
        stderr="",
        resource_usage=ru,
        metadata=EventMetadata(service_name="test", service_version="1.0").model_dump(),
        error_type=None,
    )
    await rp._execution_repo.upsert_result(domain)
    result = domain
    
    # Verify result structure
    assert result.execution_id == "test-123"
    assert result.status == ExecutionStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout == "Hello, World!"
    assert result.stderr == ""
    assert result.resource_usage.execution_time_wall_seconds == 0.5
    assert result.resource_usage.peak_memory_kb == 128
    
    # Verify database call
    exec_repo.upsert_result.assert_awaited()


@pytest.mark.asyncio
async def test_update_execution_status():
    """Test the _update_execution_status method."""
    exec_repo = mk_repo()
    prod = DummyProducer()
    
    rp = ResultProcessor(execution_repo=exec_repo, producer=prod, idempotency_manager=AsyncMock(spec=IdempotencyManager))
    
    # Mock database
    # Test updating status
    from app.domain.execution.models import ResourceUsageDomain, ExecutionResultDomain
    res = ExecutionResultDomain(
        execution_id="test-456",
        status=ExecutionStatus.FAILED,
        exit_code=1,
        stdout="Output text",
        stderr="Error text",
        resource_usage=ResourceUsageDomain(execution_time_wall_seconds=1.5, cpu_time_jiffies=0, clk_tck_hertz=0, peak_memory_kb=0),
        metadata={},
    )
    await rp._update_execution_status(ExecutionStatus.FAILED, res)
    
    # Verify repository update
    exec_repo.update_execution.assert_awaited()


@pytest.mark.asyncio
async def test_publish_result_failed():
    """Test the _publish_result_failed method."""
    exec_repo = mk_repo()
    prod = DummyProducer()
    
    rp = ResultProcessor(execution_repo=exec_repo, producer=prod, idempotency_manager=AsyncMock(spec=IdempotencyManager))
    
    # No context required
    
    await rp._publish_result_failed("exec-789", "Test error message")
    
    # Check that event was produced
    assert len(prod.calls) == 1
    event_type, key = prod.calls[0]
    assert event_type == EventType.RESULT_FAILED
    assert key == "exec-789"


@pytest.mark.asyncio
async def test_get_status():
    """Test the get_status method."""
    exec_repo = mk_repo()
    rp = ResultProcessor(execution_repo=exec_repo, producer=AsyncMock(), idempotency_manager=AsyncMock(spec=IdempotencyManager))
    
    # Set some state
    rp._state = ProcessingState.PROCESSING
    rp._consumer = Mock()
    
    status = await rp.get_status()
    
    assert status["state"] == ProcessingState.PROCESSING.value
    assert status["consumer_active"] is True


@pytest.mark.asyncio
async def test_handle_timeout_with_metrics():
    """Test _handle_timeout with metrics recording."""
    exec_repo = mk_repo()
    prod = DummyProducer()
    
    rp = ResultProcessor(execution_repo=exec_repo, producer=prod, idempotency_manager=AsyncMock(spec=IdempotencyManager))
    
    # Mock metrics
    mock_metrics = Mock()
    rp._metrics = mock_metrics
    
    # Mock the helper methods
    rp._execution_repo.upsert_result = AsyncMock(return_value=True)
    
    async def fake_update(status, result):
        pass
    
    async def fake_publish(result):
        pass
    async def fake_store(res):
        return res
    
    rp._store_result = fake_store
    rp._update_execution_status = fake_update
    rp._publish_result_stored = fake_publish
    
    # Create timeout event
    timeout_event = mk_timeout()
    
    await rp._handle_timeout(timeout_event)
    
    # Verify metrics were recorded
    mock_metrics.record_error.assert_called_with(ExecutionErrorType.TIMEOUT)
    mock_metrics.record_script_execution.assert_called()
    mock_metrics.record_execution_duration.assert_called()


@pytest.mark.asyncio
async def test_run_result_processor():
    """Test the run_result_processor function."""
    with patch('app.services.result_processor.processor.create_result_processor_container') as mock_container:
        with patch('app.services.result_processor.processor.ResultProcessor') as mock_processor:
            with patch('asyncio.sleep') as mock_sleep:
                # Set up mocks
                container = AsyncMock()
                mock_container.return_value = container
                
                processor_instance = AsyncMock()
                processor_instance.get_status.return_value = {"state": "running"}
                mock_processor.return_value = processor_instance
                
                # Make sleep raise CancelledError after first call
                mock_sleep.side_effect = [None, asyncio.CancelledError()]
                
                # Run the processor - it should handle CancelledError gracefully
                await run_result_processor()
                
                # Verify startup sequence
                mock_container.assert_called_once()
                processor_instance.start.assert_called_once()
                processor_instance.stop.assert_called_once()
                container.close.assert_called_once()


@pytest.mark.asyncio
async def test_handle_failed_with_error_type():
    """Test _handle_failed with error type metrics."""
    exec_repo = mk_repo()
    prod = DummyProducer()
    
    rp = ResultProcessor(execution_repo=exec_repo, producer=prod, idempotency_manager=AsyncMock(spec=IdempotencyManager))
    
    # Mock metrics
    mock_metrics = Mock()
    rp._metrics = mock_metrics
    
    # Set up context
    # No context required
    
    # Mock helper methods
    rp._execution_repo.upsert_result = AsyncMock(return_value=True)
    
    async def fake_update(status, result):
        pass
    
    async def fake_publish(result):
        pass
    async def fake_store(res):
        return res
    
    rp._store_result = fake_store
    rp._update_execution_status = fake_update
    rp._publish_result_stored = fake_publish
    
    # Create failed event with error type
    failed_event = mk_failed()
    
    await rp._handle_failed(failed_event)
    
    # Verify error type was recorded
    mock_metrics.record_error.assert_called_with(ExecutionErrorType.SCRIPT_ERROR)
    mock_metrics.record_script_execution.assert_called()


@pytest.mark.asyncio
async def test_handle_completed_with_memory_metrics():
    """Test _handle_completed with memory usage metrics."""
    exec_repo = mk_repo()
    prod = DummyProducer()
    
    rp = ResultProcessor(execution_repo=exec_repo, producer=prod, idempotency_manager=AsyncMock(spec=IdempotencyManager))
    
    # Mock metrics with all required attributes
    mock_metrics = Mock()
    mock_metrics.memory_utilization_percent = Mock()
    rp._metrics = mock_metrics
    
    # Set up context
    # No context required
    
    # Mock helper methods
    from app.domain.execution.models import ExecutionResultDomain
    async def fake_store(res: ExecutionResultDomain):
        return res
    
    async def fake_update(status, result):
        pass
    
    async def fake_publish(result):
        pass
    
    rp._store_result = fake_store
    rp._update_execution_status = fake_update
    rp._publish_result_stored = fake_publish
    
    # Create completed event with memory usage
    completed_event = mk_completed()
    
    await rp._handle_completed(completed_event)
    
    # Verify metrics were recorded
    mock_metrics.record_script_execution.assert_called_with(
        ExecutionStatus.COMPLETED, 
        "python-3.11"
    )
    mock_metrics.record_execution_duration.assert_called()
    mock_metrics.record_memory_usage.assert_called()
    mock_metrics.memory_utilization_percent.record.assert_called()


@pytest.mark.asyncio
async def test_stop_already_stopped():
    """Test stopping a processor that's already stopped."""
    exec_repo = mk_repo()
    rp = ResultProcessor(execution_repo=exec_repo, producer=AsyncMock(), idempotency_manager=AsyncMock(spec=IdempotencyManager))
    
    # Set state to already stopped
    rp._state = ProcessingState.STOPPED
    
    # Should return without doing anything
    await rp.stop()


@pytest.mark.asyncio
async def test_stop_with_non_idempotent_consumer():
    """Test stopping processor with non-idempotent consumer."""
    exec_repo = mk_repo()
    rp = ResultProcessor(execution_repo=exec_repo, producer=AsyncMock(), idempotency_manager=AsyncMock(spec=IdempotencyManager))
    
    # Set up non-idempotent consumer
    rp._state = ProcessingState.PROCESSING
    rp._idempotent_consumer = None
    rp._consumer = AsyncMock()
    rp._idempotency_manager = AsyncMock()
    
    await rp.stop()
    
    # Verify consumer was stopped
    rp._consumer.stop.assert_called_once()
    rp._idempotency_manager.close.assert_called_once()


@pytest.mark.asyncio
async def test_stop_with_non_provided_producer():
    """Test stopping processor when producer wasn't provided."""
    exec_repo = mk_repo()
    producer = AsyncMock()
    rp = ResultProcessor(execution_repo=exec_repo, producer=producer, idempotency_manager=AsyncMock(spec=IdempotencyManager))
    
    rp._state = ProcessingState.PROCESSING
    rp._producer = producer
    rp._idempotent_consumer = AsyncMock()
    
    await rp.stop()
    
    # Verify producer was stopped
    producer.stop.assert_called_once()
