from app.events.metadata import EventMetadata


def test_event_metadata_helpers():
    m = EventMetadata(service_name="svc", service_version="1")
    # ensure_correlation_id returns self if present
    same = m.ensure_correlation_id()
    assert same.correlation_id == m.correlation_id
    # with_correlation and with_user create copies
    m2 = m.with_correlation("cid")
    assert m2.correlation_id == "cid" and m2.service_name == m.service_name
    m3 = m.with_user("u1")
    assert m3.user_id == "u1"

