from app.infrastructure.kafka.events.metadata import AvroEventMetadata


def test_to_dict() -> None:
    m = AvroEventMetadata(service_name="svc", service_version="1.0")
    d = m.to_dict()
    assert d["service_name"] == "svc"
    assert d["service_version"] == "1.0"


def test_from_dict() -> None:
    m = AvroEventMetadata.from_dict({"service_name": "a", "service_version": "2", "user_id": "u"})
    assert m.service_name == "a"
    assert m.service_version == "2"
    assert m.user_id == "u"


def test_with_correlation() -> None:
    m = AvroEventMetadata(service_name="svc", service_version="1")
    m2 = m.with_correlation("cid")
    assert m2.correlation_id == "cid"
    assert m2.service_name == m.service_name  # preserves other fields


def test_with_user() -> None:
    m = AvroEventMetadata(service_name="svc", service_version="1")
    m2 = m.with_user("u1")
    assert m2.user_id == "u1"


def test_ensure_correlation_id() -> None:
    m = AvroEventMetadata(service_name="svc", service_version="1")
    # ensure_correlation_id returns self if correlation_id already present
    same = m.ensure_correlation_id()
    assert same.correlation_id == m.correlation_id
    assert m.ensure_correlation_id().correlation_id
