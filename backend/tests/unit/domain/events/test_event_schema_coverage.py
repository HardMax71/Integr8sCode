import re
from typing import get_args

import pytest

from app.domain.enums import EventType
from app.domain.events import DomainEvent

pytestmark = pytest.mark.unit


def test_every_event_type_has_exactly_one_event_class() -> None:
    classes = get_args(get_args(DomainEvent)[0])
    assert sorted(cls.model_fields["event_type"].default for cls in classes) == sorted(EventType)


@pytest.mark.parametrize("event_type", list(EventType))
def test_event_type_is_snake_case(event_type: EventType) -> None:
    assert re.fullmatch(r"[a-z]+(_[a-z]+)*", event_type)
