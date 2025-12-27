from app.events.metadata import AvroEventMetadata


def test_metadata_helpers():
    m = AvroEventMetadata(service_name="s", service_version="1")
    d = m.to_dict()
    assert d["service_name"] == "s"
    m2 = AvroEventMetadata.from_dict({"service_name": "a", "service_version": "2", "user_id": "u"})
    assert m2.user_id == "u"
    m3 = m.with_correlation("cid")
    assert m3.correlation_id == "cid"
    m4 = m.with_user("u2")
    assert m4.user_id == "u2"
    assert m.ensure_correlation_id().correlation_id

