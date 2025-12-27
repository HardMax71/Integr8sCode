from datetime import datetime, timezone, timedelta

import pytest

from app.db.repositories import EventRepository
from app.domain.events.event_models import EventFields, Event, EventFilter
from app.domain.enums.common import SortOrder
from app.domain.enums.user import UserRole
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.domain.enums.events import EventType
from app.services.event_service import EventService

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_event_service_access_and_queries(scope) -> None:  # type: ignore[valid-type]
    repo: EventRepository = await scope.get(EventRepository)
    svc: EventService = await scope.get(EventService)

    now = datetime.now(timezone.utc)
    # Seed some events (domain Event, not infra BaseEvent)
    md1 = AvroEventMetadata(service_name="svc", service_version="1", user_id="u1", correlation_id="c1")
    md2 = AvroEventMetadata(service_name="svc", service_version="1", user_id="u2", correlation_id="c1")
    e1 = Event(event_id="e1", event_type=str(EventType.USER_LOGGED_IN), event_version="1.0", timestamp=now,
               metadata=md1, payload={"user_id": "u1", "login_method": "password"}, aggregate_id="agg1")
    e2 = Event(event_id="e2", event_type=str(EventType.USER_LOGGED_IN), event_version="1.0", timestamp=now,
               metadata=md2, payload={"user_id": "u2", "login_method": "password"}, aggregate_id="agg2")
    await repo.store_event(e1)
    await repo.store_event(e2)

    # get_execution_events returns None when non-admin for different user; then admin sees
    events_user = await svc.get_execution_events("agg1", "u2", UserRole.USER)
    assert events_user is None
    events_admin = await svc.get_execution_events("agg1", "admin", UserRole.ADMIN)
    assert any(ev.aggregate_id == "agg1" for ev in events_admin.events)

    # query_events_advanced: basic run (empty filters) should return a result structure
    res = await svc.query_events_advanced("u1", UserRole.USER, filters=EventFilter(), sort_by="correlation_id", sort_order=SortOrder.ASC)
    assert res is not None

    # get_events_by_correlation filters non-admin to their own user_id
    by_corr_user = await svc.get_events_by_correlation("c1", user_id="u1", user_role=UserRole.USER, include_all_users=False)
    assert all(ev.metadata.user_id == "u1" for ev in by_corr_user.events)
    by_corr_admin = await svc.get_events_by_correlation("c1", user_id="admin", user_role=UserRole.ADMIN, include_all_users=True)
    assert len(by_corr_admin.events) >= 2

    # get_event_statistics (time window)
    _ = await svc.get_event_statistics("u1", UserRole.USER, start_time=now - timedelta(days=1), end_time=now + timedelta(days=1))

    # get_event enforces access control
    one_allowed = await svc.get_event(e1.event_id, user_id="u1", user_role=UserRole.USER)
    assert one_allowed is not None
    one_denied = await svc.get_event(e1.event_id, user_id="u2", user_role=UserRole.USER)
    assert one_denied is None

    # aggregate_events injects user filter for non-admin
    pipe = [{"$match": {EventFields.EVENT_TYPE: str(e1.event_type)}}]
    _ = await svc.aggregate_events("u1", UserRole.USER, pipe)

    # list_event_types returns at least one type
    types = await svc.list_event_types("u1", UserRole.USER)
    assert isinstance(types, list) and len(types) >= 1
