import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pymongo.errors import DuplicateKeyError

from app.domain.idempotency import IdempotencyRecord, IdempotencyStats, IdempotencyStatus
from app.infrastructure.kafka.events.base import BaseEvent
from app.services.idempotency.idempotency_manager import (
    IdempotencyConfig,
    IdempotencyManager,
    IdempotencyKeyStrategy,
    IdempotencyResult,
    create_idempotency_manager,
)


pytestmark = pytest.mark.unit


class TestIdempotencyKeyStrategy:
    def test_event_based(self):
        event = MagicMock(spec=BaseEvent)
        event.event_type = "test.event"
        event.event_id = "event-123"

        key = IdempotencyKeyStrategy.event_based(event)
        assert key == "test.event:event-123"

    def test_content_hash_all_fields(self):
        event = MagicMock(spec=BaseEvent)
        event.model_dump.return_value = {
            "event_id": "123",
            "event_type": "test",
            "timestamp": "2025-01-01",
            "metadata": {},
            "field1": "value1",
            "field2": "value2"
        }

        key = IdempotencyKeyStrategy.content_hash(event)
        assert isinstance(key, str)
        assert len(key) == 64  # SHA256 hex digest length

    def test_content_hash_specific_fields(self):
        event = MagicMock(spec=BaseEvent)
        event.model_dump.return_value = {
            "event_id": "123",
            "event_type": "test",
            "field1": "value1",
            "field2": "value2",
            "field3": "value3"
        }

        key = IdempotencyKeyStrategy.content_hash(event, fields={"field1", "field3"})
        assert isinstance(key, str)
        assert len(key) == 64

    def test_custom(self):
        event = MagicMock(spec=BaseEvent)
        event.event_type = "test.event"

        key = IdempotencyKeyStrategy.custom(event, "custom-key-123")
        assert key == "test.event:custom-key-123"


class TestIdempotencyConfig:
    def test_default_config(self):
        config = IdempotencyConfig()
        assert config.key_prefix == "idempotency"
        assert config.default_ttl_seconds == 3600
        assert config.processing_timeout_seconds == 300
        assert config.enable_result_caching is True
        assert config.max_result_size_bytes == 1048576
        assert config.enable_metrics is True
        assert config.collection_name == "idempotency_keys"

    def test_custom_config(self):
        config = IdempotencyConfig(
            key_prefix="custom",
            default_ttl_seconds=7200,
            processing_timeout_seconds=600,
            enable_result_caching=False,
            max_result_size_bytes=2048,
            enable_metrics=False,
            collection_name="custom_keys"
        )
        assert config.key_prefix == "custom"
        assert config.default_ttl_seconds == 7200
        assert config.processing_timeout_seconds == 600
        assert config.enable_result_caching is False
        assert config.max_result_size_bytes == 2048
        assert config.enable_metrics is False
        assert config.collection_name == "custom_keys"


