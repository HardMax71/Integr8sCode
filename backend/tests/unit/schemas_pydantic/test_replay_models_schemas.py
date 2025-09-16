from datetime import datetime, timezone

from app.domain.enums.events import EventType
from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay.models import ReplayConfig as DomainReplayConfig, ReplayFilter as DomainReplayFilter
from app.schemas_pydantic.replay_models import ReplayConfigSchema, ReplayFilterSchema, ReplaySession


def test_replay_filter_schema_from_domain():
    df = DomainReplayFilter(
        execution_id="e1",
        event_types=[EventType.EXECUTION_REQUESTED],
        exclude_event_types=[EventType.POD_CREATED],
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        user_id="u1",
        service_name="svc",
        custom_query={"x": 1},
    )
    sf = ReplayFilterSchema.from_domain(df)
    assert sf.event_types == [str(EventType.EXECUTION_REQUESTED)]
    assert sf.exclude_event_types == [str(EventType.POD_CREATED)]


def test_replay_config_schema_from_domain_and_key_conversion():
    df = DomainReplayFilter(event_types=[EventType.EXECUTION_REQUESTED])
    cfg = DomainReplayConfig(
        replay_type=ReplayType.TIME_RANGE,
        target=ReplayTarget.KAFKA,
        filter=df,
        target_topics={EventType.EXECUTION_REQUESTED: "execution-events"},
        max_events=10,
    )
    sc = ReplayConfigSchema.model_validate(cfg)
    assert sc.target_topics == {str(EventType.EXECUTION_REQUESTED): "execution-events"}
    assert sc.max_events == 10


def test_replay_session_coerces_config_from_domain():
    df = DomainReplayFilter()
    cfg = DomainReplayConfig(replay_type=ReplayType.TIME_RANGE, filter=df)
    session = ReplaySession(config=cfg)
    assert session.status == ReplayStatus.CREATED
    assert isinstance(session.config, ReplayConfigSchema)
