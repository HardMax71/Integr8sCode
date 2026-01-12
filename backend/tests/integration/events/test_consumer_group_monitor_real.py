import logging
from uuid import uuid4

import pytest
from app.events.consumer_group_monitor import (
    ConsumerGroupHealth,
    ConsumerGroupState,
    ConsumerGroupStatus,
    NativeConsumerGroupMonitor,
)
from app.settings import Settings

pytestmark = [pytest.mark.integration, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.consumer_group_monitor_real")


@pytest.mark.asyncio
async def test_consumer_group_status_error_path_and_summary(test_settings: Settings) -> None:
    monitor = NativeConsumerGroupMonitor(settings=test_settings, logger=_test_logger)
    # Non-existent group triggers error-handling path and returns minimal status
    gid = f"does-not-exist-{uuid4().hex[:8]}"
    status = await monitor.get_consumer_group_status(gid, include_lag=False)
    assert status.group_id == gid
    # Some clusters report non-existent groups as DEAD/UNKNOWN rather than raising
    assert status.state in (ConsumerGroupState.DEAD, ConsumerGroupState.UNKNOWN)
    assert status.health is ConsumerGroupHealth.UNHEALTHY
    summary = monitor.get_health_summary(status)
    assert summary["group_id"] == gid and summary["health"] == ConsumerGroupHealth.UNHEALTHY.value


def test_assess_group_health_branches(test_settings: Settings) -> None:
    m = NativeConsumerGroupMonitor(settings=test_settings, logger=_test_logger)
    # Unknown state (triggers unhealthy)
    s = ConsumerGroupStatus(
        group_id="g",
        state=ConsumerGroupState.UNKNOWN,
        protocol="p",
        protocol_type="ptype",
        coordinator="c",
        members=[],
        member_count=0,
        assigned_partitions=0,
        partition_distribution={},
        total_lag=0,
    )
    h, msg = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.UNHEALTHY and "unknown" in msg.lower()

    # Dead state
    s.state = ConsumerGroupState.DEAD
    h, msg = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.UNHEALTHY and "dead" in msg.lower()

    # Insufficient members
    s.state = ConsumerGroupState.STABLE
    h, _ = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.UNHEALTHY

    # Rebalancing (preparing)
    s.member_count = 1
    s.state = ConsumerGroupState.PREPARING_REBALANCE
    h, _ = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.DEGRADED

    # Rebalancing (completing)
    s.state = ConsumerGroupState.COMPLETING_REBALANCE
    h, _ = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.DEGRADED

    # Empty group
    s.state = ConsumerGroupState.EMPTY
    h, _ = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.DEGRADED

    # Critical lag
    s.state = ConsumerGroupState.STABLE
    s.total_lag = m.critical_lag_threshold + 1
    h, _ = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.UNHEALTHY

    # Warning lag
    s.total_lag = m.warning_lag_threshold + 1
    h, _ = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.DEGRADED

    # Uneven partition distribution
    s.total_lag = 0
    s.partition_distribution = {"m1": 10, "m2": 1}
    h, _ = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.DEGRADED

    # Healthy stable
    s.partition_distribution = {"m1": 1, "m2": 1}
    s.assigned_partitions = 2
    h, _ = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.HEALTHY


@pytest.mark.asyncio
async def test_multiple_group_status_mixed_errors(test_settings: Settings) -> None:
    m = NativeConsumerGroupMonitor(settings=test_settings, logger=_test_logger)
    gids = [f"none-{uuid4().hex[:6]}", f"none-{uuid4().hex[:6]}"]
    res = await m.get_multiple_group_status(gids, include_lag=False)
    assert set(res.keys()) == set(gids)
    assert all(v.health is ConsumerGroupHealth.UNHEALTHY for v in res.values())
