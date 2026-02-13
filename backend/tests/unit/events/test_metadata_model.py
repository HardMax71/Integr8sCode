from app.domain.events import EventMetadata


def test_metadata_creation() -> None:
    m = EventMetadata(service_name="svc", service_version="1")
    assert m.service_name == "svc"
    assert m.service_version == "1"


def test_metadata_with_user() -> None:
    m = EventMetadata(service_name="svc", service_version="1", user_id="u1")
    assert m.user_id == "u1"
