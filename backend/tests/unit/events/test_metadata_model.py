import pytest

from app.domain.events import EventMetadata


def test_metadata_requires_user_id() -> None:
    with pytest.raises(TypeError, match="user_id"):
        EventMetadata(service_name="svc", service_version="1")  # type: ignore[call-arg]


def test_metadata_with_user() -> None:
    m = EventMetadata(service_name="svc", service_version="1", user_id="u1")
    assert m.user_id == "u1"
