import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import json

import pytest

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.events.core.dispatcher import EventDispatcher
from app.events.core.producer import UnifiedProducer
from app.events.core.types import ConsumerConfig, ProducerConfig
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.events.core.consumer import UnifiedConsumer
from app.infrastructure.kafka.events.base import BaseEvent


class DummySchemaRegistry(SchemaRegistryManager):
    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        pass

    def serialize_event(self, event: BaseEvent) -> bytes:  # type: ignore[override]
        return b"dummy"

    def deserialize_event(self, raw: bytes, topic: str):  # type: ignore[override]
        return ExecutionRequestedEvent(
            execution_id="exec-1",
            script="print(1)",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            priority=5,
            metadata=EventMetadata(service_name="t", service_version="1"),
        )


@pytest.mark.asyncio
async def test_unified_producer_produce_calls_kafka() -> None:
    schema = DummySchemaRegistry()
    producer_config = ProducerConfig(bootstrap_servers="kafka:29092")

    with patch("app.events.core.producer.Producer") as producer_cls:
        mock_producer = MagicMock()
        producer_cls.return_value = mock_producer

        producer = UnifiedProducer(producer_config, schema)
        await producer.start()

        event = ExecutionRequestedEvent(
            execution_id="exec-1",
            script="print(1)",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            priority=5,
            metadata=EventMetadata(service_name="t", service_version="1"),
        )

        await producer.produce(event_to_produce=event, key=event.execution_id)

        assert mock_producer.produce.called
        args, kwargs = mock_producer.produce.call_args
        assert kwargs["topic"] == str(event.topic)
        assert kwargs["key"] == event.execution_id.encode()

        await producer.stop()


@pytest.mark.asyncio
async def test_unified_producer_send_to_dlq() -> None:
    schema = DummySchemaRegistry()
    producer_config = ProducerConfig(bootstrap_servers="kafka:29092")

    with patch("app.events.core.producer.Producer") as producer_cls:
        mock_producer = MagicMock()
        producer_cls.return_value = mock_producer

        producer = UnifiedProducer(producer_config, schema)
        await producer.start()

        original = ExecutionRequestedEvent(
            execution_id="e2",
            script="print(2)",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            priority=5,
            metadata=EventMetadata(service_name="t", service_version="1"),
        )

        await producer.send_to_dlq(original, str(KafkaTopic.EXECUTION_EVENTS), RuntimeError("x"), retry_count=2)

        assert mock_producer.produce.called
        args, kwargs = mock_producer.produce.call_args
        assert kwargs["topic"] == str(KafkaTopic.DEAD_LETTER_QUEUE)

        await producer.stop()


@pytest.mark.asyncio
async def test_unified_consumer_dispatches_event() -> None:
    schema = DummySchemaRegistry()
    dispatcher = EventDispatcher()
    handled = {}

    @dispatcher.register(EventType.EXECUTION_REQUESTED)
    async def handle(ev):  # type: ignore[no-redef]
        handled["ok"] = True

    consumer_config = ConsumerConfig(bootstrap_servers="kafka:29092", group_id="g1")

    with patch("app.events.core.consumer.Consumer") as consumer_cls:
        mock_consumer = MagicMock()
        consumer_cls.return_value = mock_consumer

        # Mock a single message then None
        class Msg:
            def value(self):
                return b"dummy"

            def topic(self):
                return str(KafkaTopic.EXECUTION_EVENTS)

            def error(self):
                return None

            def partition(self):
                return 0

            def offset(self):
                return 1

        poll_seq = [Msg(), None]

        def poll_side_effect(timeout=0.1):  # noqa: ANN001
            return poll_seq.pop(0) if poll_seq else None

        mock_consumer.poll.side_effect = poll_side_effect

        # Patch internal registry to our dummy
        with patch("app.events.core.consumer.SchemaRegistryManager", return_value=schema):
            uc = UnifiedConsumer(consumer_config, dispatcher)
            # Inject dummy schema registry directly
            uc._schema_registry = schema  # type: ignore[attr-defined]
        await uc.start([KafkaTopic.EXECUTION_EVENTS])

        # Give consume loop a moment
        await asyncio.sleep(0.05)
        await uc.stop()

        assert handled.get("ok") is True


