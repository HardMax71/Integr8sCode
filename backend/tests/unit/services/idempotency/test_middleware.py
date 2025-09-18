import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.infrastructure.kafka.events.base import BaseEvent
from app.services.idempotency.idempotency_manager import IdempotencyManager, IdempotencyResult
from app.services.idempotency.middleware import (
    IdempotentEventHandler,
    idempotent_handler,
    IdempotentConsumerWrapper,
)
from app.domain.idempotency import IdempotencyStatus
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic


pytestmark = pytest.mark.unit


class TestIdempotentEventHandler:
    @pytest.fixture
    def mock_idempotency_manager(self):
        return AsyncMock(spec=IdempotencyManager)

    @pytest.fixture
    def mock_handler(self):
        handler = AsyncMock()
        handler.__name__ = "test_handler"
        return handler

    @pytest.fixture
    def event(self):
        event = MagicMock(spec=BaseEvent)
        event.event_type = "test.event"
        event.event_id = "event-123"
        return event

    @pytest.fixture
    def idempotent_event_handler(self, mock_handler, mock_idempotency_manager):
        return IdempotentEventHandler(
            handler=mock_handler,
            idempotency_manager=mock_idempotency_manager,
            key_strategy="event_based",
            ttl_seconds=3600,
            cache_result=True
        )

    @pytest.mark.asyncio
    async def test_call_with_fields(self, mock_handler, mock_idempotency_manager, event):
        # Setup with specific fields
        fields = {"field1", "field2"}

        handler = IdempotentEventHandler(
            handler=mock_handler,
            idempotency_manager=mock_idempotency_manager,
            key_strategy="content_hash",
            fields=fields
        )

        idempotency_result = IdempotencyResult(
            is_duplicate=False,
            status=IdempotencyStatus.PROCESSING,
            created_at=MagicMock(),
            key="test-key"
        )
        mock_idempotency_manager.check_and_reserve.return_value = idempotency_result

        # Execute
        await handler(event)

        # Verify
        mock_idempotency_manager.check_and_reserve.assert_called_once_with(
            event=event,
            key_strategy="content_hash",
            custom_key=None,
            ttl_seconds=None,
            fields=fields
        )

    @pytest.mark.asyncio
    async def test_call_handler_exception(self, idempotent_event_handler, mock_idempotency_manager, mock_handler, event):
        # Setup: Handler raises exception
        idempotency_result = IdempotencyResult(
            is_duplicate=False,
            status=IdempotencyStatus.PROCESSING,
            created_at=MagicMock(),
            key="test-key"
        )
        mock_idempotency_manager.check_and_reserve.return_value = idempotency_result
        mock_handler.side_effect = Exception("Handler error")

        # Execute and verify exception is raised
        with pytest.raises(Exception, match="Handler error"):
            await idempotent_event_handler(event)

        # Verify failure is marked
        mock_idempotency_manager.mark_failed.assert_called_once_with(
            event=event,
            error="Handler error",
            key_strategy="event_based",
            custom_key=None,
            fields=None
        )

    # Duplicate handler and custom key behavior covered by integration tests


class TestIdempotentHandlerDecorator:
    pass

class TestIdempotentConsumerWrapper:
    pass
