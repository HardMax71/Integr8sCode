
from app.events.core.types import ConsumerConfig, ProducerConfig


def test_producer_config_mapping() -> None:
    cfg = ProducerConfig(bootstrap_servers="localhost:9092", client_id="cid")
    m = cfg.to_producer_config()
    assert m["bootstrap.servers"] == "localhost:9092"
    assert m["client.id"] == "cid"
    assert m["compression.type"] == "gzip"


def test_consumer_config_mapping() -> None:
    cfg = ConsumerConfig(bootstrap_servers="localhost:9092", group_id="gid", client_id="cid")
    m = cfg.to_consumer_config()
    assert m["bootstrap.servers"] == "localhost:9092"
    assert m["group.id"] == "gid"
    assert m["client.id"] == "cid"
    assert m["auto.offset.reset"] == "earliest"
