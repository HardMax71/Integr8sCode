from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.events.core import ConsumerConfig, ProducerConfig
from app.infrastructure.kafka.mappings import (
    get_event_class_for_type,
    get_event_types_for_topic,
    get_topic_for_event,
)


def test_producer_config_mapping() -> None:
    cfg = ProducerConfig(
        bootstrap_servers="kafka:29092",
        client_id="cid",
        batch_size=123,
        linger_ms=7,
        compression_type="gzip",
        request_timeout_ms=1111,
        retries=2,
        enable_idempotence=True,
        acks="all",
        max_in_flight_requests_per_connection=3,
    )
    conf = cfg.to_producer_config()
    assert conf["bootstrap.servers"] == "kafka:29092"
    assert conf["client.id"] == "cid"
    assert conf["batch.size"] == 123
    assert conf["linger.ms"] == 7
    assert conf["compression.type"] == "gzip"
    assert conf["enable.idempotence"] is True


def test_consumer_config_mapping() -> None:
    cfg = ConsumerConfig(
        bootstrap_servers="kafka:29092",
        group_id="g",
        client_id="c",
        auto_offset_reset="latest",
        enable_auto_commit=False,
        session_timeout_ms=12345,
        heartbeat_interval_ms=999,
        max_poll_interval_ms=555000,
        fetch_min_bytes=10,
        fetch_max_wait_ms=777,
        statistics_interval_ms=60000,
    )
    conf = cfg.to_consumer_config()
    assert conf["bootstrap.servers"] == "kafka:29092"
    assert conf["group.id"] == "g"
    assert conf["client.id"] == "c"
    assert conf["auto.offset.reset"] == "latest"
    assert conf["enable.auto.commit"] is False
    assert conf["fetch.wait.max.ms"] == 777


def test_event_mappings_topics() -> None:
    # A few spot checks
    assert get_topic_for_event(EventType.EXECUTION_REQUESTED) == KafkaTopic.EXECUTION_EVENTS
    cls = get_event_class_for_type(EventType.CREATE_POD_COMMAND)
    assert cls is not None
    # All event types for a topic include at least one of the checked types
    ev_types = get_event_types_for_topic(KafkaTopic.EXECUTION_EVENTS)
    assert EventType.EXECUTION_REQUESTED in ev_types
