import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.protocol.api import Response
from aiokafka.protocol.group import MemberAssignment
from aiokafka.structs import OffsetAndMetadata

from app.core.utils import StringEnum
from app.settings import Settings


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


class NativeConsumerGroupMonitor:
    """
    Enhanced consumer group monitoring using aiokafka.

    Provides detailed consumer group health monitoring, lag tracking, and
    rebalancing detection using AIOKafkaAdminClient's native capabilities.
    """

    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger,
        client_id: str = "integr8scode-consumer-group-monitor",
        # Health thresholds
        critical_lag_threshold: int = 10000,
        warning_lag_threshold: int = 1000,
        min_members_threshold: int = 1,
    ):
        self.logger = logger
        self._settings = settings
        self._bootstrap_servers = settings.KAFKA_BOOTSTRAP_SERVERS
        self._client_id = client_id

        self._admin: AIOKafkaAdminClient | None = None

        # Health thresholds
        self.critical_lag_threshold = critical_lag_threshold
        self.warning_lag_threshold = warning_lag_threshold
        self.min_members_threshold = min_members_threshold

        # Monitoring state
        self._group_status_cache: dict[str, ConsumerGroupStatus] = {}
        self._cache_ttl_seconds = 30

    async def _get_admin(self) -> AIOKafkaAdminClient:
        """Get or create the admin client."""
        if self._admin is None:
            self._admin = AIOKafkaAdminClient(
                bootstrap_servers=self._bootstrap_servers,
                client_id=self._client_id,
            )
            await self._admin.start()
        return self._admin

    async def close(self) -> None:
        """Close the admin client."""
        if self._admin is not None:
            await self._admin.close()
            self._admin = None

    async def get_consumer_group_status(
        self, group_id: str, include_lag: bool = True
    ) -> ConsumerGroupStatus:
        """Get comprehensive status for a consumer group."""
        try:
            # Check cache first
            cached = self._group_status_cache.get(group_id)
            if cached is not None:
                cache_age = (datetime.now(timezone.utc) - cached.timestamp).total_seconds()
                if cache_age < self._cache_ttl_seconds:
                    return cached

            # Get group description from AdminClient
            described_group = await self._describe_consumer_group(group_id)

            # Build member information
            members: list[ConsumerGroupMember] = []
            partition_distribution: dict[str, int] = {}
            total_assigned_partitions = 0

            for member_data in described_group.members:
                member_id: str = member_data["member_id"]
                client_id: str = member_data["client_id"]
                client_host: str = member_data["client_host"]
                assignment_bytes: bytes = member_data["member_assignment"]

                # Parse assigned partitions from assignment bytes
                assigned_partitions: list[str] = []
                topic_partitions = _parse_member_assignment(assignment_bytes)
                for topic, partitions in topic_partitions:
                    for partition in partitions:
                        assigned_partitions.append(f"{topic}:{partition}")

                members.append(
                    ConsumerGroupMember(
                        member_id=member_id,
                        client_id=client_id,
                        host=client_host,
                        assigned_partitions=assigned_partitions,
                    )
                )

                partition_distribution[member_id] = len(assigned_partitions)
                total_assigned_partitions += len(assigned_partitions)

            # Get coordinator information
            admin = await self._get_admin()
            coordinator_id = await admin.find_coordinator(group_id)
            coordinator = f"node:{coordinator_id}"

            # Parse state
            state = _state_from_string(described_group.state)

            # Get lag information if requested
            total_lag = 0
            partition_lags: dict[str, int] = {}
            if include_lag and state == ConsumerGroupState.STABLE:
                try:
                    lag_info = await self._get_consumer_group_lag(group_id)
                    total_lag = lag_info["total_lag"]
                    partition_lags = lag_info["partition_lags"]
                except Exception as e:
                    self.logger.warning(f"Failed to get lag info for group {group_id}: {e}")

            # Create status object
            status = ConsumerGroupStatus(
                group_id=group_id,
                state=state,
                protocol=described_group.protocol,
                protocol_type=described_group.protocol_type,
                coordinator=coordinator,
                members=members,
                member_count=len(members),
                assigned_partitions=total_assigned_partitions,
                partition_distribution=partition_distribution,
                total_lag=total_lag,
                partition_lags=partition_lags,
            )

            # Assess health
            status.health, status.health_message = self._assess_group_health(status)

            # Cache the result
            self._group_status_cache[group_id] = status

            return status

        except Exception as e:
            self.logger.error(f"Failed to get consumer group status for {group_id}: {e}")

            # Return minimal status with error
            return ConsumerGroupStatus(
                group_id=group_id,
                state=ConsumerGroupState.UNKNOWN,
                protocol="unknown",
                protocol_type="unknown",
                coordinator="unknown",
                members=[],
                member_count=0,
                assigned_partitions=0,
                partition_distribution={},
                health=ConsumerGroupHealth.UNHEALTHY,
                health_message=f"Failed to get group status: {e}",
            )

    async def get_multiple_group_status(
        self, group_ids: list[str], include_lag: bool = True
    ) -> dict[str, ConsumerGroupStatus]:
        """Get status for multiple consumer groups efficiently."""
        results: dict[str, ConsumerGroupStatus] = {}

        # Process groups concurrently
        tasks = [self.get_consumer_group_status(group_id, include_lag) for group_id in group_ids]

        try:
            statuses = await asyncio.gather(*tasks, return_exceptions=True)

            for group_id, status in zip(group_ids, statuses, strict=False):
                if isinstance(status, ConsumerGroupStatus):
                    results[group_id] = status
                else:
                    # status is BaseException
                    self.logger.error(f"Failed to get status for group {group_id}: {status}")
                    results[group_id] = ConsumerGroupStatus(
                        group_id=group_id,
                        state=ConsumerGroupState.UNKNOWN,
                        protocol="unknown",
                        protocol_type="unknown",
                        coordinator="unknown",
                        members=[],
                        member_count=0,
                        assigned_partitions=0,
                        partition_distribution={},
                        health=ConsumerGroupHealth.UNHEALTHY,
                        health_message=str(status),
                    )

        except Exception as e:
            self.logger.error(f"Failed to get multiple group status: {e}")
            # Return error status for all groups
            for group_id in group_ids:
                if group_id not in results:
                    results[group_id] = ConsumerGroupStatus(
                        group_id=group_id,
                        state=ConsumerGroupState.UNKNOWN,
                        protocol="unknown",
                        protocol_type="unknown",
                        coordinator="unknown",
                        members=[],
                        member_count=0,
                        assigned_partitions=0,
                        partition_distribution={},
                        health=ConsumerGroupHealth.UNHEALTHY,
                        health_message=str(e),
                    )

        return results

    async def list_consumer_groups(self) -> list[str]:
        """List all consumer groups in the cluster."""
        try:
            admin = await self._get_admin()
            # Returns list of tuples: (group_id, protocol_type)
            groups: list[tuple[Any, ...]] = await admin.list_consumer_groups()
            return [str(g[0]) for g in groups]
        except Exception as e:
            self.logger.error(f"Failed to list consumer groups: {e}")
            return []

    async def _describe_consumer_group(self, group_id: str) -> DescribedGroup:
        """Describe a single consumer group using native AdminClient."""
        admin = await self._get_admin()
        responses: list[Response] = await admin.describe_consumer_groups([group_id])

        if not responses:
            raise ValueError(f"No response for group {group_id}")

        # Parse the response
        groups = _parse_describe_groups_response(responses[0])

        # Find our group in the response
        for group in groups:
            if group.group_id == group_id:
                if group.error_code != 0:
                    raise ValueError(f"Error describing group {group_id}: error_code={group.error_code}")
                return group

        raise ValueError(f"Group {group_id} not found in response")

    async def _get_consumer_group_lag(self, group_id: str) -> dict[str, Any]:
        """Get consumer group lag information."""
        try:
            admin = await self._get_admin()

            # Get committed offsets for the group
            offsets: dict[TopicPartition, OffsetAndMetadata] = await admin.list_consumer_group_offsets(group_id)

            if not offsets:
                return {"total_lag": 0, "partition_lags": {}}

            # Create a temporary consumer to get high watermarks
            consumer = AIOKafkaConsumer(
                bootstrap_servers=self._bootstrap_servers,
                group_id=f"{group_id}-lag-monitor-{datetime.now().timestamp()}",
                enable_auto_commit=False,
                auto_offset_reset="earliest",
                session_timeout_ms=self._settings.KAFKA_SESSION_TIMEOUT_MS,
                heartbeat_interval_ms=self._settings.KAFKA_HEARTBEAT_INTERVAL_MS,
                request_timeout_ms=self._settings.KAFKA_REQUEST_TIMEOUT_MS,
            )

            try:
                await consumer.start()

                total_lag = 0
                partition_lags: dict[str, int] = {}

                # Get end offsets for all partitions
                tps = list(offsets.keys())
                if tps:
                    end_offsets: dict[TopicPartition, int] = await consumer.end_offsets(tps)

                    for tp, offset_meta in offsets.items():
                        committed_offset = offset_meta.offset
                        high = end_offsets.get(tp, 0)

                        if committed_offset >= 0:
                            lag = max(0, high - committed_offset)
                            partition_lags[f"{tp.topic}:{tp.partition}"] = lag
                            total_lag += lag

                return {"total_lag": total_lag, "partition_lags": partition_lags}

            finally:
                await consumer.stop()

        except Exception as e:
            self.logger.warning(f"Failed to get consumer group lag for {group_id}: {e}")
            return {"total_lag": 0, "partition_lags": {}}

    def _assess_group_health(self, status: ConsumerGroupStatus) -> tuple[ConsumerGroupHealth, str]:
        """Assess the health of a consumer group based on its status."""

        # Check for error/unknown state
        if status.state == ConsumerGroupState.UNKNOWN:
            return ConsumerGroupHealth.UNHEALTHY, "Group is in unknown state"

        if status.state == ConsumerGroupState.DEAD:
            return ConsumerGroupHealth.UNHEALTHY, "Group is dead"

        if status.member_count < self.min_members_threshold:
            return ConsumerGroupHealth.UNHEALTHY, f"Insufficient members: {status.member_count}"

        # Check for rebalancing issues
        if status.state in (ConsumerGroupState.PREPARING_REBALANCE, ConsumerGroupState.COMPLETING_REBALANCE):
            return ConsumerGroupHealth.DEGRADED, f"Group is rebalancing: {status.state.value}"

        # Check for empty group
        if status.state == ConsumerGroupState.EMPTY:
            return ConsumerGroupHealth.DEGRADED, "Group is empty (no active members)"

        # Check lag if available
        if status.total_lag >= self.critical_lag_threshold:
            return ConsumerGroupHealth.UNHEALTHY, f"Critical lag: {status.total_lag} messages"

        if status.total_lag >= self.warning_lag_threshold:
            return ConsumerGroupHealth.DEGRADED, f"High lag: {status.total_lag} messages"

        # Check partition distribution
        if status.partition_distribution:
            values = list(status.partition_distribution.values())
            max_partitions = max(values)
            min_partitions = min(values)

            # Warn if partition distribution is very uneven
            if max_partitions > 0 and (max_partitions - min_partitions) > max_partitions * 0.5:
                return ConsumerGroupHealth.DEGRADED, "Uneven partition distribution"

        # Check if group is stable and consuming
        if status.state == ConsumerGroupState.STABLE and status.assigned_partitions > 0:
            return ConsumerGroupHealth.HEALTHY, f"Group is stable with {status.member_count} members"

        # Default case
        return ConsumerGroupHealth.UNKNOWN, f"Group state: {status.state.value}"

    def get_health_summary(self, status: ConsumerGroupStatus) -> dict[str, Any]:
        """Get a health summary for a consumer group."""
        return {
            "group_id": status.group_id,
            "health": status.health.value,
            "health_message": status.health_message,
            "state": status.state.value,
            "members": status.member_count,
            "assigned_partitions": status.assigned_partitions,
            "total_lag": status.total_lag,
            "coordinator": status.coordinator,
            "timestamp": status.timestamp.isoformat(),
            "partition_distribution": status.partition_distribution,
        }

    def clear_cache(self) -> None:
        """Clear the status cache."""
        self._group_status_cache.clear()