class TestIdempotencyManager:
    @pytest.fixture
    def mock_repo(self):
        return AsyncMock()

    @pytest.fixture
    def config(self):
        return IdempotencyConfig()

    @pytest.fixture
    def manager(self, config, mock_repo):
        with patch('app.services.idempotency.idempotency_manager.get_database_metrics') as mock_metrics:
            mock_metrics.return_value = MagicMock()
            return IdempotencyManager(config, mock_repo)

    @pytest.fixture
    def event(self):
        event = MagicMock(spec=BaseEvent)
        event.event_type = "test.event"
        event.event_id = "event-123"
        event.model_dump.return_value = {
            "event_id": "event-123",
            "event_type": "test.event",
            "field1": "value1"
        }
        return event

    @pytest.mark.asyncio
    async def test_initialize_with_metrics(self, manager):
        manager.config.enable_metrics = True

        with patch.object(manager, '_update_stats_loop', new_callable=AsyncMock) as mock_loop:
            await manager.initialize()

            assert manager._stats_update_task is not None

    @pytest.mark.asyncio
    async def test_initialize_without_metrics(self, manager):
        manager.config.enable_metrics = False

        await manager.initialize()

        assert manager._stats_update_task is None

    @pytest.mark.asyncio
    async def test_close_with_task(self, manager):
        # Create a real async task that can be cancelled
        async def dummy_task():
            await asyncio.sleep(100)

        real_task = asyncio.create_task(dummy_task())
        manager._stats_update_task = real_task

        await manager.close()

        # Task should be cancelled
        assert real_task.cancelled()

    @pytest.mark.asyncio
    async def test_close_without_task(self, manager):
        manager._stats_update_task = None

        await manager.close()
        # Should not raise

    def test_generate_key_event_based(self, manager, event):
        key = manager._generate_key(event, "event_based")
        assert key == "idempotency:test.event:event-123"

    def test_generate_key_content_hash(self, manager, event):
        key = manager._generate_key(event, "content_hash")
        assert key.startswith("idempotency:")
        assert len(key.split(":")[-1]) == 64  # SHA256 hash

    def test_generate_key_custom(self, manager, event):
        key = manager._generate_key(event, "custom", custom_key="my-key")
        assert key == "idempotency:test.event:my-key"

    def test_generate_key_invalid_strategy(self, manager, event):
        with pytest.raises(ValueError, match="Invalid key strategy"):
            manager._generate_key(event, "invalid")

    @pytest.mark.asyncio
    async def test_check_and_reserve_new_key(self, manager, mock_repo, event):
        mock_repo.find_by_key.return_value = None
        mock_repo.insert_processing.return_value = None

        result = await manager.check_and_reserve(event)

        assert result.is_duplicate is False
        assert result.status == IdempotencyStatus.PROCESSING
        mock_repo.insert_processing.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_and_reserve_existing_completed(self, manager, mock_repo, event):
        existing = IdempotencyRecord(
            key="test-key",
            status=IdempotencyStatus.COMPLETED,
            event_type="test.event",
            event_id="event-123",
            created_at=datetime.now(timezone.utc),
            ttl_seconds=3600,
            completed_at=datetime.now(timezone.utc),
            processing_duration_ms=100
        )
        mock_repo.find_by_key.return_value = existing

        result = await manager.check_and_reserve(event)

        assert result.is_duplicate is True
        assert result.status == IdempotencyStatus.COMPLETED
        manager.metrics.record_idempotency_duplicate_blocked.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_and_reserve_existing_processing_not_timeout(self, manager, mock_repo, event):
        existing = IdempotencyRecord(
            key="test-key",
            status=IdempotencyStatus.PROCESSING,
            event_type="test.event",
            event_id="event-123",
            created_at=datetime.now(timezone.utc),
            ttl_seconds=3600
        )
        mock_repo.find_by_key.return_value = existing

        result = await manager.check_and_reserve(event)

        assert result.is_duplicate is True
        assert result.status == IdempotencyStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_check_and_reserve_existing_processing_timeout(self, manager, mock_repo, event):
        old_time = datetime.now(timezone.utc) - timedelta(seconds=400)
        existing = IdempotencyRecord(
            key="test-key",
            status=IdempotencyStatus.PROCESSING,
            event_type="test.event",
            event_id="event-123",
            created_at=old_time,
            ttl_seconds=3600
        )
        mock_repo.find_by_key.return_value = existing
        mock_repo.update_record.return_value = 1

        result = await manager.check_and_reserve(event)

        assert result.is_duplicate is False
        assert result.status == IdempotencyStatus.PROCESSING
        mock_repo.update_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_and_reserve_duplicate_key_error(self, manager, mock_repo, event):
        mock_repo.find_by_key.side_effect = [None, IdempotencyRecord(
            key="test-key",
            status=IdempotencyStatus.PROCESSING,
            event_type="test.event",
            event_id="event-123",
            created_at=datetime.now(timezone.utc),
            ttl_seconds=3600
        )]
        mock_repo.insert_processing.side_effect = DuplicateKeyError("Duplicate key")

        result = await manager.check_and_reserve(event)

        assert result.is_duplicate is True

    @pytest.mark.asyncio
    async def test_check_and_reserve_duplicate_key_error_not_found(self, manager, mock_repo, event):
        mock_repo.find_by_key.return_value = None
        mock_repo.insert_processing.side_effect = DuplicateKeyError("Duplicate key")

        result = await manager.check_and_reserve(event)

        assert result.is_duplicate is False
        assert result.status == IdempotencyStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_mark_completed(self, manager, mock_repo, event):
        existing = IdempotencyRecord(
            key="test-key",
            status=IdempotencyStatus.PROCESSING,
            event_type="test.event",
            event_id="event-123",
            created_at=datetime.now(timezone.utc),
            ttl_seconds=3600
        )
        mock_repo.find_by_key.return_value = existing
        mock_repo.update_record.return_value = 1

        result = await manager.mark_completed(event)

        assert result is True
        mock_repo.update_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_completed_not_found(self, manager, mock_repo, event):
        mock_repo.find_by_key.return_value = None

        result = await manager.mark_completed(event)

        assert result is False

    @pytest.mark.asyncio
    async def test_mark_completed_exception(self, manager, mock_repo, event):
        mock_repo.find_by_key.side_effect = Exception("DB error")

        result = await manager.mark_completed(event)

        assert result is False

    @pytest.mark.asyncio
    async def test_mark_failed(self, manager, mock_repo, event):
        existing = IdempotencyRecord(
            key="test-key",
            status=IdempotencyStatus.PROCESSING,
            event_type="test.event",
            event_id="event-123",
            created_at=datetime.now(timezone.utc),
            ttl_seconds=3600
        )
        mock_repo.find_by_key.return_value = existing
        mock_repo.update_record.return_value = 1

        result = await manager.mark_failed(event, "Test error")

        assert result is True
        mock_repo.update_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_failed_not_found(self, manager, mock_repo, event):
        mock_repo.find_by_key.return_value = None

        result = await manager.mark_failed(event, "Test error")

        assert result is False

    @pytest.mark.asyncio
    async def test_mark_completed_with_json(self, manager, mock_repo, event):
        existing = IdempotencyRecord(
            key="test-key",
            status=IdempotencyStatus.PROCESSING,
            event_type="test.event",
            event_id="event-123",
            created_at=datetime.now(timezone.utc),
            ttl_seconds=3600
        )
        mock_repo.find_by_key.return_value = existing
        mock_repo.update_record.return_value = 1

        result = await manager.mark_completed_with_json(event, '{"result": "success"}')

        assert result is True
        mock_repo.update_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_completed_with_json_not_found(self, manager, mock_repo, event):
        mock_repo.find_by_key.return_value = None

        result = await manager.mark_completed_with_json(event, '{"result": "success"}')

        assert result is False

    @pytest.mark.asyncio
    async def test_update_key_status_with_large_result(self, manager, mock_repo):
        existing = IdempotencyRecord(
            key="test-key",
            status=IdempotencyStatus.PROCESSING,
            event_type="test.event",
            event_id="event-123",
            created_at=datetime.now(timezone.utc),
            ttl_seconds=3600
        )
        mock_repo.update_record.return_value = 1

        # Create a large result that exceeds max size
        large_result = "x" * (manager.config.max_result_size_bytes + 1)

        result = await manager._update_key_status(
            "test-key",
            existing,
            IdempotencyStatus.COMPLETED,
            cached_json=large_result
        )

        assert result is True
        # Result should not be cached due to size
        assert existing.result_json is None

    @pytest.mark.asyncio
    async def test_update_key_status_caching_disabled(self, manager, mock_repo):
        manager.config.enable_result_caching = False
        existing = IdempotencyRecord(
            key="test-key",
            status=IdempotencyStatus.PROCESSING,
            event_type="test.event",
            event_id="event-123",
            created_at=datetime.now(timezone.utc),
            ttl_seconds=3600
        )
        mock_repo.update_record.return_value = 1

        result = await manager._update_key_status(
            "test-key",
            existing,
            IdempotencyStatus.COMPLETED,
            cached_json='{"result": "success"}'
        )

        assert result is True
        # Result should not be cached when caching is disabled
        assert existing.result_json is None

    @pytest.mark.asyncio
    async def test_get_cached_json(self, manager, mock_repo, event):
        existing = IdempotencyRecord(
            key="test-key",
            status=IdempotencyStatus.COMPLETED,
            event_type="test.event",
            event_id="event-123",
            created_at=datetime.now(timezone.utc),
            ttl_seconds=3600,
            result_json='{"result": "success"}'
        )
        mock_repo.find_by_key.return_value = existing

        result = await manager.get_cached_json(event, "event_based", None)

        assert result == '{"result": "success"}'

    @pytest.mark.asyncio
    async def test_get_cached_json_not_found(self, manager, mock_repo, event):
        mock_repo.find_by_key.return_value = None

        with pytest.raises(AssertionError):
            await manager.get_cached_json(event, "event_based", None)

    @pytest.mark.asyncio
    async def test_remove(self, manager, mock_repo, event):
        mock_repo.delete_key.return_value = 1

        result = await manager.remove(event)

        assert result is True
        mock_repo.delete_key.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_not_found(self, manager, mock_repo, event):
        mock_repo.delete_key.return_value = 0

        result = await manager.remove(event)

        assert result is False

    @pytest.mark.asyncio
    async def test_remove_exception(self, manager, mock_repo, event):
        mock_repo.delete_key.side_effect = Exception("DB error")

        result = await manager.remove(event)

        assert result is False

    @pytest.mark.asyncio
    async def test_get_stats(self, manager, mock_repo):
        mock_repo.aggregate_status_counts.return_value = {
            IdempotencyStatus.PROCESSING: 5,
            IdempotencyStatus.COMPLETED: 10,
            IdempotencyStatus.FAILED: 2
        }

        stats = await manager.get_stats()

        assert stats.total_keys == 17
        assert stats.status_counts[IdempotencyStatus.PROCESSING] == 5
        assert stats.status_counts[IdempotencyStatus.COMPLETED] == 10
        assert stats.status_counts[IdempotencyStatus.FAILED] == 2
        assert stats.prefix == "idempotency"

    @pytest.mark.asyncio
    async def test_update_stats_loop(self, manager, mock_repo):
        mock_repo.aggregate_status_counts.return_value = {
            IdempotencyStatus.PROCESSING: 1,
            IdempotencyStatus.COMPLETED: 2,
            IdempotencyStatus.FAILED: 0
        }

        with patch('asyncio.sleep', side_effect=[asyncio.CancelledError]):
            try:
                await manager._update_stats_loop()
            except asyncio.CancelledError:
                pass

        manager.metrics.update_idempotency_keys_active.assert_called_with(3, "idempotency")

    @pytest.mark.asyncio
    async def test_update_stats_loop_exception(self, manager, mock_repo):
        mock_repo.aggregate_status_counts.side_effect = Exception("DB error")

        with patch('asyncio.sleep', side_effect=[300, asyncio.CancelledError]):
            try:
                await manager._update_stats_loop()
            except asyncio.CancelledError:
                pass

        # Should handle exception and continue

    def test_create_idempotency_manager(self, mock_repo):
        manager = create_idempotency_manager(repository=mock_repo)

        assert isinstance(manager, IdempotencyManager)
        assert manager.config.key_prefix == "idempotency"

    def test_create_idempotency_manager_with_config(self, mock_repo):
        config = IdempotencyConfig(key_prefix="custom")
        manager = create_idempotency_manager(repository=mock_repo, config=config)

        assert isinstance(manager, IdempotencyManager)
        assert manager.config.key_prefix == "custom"