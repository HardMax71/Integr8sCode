import pytest
from app.domain.enums.common import SortOrder
from app.schemas_pydantic.events import EventFilterRequest


def test_event_filter_request_sort_validator_accepts_allowed_fields() -> None:
    req = EventFilterRequest(sort_by="timestamp", sort_order=SortOrder.DESC)
    assert req.sort_by == "timestamp"

    for field in ("event_type", "aggregate_id", "correlation_id", "stored_at"):
        req2 = EventFilterRequest(sort_by=field)
        assert req2.sort_by == field


def test_event_filter_request_sort_validator_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        EventFilterRequest(sort_by="not-a-field")
