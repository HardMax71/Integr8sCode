import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aiokafka.protocol.api import Response
from aiokafka.protocol.group import MemberAssignment

from app.core.utils import StringEnum


class ConsumerGroupHealth(StringEnum):
    """Consumer group health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# Known consumer group states from Kafka protocol
class ConsumerGroupState(StringEnum):
    """Consumer group states from Kafka protocol."""

    STABLE = "Stable"
    PREPARING_REBALANCE = "PreparingRebalance"
    COMPLETING_REBALANCE = "CompletingRebalance"
    EMPTY = "Empty"
    DEAD = "Dead"
    UNKNOWN = "Unknown"


@dataclass(slots=True)
class ConsumerGroupMember:
    """Information about a consumer group member."""

    member_id: str
    client_id: str
    host: str
    assigned_partitions: list[str]  # topic:partition format


@dataclass(slots=True)
class ConsumerGroupStatus:
    """Comprehensive consumer group status information."""

    group_id: str
    state: ConsumerGroupState
    protocol: str
    protocol_type: str
    coordinator: str
    members: list[ConsumerGroupMember]

    # Health metrics
    member_count: int
    assigned_partitions: int
    partition_distribution: dict[str, int]  # member_id -> partition count

    # Lag information (if available)
    total_lag: int = 0
    partition_lags: dict[str, int] = field(default_factory=dict)  # topic:partition -> lag

    # Health assessment
    health: ConsumerGroupHealth = ConsumerGroupHealth.UNKNOWN
    health_message: str = ""

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class DescribedGroup:
    """Parsed group from DescribeGroupsResponse."""

    error_code: int
    group_id: str
    state: str
    protocol_type: str
    protocol: str
    members: list[dict[str, Any]]


def _parse_describe_groups_response(response: Response) -> list[DescribedGroup]:
    """Parse DescribeGroupsResponse into typed DescribedGroup objects."""
    obj = response.to_object()
    groups_data: list[dict[str, Any]] = obj["groups"]

    result: list[DescribedGroup] = []
    for g in groups_data:
        result.append(
            DescribedGroup(
                error_code=g["error_code"],
                group_id=g["group"],
                state=g["state"],
                protocol_type=g["protocol_type"],
                protocol=g["protocol"],
                members=g["members"],
            )
        )
    return result


_logger = logging.getLogger(__name__)


def _parse_member_assignment(assignment_bytes: bytes) -> list[tuple[str, list[int]]]:
    """Parse member_assignment bytes to list of (topic, partitions)."""
    if not assignment_bytes:
        return []

    try:
        assignment = MemberAssignment.decode(assignment_bytes)
        return [(topic, list(partitions)) for topic, partitions in assignment.assignment]
    except Exception as e:
        _logger.debug(f"Failed to parse member assignment: {e}")
        return []


def _state_from_string(state_str: str) -> ConsumerGroupState:
    """Convert state string to ConsumerGroupState enum."""
    try:
        return ConsumerGroupState(state_str)
    except ValueError:
        return ConsumerGroupState.UNKNOWN