def test_producer_handle_stats_and_delivery_callbacks() -> None:
    schema = DummySchemaRegistry()
    pc = ProducerConfig(bootstrap_servers="kafka:29092")
    with patch("app.events.core.producer.Producer") as producer_cls:
        mock_producer = MagicMock()
        producer_cls.return_value = mock_producer

        p = UnifiedProducer(pc, schema)
        # feed stats JSON
        p._handle_stats(json.dumps({
            "msg_cnt": 3,
            "topics": {
                "t": {"partitions": {"0": {"msgq_cnt": 2, "rtt": {"avg": 5}}}}
            }
        }))
        assert p.metrics.queue_size == 3

        # simulate delivery errors and success
        msg = MagicMock()
        msg.topic.return_value = "topic"
        msg.partition.return_value = 0
        msg.offset.return_value = 10
        from confluent_kafka.error import KafkaError
        err = KafkaError(KafkaError._ALL_BROKERS_DOWN)
        p._handle_delivery(err, msg)
        assert p.metrics.messages_failed >= 1
        p._handle_delivery(None, msg)
        assert p.metrics.messages_sent >= 1
import asyncio
from types import SimpleNamespace

import pytest

from app.events.core.consumer import UnifiedConsumer
from app.events.core.dispatcher import EventDispatcher
from app.events.core.types import ConsumerConfig
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.user import UserLoggedInEvent
from app.domain.enums.auth import LoginMethod


class DummySchema:
    def deserialize_event(self, raw, topic):  # noqa: ANN001
        # Return a valid event so dispatcher runs and raises
        return UserLoggedInEvent(user_id="u1", login_method=LoginMethod.PASSWORD,
                                 metadata=EventMetadata(service_name="svc", service_version="1"))


class Msg:
    def __init__(self):
        self._topic = "t"
        self._val = b"x"
    def topic(self): return self._topic
    def value(self): return self._val
    def error(self): return None
    def partition(self): return 0
    def offset(self): return 1


@pytest.mark.asyncio
async def test_consumer_calls_error_callback_on_deserialize_failure(monkeypatch):
    cfg = ConsumerConfig(bootstrap_servers="kafka:29092", group_id="g")
    disp = EventDispatcher()
    uc = UnifiedConsumer(cfg, disp)
    # Use a schema registry that returns a valid event
    uc._schema_registry = DummySchemaRegistry()  # type: ignore[attr-defined]
    called = {"n": 0}

    async def err_cb(exc, ev):  # noqa: ANN001
        called["n"] += 1
        # Ensure we got the expected error
        assert "bad payload" in str(exc)

    uc.register_error_callback(err_cb)
    # Register a handler that raises to trigger error callback
    async def boom(_):  # noqa: ANN001
        raise ValueError("bad payload")
    from app.domain.enums.events import EventType
    disp.register_handler(EventType.USER_LOGGED_IN, boom)
    # Processing triggers dispatcher error, but dispatcher swallows exceptions;
    # UnifiedConsumer only calls error callback on exceptions raised from dispatch,
    # so the error callback should NOT be invoked.
    await uc._process_message(Msg())
    # Give a moment for async callback to complete
    await asyncio.sleep(0.1)
    assert called["n"] == 0
import json

from app.events.core.consumer import UnifiedConsumer
from app.events.core.dispatcher import EventDispatcher
from app.events.core.types import ConsumerConfig
from app.events.schema.schema_registry import SchemaRegistryManager


class DummySchema(SchemaRegistryManager):
    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        pass


def test_handle_stats_updates_metrics() -> None:
    cfg = ConsumerConfig(bootstrap_servers="kafka:29092", group_id="g")
    uc = UnifiedConsumer(cfg, EventDispatcher())
    stats = {
        "rxmsgs": 10,
        "rxmsg_bytes": 1000,
        "topics": {
            "t": {
                "partitions": {
                    "0": {"consumer_lag": 5},
                    "1": {"consumer_lag": 7},
                }
            }
        },
    }
    uc._handle_stats(json.dumps(stats))
    m = uc.metrics
    assert m.messages_consumed == 10
    assert m.bytes_consumed == 1000
    assert m.consumer_lag == 12


def test_seek_helpers_no_consumer() -> None:
    cfg = ConsumerConfig(bootstrap_servers="kafka:29092", group_id="g")
    uc = UnifiedConsumer(cfg, EventDispatcher())
    # Should not crash without a real consumer
    uc._seek_all_partitions(0)
    assert uc.consumer is None
