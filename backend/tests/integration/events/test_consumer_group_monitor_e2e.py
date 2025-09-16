import asyncio
from uuid import uuid4

import pytest

from app.events.consumer_group_monitor import (
    ConsumerGroupHealth,
    ConsumerGroupStatus,
    NativeConsumerGroupMonitor,
)


pytestmark = [pytest.mark.integration, pytest.mark.kafka]


@pytest.mark.asyncio
async def test_consumer_group_status_error_path_and_summary():
    monitor = NativeConsumerGroupMonitor(bootstrap_servers="localhost:9092")
    # Non-existent group triggers error-handling path and returns minimal status
    gid = f"does-not-exist-{uuid4().hex[:8]}"
    status = await monitor.get_consumer_group_status(gid, timeout=5.0, include_lag=False)
    assert status.group_id == gid
    # Some clusters report non-existent groups as DEAD/UNKNOWN rather than raising
    assert status.state in ("ERROR", "DEAD", "UNKNOWN")
    assert status.health is ConsumerGroupHealth.UNHEALTHY
    summary = monitor.get_health_summary(status)
    assert summary["group_id"] == gid and summary["health"] == ConsumerGroupHealth.UNHEALTHY.value


def test_assess_group_health_branches():
    m = NativeConsumerGroupMonitor()
    # Error state
    s = ConsumerGroupStatus(
        group_id="g", state="ERROR", protocol="p", protocol_type="ptype", coordinator="c",
        members=[], member_count=0, assigned_partitions=0, partition_distribution={}, total_lag=0
    )
    h, msg = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.UNHEALTHY and "error" in msg.lower()

    # Insufficient members
    s.state = "STABLE"
    h, _ = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.UNHEALTHY

    # Rebalancing
    s.member_count = 1
    s.state = "REBALANCING"
    h, _ = m._assess_group_health(s)  # noqa: SLF001
    assert h is ConsumerGroupHealth.DEGRADED

    # Critical lag
    s.state = "STABLE"
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
async def test_multiple_group_status_mixed_errors():
    m = NativeConsumerGroupMonitor(bootstrap_servers="localhost:9092")
    gids = [f"none-{uuid4().hex[:6]}", f"none-{uuid4().hex[:6]}"]
    res = await m.get_multiple_group_status(gids, timeout=5.0, include_lag=False)
    assert set(res.keys()) == set(gids)
    assert all(v.health is ConsumerGroupHealth.UNHEALTHY for v in res.values())
