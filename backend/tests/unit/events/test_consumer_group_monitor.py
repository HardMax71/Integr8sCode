import asyncio
from types import SimpleNamespace

import pytest

from app.events.consumer_group_monitor import (
    ConsumerGroupHealth,
    ConsumerGroupMember,
    ConsumerGroupStatus,
    NativeConsumerGroupMonitor,
)
from confluent_kafka import ConsumerGroupState


def make_status(**kwargs) -> ConsumerGroupStatus:  # noqa: ANN001
    defaults = dict(
        group_id="g",
        state="STABLE",
        protocol="range",
        protocol_type="consumer",
        coordinator="host:9092",
        members=[ConsumerGroupMember("m1", "c1", "h1", ["t:0"])],
        member_count=1,
        assigned_partitions=1,
        partition_distribution={"m1": 1},
        total_lag=0,
        partition_lags={},
    )
    defaults.update(kwargs)
    return ConsumerGroupStatus(**defaults)


def test_assess_group_health_variants():
    mon = NativeConsumerGroupMonitor()
    assert mon._assess_group_health(make_status(state="ERROR"))[0] == ConsumerGroupHealth.UNHEALTHY
    assert mon._assess_group_health(make_status(member_count=0))[0] == ConsumerGroupHealth.UNHEALTHY
    assert mon._assess_group_health(make_status(state="REBALANCING"))[0] == ConsumerGroupHealth.DEGRADED
    assert mon._assess_group_health(make_status(total_lag=20000))[0] == ConsumerGroupHealth.UNHEALTHY
    assert mon._assess_group_health(make_status(total_lag=1500))[0] == ConsumerGroupHealth.DEGRADED
    # Uneven partitions
    s = make_status(partition_distribution={"m1": 10, "m2": 1}, member_count=2)
    assert mon._assess_group_health(s)[0] == ConsumerGroupHealth.DEGRADED
    # Healthy
    assert mon._assess_group_health(make_status())[0] == ConsumerGroupHealth.HEALTHY
    # Unknown
    assert mon._assess_group_health(make_status(state="UNKNOWN", assigned_partitions=0))[0] == ConsumerGroupHealth.UNKNOWN


def test_get_health_summary_and_cache_clear():
    mon = NativeConsumerGroupMonitor()
    s = make_status()
    summary = mon.get_health_summary(s)
    assert summary["group_id"] == "g"
    mon._group_status_cache["g"] = s
    assert "g" in mon._group_status_cache
    mon.clear_cache()
    assert "g" not in mon._group_status_cache


@pytest.mark.asyncio
async def test_get_consumer_group_status_success_and_cache(monkeypatch):
    mon = NativeConsumerGroupMonitor()

    class Member:
        def __init__(self):
            self.member_id = "m1"
            self.client_id = "c1"
            self.host = "h1"
            self.assignment = SimpleNamespace(topic_partitions=[SimpleNamespace(topic="t", partition=0)])

    group_desc = SimpleNamespace(
        members=[Member()],
        state=ConsumerGroupState.STABLE,
        protocol="range",
        protocol_type="consumer",
        coordinator=SimpleNamespace(host="co", port=9092),
    )

    calls = {"describe": 0}

    async def fake_describe(group_id, timeout):  # noqa: ANN001
        calls["describe"] += 1
        return group_desc

    async def fake_lag(group_id, timeout):  # noqa: ANN001
        # Return dict matching monitor implementation
        return {"total_lag": 5, "partition_lags": {"t:0": 5}}

    monkeypatch.setattr(mon, "_describe_consumer_group", fake_describe)
    monkeypatch.setattr(mon, "_get_consumer_group_lag", fake_lag)

    st = await mon.get_consumer_group_status("g1")
    assert st.group_id == "g1"
    assert st.total_lag == 5
    # Cache it and call again; describe should not be called if within TTL
    mon._group_status_cache["g1"] = st
    st2 = await mon.get_consumer_group_status("g1")
    assert st2 is st


@pytest.mark.asyncio
async def test_list_consumer_groups_success_and_error(monkeypatch):
    mon = NativeConsumerGroupMonitor()

    class Admin:
        def list_consumer_groups(self, request_timeout):  # noqa: ANN001
            return SimpleNamespace(
                valid=[SimpleNamespace(group_id="g1"), SimpleNamespace(group_id="g2")],
                errors=[],
            )

    # Inject admin client instance through AdminUtils internals
    mon.admin_client._admin = Admin()
    groups = await mon.list_consumer_groups()
    assert groups == ["g1", "g2"]

    class BadAdmin:
        def list_consumer_groups(self, request_timeout):  # noqa: ANN001
            raise RuntimeError("x")

    mon.admin_client._admin = BadAdmin()
    groups2 = await mon.list_consumer_groups()
    assert groups2 == []
