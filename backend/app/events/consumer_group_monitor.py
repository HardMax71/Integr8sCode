import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, cast

from confluent_kafka import Consumer, ConsumerGroupState, KafkaError, TopicPartition
from confluent_kafka.admin import ConsumerGroupDescription

from app.core.logging import logger
from app.core.utils import StringEnum
from app.events.admin_utils import AdminUtils
from app.settings import get_settings


class ConsumerGroupHealth(StringEnum):
    """Consumer group health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ConsumerGroupMember:
    """Information about a consumer group member."""
    member_id: str
    client_id: str
    host: str
    assigned_partitions: List[str]  # topic:partition format


@dataclass(slots=True)
class ConsumerGroupStatus:
    """Comprehensive consumer group status information."""
    group_id: str
    state: str
    protocol: str
    protocol_type: str
    coordinator: str
    members: List[ConsumerGroupMember]

    # Health metrics
    member_count: int
    assigned_partitions: int
    partition_distribution: Dict[str, int]  # member_id -> partition count

    # Lag information (if available)
    total_lag: int = 0
    partition_lags: Dict[str, int] | None = None  # topic:partition -> lag

    # Health assessment
    health: ConsumerGroupHealth = ConsumerGroupHealth.UNKNOWN
    health_message: str = ""

    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

        if self.partition_lags is None:
            self.partition_lags = {}


class NativeConsumerGroupMonitor:
    """
    Enhanced consumer group monitoring using confluent-kafka native operations.
    
    Provides detailed consumer group health monitoring, lag tracking, and
    rebalancing detection using AdminClient's native capabilities.
    """

    def __init__(
            self,
            bootstrap_servers: str | None = None,
            client_id: str = "integr8scode-consumer-group-monitor",
            request_timeout_ms: int = 30000,
            # Health thresholds
            max_rebalance_time_seconds: int = 300,  # 5 minutes
            critical_lag_threshold: int = 10000,
            warning_lag_threshold: int = 1000,
            min_members_threshold: int = 1,
    ):
        settings = get_settings()
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS

        self.admin_client = AdminUtils(bootstrap_servers=self.bootstrap_servers)

        # Health thresholds
        self.max_rebalance_time = max_rebalance_time_seconds
        self.critical_lag_threshold = critical_lag_threshold
        self.warning_lag_threshold = warning_lag_threshold
        self.min_members_threshold = min_members_threshold

        # Monitoring state
        self._group_status_cache: Dict[str, ConsumerGroupStatus] = {}
        self._cache_ttl_seconds = 30

    async def get_consumer_group_status(
            self,
            group_id: str,
            timeout: float = 30.0,
            include_lag: bool = True
    ) -> ConsumerGroupStatus:
        """Get comprehensive status for a consumer group."""
        try:
            # Check cache first
            if group_id in self._group_status_cache:
                cached = self._group_status_cache[group_id]
                if cached.timestamp is not None:
                    cache_age = (datetime.now(timezone.utc) - cached.timestamp).total_seconds()
                    if cache_age < self._cache_ttl_seconds:
                        return cached

            # Get group description from AdminClient
            group_desc = await self._describe_consumer_group(group_id, timeout)

            # Build member information
            members = []
            partition_distribution = {}
            total_assigned_partitions = 0

            for member in group_desc.members:
                # Parse assigned partitions
                assigned_partitions = []
                if member.assignment and hasattr(member.assignment, 'topic_partitions'):
                    for tp in member.assignment.topic_partitions:
                        assigned_partitions.append(f"{tp.topic}:{tp.partition}")

                members.append(ConsumerGroupMember(
                    member_id=member.member_id,
                    client_id=member.client_id,
                    host=member.host,
                    assigned_partitions=assigned_partitions
                ))

                partition_distribution[member.member_id] = len(assigned_partitions)
                total_assigned_partitions += len(assigned_partitions)

            # Get coordinator information
            coordinator = f"{group_desc.coordinator.host}:{group_desc.coordinator.port}"

            # Get lag information if requested
            total_lag = 0
            partition_lags = {}
            if include_lag and group_desc.state == ConsumerGroupState.STABLE:
                try:
                    lag_info = await self._get_consumer_group_lag(group_id, timeout)
                    total_lag = lag_info.get('total_lag', 0)
                    partition_lags = lag_info.get('partition_lags', {})
                except Exception as e:
                    logger.warning(f"Failed to get lag info for group {group_id}: {e}")

            # Create status object
            status = ConsumerGroupStatus(
                group_id=group_id,
                state=group_desc.state.name if group_desc.state else "UNKNOWN",
                protocol=getattr(group_desc, 'protocol', 'unknown'),
                protocol_type=getattr(group_desc, 'protocol_type', 'unknown'),
                coordinator=coordinator,
                members=members,
                member_count=len(members),
                assigned_partitions=total_assigned_partitions,
                partition_distribution=partition_distribution,
                total_lag=total_lag,
                partition_lags=partition_lags
            )

            # Assess health
            status.health, status.health_message = self._assess_group_health(status)

            # Cache the result
            self._group_status_cache[group_id] = status

            return status

        except Exception as e:
            logger.error(f"Failed to get consumer group status for {group_id}: {e}")

            # Return minimal status with error
            return ConsumerGroupStatus(
                group_id=group_id,
                state="ERROR",
                protocol="unknown",
                protocol_type="unknown",
                coordinator="unknown",
                members=[],
                member_count=0,
                assigned_partitions=0,
                partition_distribution={},
                health=ConsumerGroupHealth.UNHEALTHY,
                health_message=f"Failed to get group status: {e}"
            )

    async def get_multiple_group_status(
            self,
            group_ids: List[str],
            timeout: float = 30.0,
            include_lag: bool = True
    ) -> Dict[str, ConsumerGroupStatus]:
        """Get status for multiple consumer groups efficiently."""
        results = {}

        # Process groups concurrently
        tasks = [
            self.get_consumer_group_status(group_id, timeout, include_lag)
            for group_id in group_ids
        ]

        try:
            statuses = await asyncio.gather(*tasks, return_exceptions=True)

            for group_id, status in zip(group_ids, statuses, strict=False):
                if isinstance(status, Exception):
                    logger.error(f"Failed to get status for group {group_id}: {status}")
                    results[group_id] = ConsumerGroupStatus(
                        group_id=group_id,
                        state="ERROR",
                        protocol="unknown",
                        protocol_type="unknown",
                        coordinator="unknown",
                        members=[],
                        member_count=0,
                        assigned_partitions=0,
                        partition_distribution={},
                        health=ConsumerGroupHealth.UNHEALTHY,
                        health_message=str(status)
                    )
                elif isinstance(status, ConsumerGroupStatus):
                    results[group_id] = status

        except Exception as e:
            logger.error(f"Failed to get multiple group status: {e}")
            # Return error status for all groups
            for group_id in group_ids:
                results[group_id] = ConsumerGroupStatus(
                    group_id=group_id,
                    state="ERROR",
                    protocol="unknown",
                    protocol_type="unknown",
                    coordinator="unknown",
                    members=[],
                    member_count=0,
                    assigned_partitions=0,
                    partition_distribution={},
                    health=ConsumerGroupHealth.UNHEALTHY,
                    health_message=str(e)
                )

        return results

    async def list_consumer_groups(self, timeout: float = 10.0) -> List[str]:
        """List all consumer groups in the cluster."""
        try:
            # Use native AdminClient to list consumer groups
            admin = self.admin_client.admin_client

            # List consumer groups (sync operation)
            result = await asyncio.to_thread(admin.list_consumer_groups, request_timeout=timeout)

            # Extract group IDs from result
            # ListConsumerGroupsResult has .valid and .errors attributes
            group_ids = []
            if hasattr(result, 'valid'):
                # result.valid contains a list of ConsumerGroupListing objects
                group_ids = [group_listing.group_id for group_listing in result.valid]

            # Log any errors that occurred
            if hasattr(result, 'errors') and result.errors:
                for error in result.errors:
                    logger.warning(f"Error listing some consumer groups: {error}")

            return group_ids

        except Exception as e:
            logger.error(f"Failed to list consumer groups: {e}")
            return []

    async def _describe_consumer_group(self, group_id: str, timeout: float) -> ConsumerGroupDescription:
        """Describe a single consumer group using native AdminClient."""
        try:
            admin = self.admin_client.admin_client

            # Describe consumer group (sync operation)
            future_map = admin.describe_consumer_groups([group_id], request_timeout=timeout)

            if group_id not in future_map:
                raise ValueError(f"Group {group_id} not found in describe result")

            future = future_map[group_id]
            # Cast future.result to proper type to help mypy
            result_func = cast(Any, future.result)
            group_desc: ConsumerGroupDescription = await asyncio.to_thread(result_func, timeout=timeout)

            return group_desc

        except Exception as e:
            if hasattr(e, 'args') and e.args and isinstance(e.args[0], KafkaError):
                kafka_err = e.args[0]
                logger.error(f"Kafka error describing group {group_id}: "
                             f"code={kafka_err.code()}, "
                             f"name={kafka_err.name()}, "
                             f"message={kafka_err}")
                raise ValueError(f"Failed to describe group {group_id}: {kafka_err}")
            raise ValueError(f"Failed to describe group {group_id}: {e}")

    async def _get_consumer_group_lag(
            self,
            group_id: str,
            timeout: float
    ) -> Dict[str, Any]:
        """Get consumer group lag information."""
        try:
            # Create a temporary consumer to get lag info
            consumer_config = {
                'bootstrap.servers': self.bootstrap_servers,
                'group.id': f"{group_id}-lag-monitor-{datetime.now().timestamp()}",
                'enable.auto.commit': False,
                'auto.offset.reset': 'earliest'
            }

            consumer = Consumer(consumer_config)

            try:
                # Get group metadata to find assigned topics
                group_desc = await self._describe_consumer_group(group_id, timeout)

                # Extract topics from member assignments
                topics = set()
                for member in group_desc.members:
                    if member.assignment and hasattr(member.assignment, 'topic_partitions'):
                        for tp in member.assignment.topic_partitions:
                            topics.add(tp.topic)

                if not topics:
                    return {'total_lag': 0, 'partition_lags': {}}

                # Get topic metadata to find all partitions
                metadata = await asyncio.to_thread(consumer.list_topics, timeout=timeout)

                total_lag = 0
                partition_lags = {}

                for topic in topics:
                    if topic not in metadata.topics:
                        continue

                    topic_metadata = metadata.topics[topic]

                    for partition_id in topic_metadata.partitions.keys():
                        try:
                            # Get high water mark
                            low, high = await asyncio.to_thread(
                                consumer.get_watermark_offsets,
                                TopicPartition(topic, partition_id),
                                timeout=timeout
                            )

                            # Get committed offset for the group
                            committed = await asyncio.to_thread(
                                consumer.committed,
                                [TopicPartition(topic, partition_id)],
                                timeout=timeout
                            )

                            if committed and len(committed) > 0:
                                committed_offset = committed[0].offset
                                if committed_offset >= 0:  # Valid offset
                                    lag = max(0, high - committed_offset)
                                    partition_lags[f"{topic}:{partition_id}"] = lag
                                    total_lag += lag

                        except Exception as e:
                            logger.debug(f"Failed to get lag for {topic}:{partition_id}: {e}")
                            continue

                return {
                    'total_lag': total_lag,
                    'partition_lags': partition_lags
                }

            finally:
                consumer.close()

        except Exception as e:
            logger.warning(f"Failed to get consumer group lag for {group_id}: {e}")
            return {'total_lag': 0, 'partition_lags': {}}

    def _assess_group_health(self, status: ConsumerGroupStatus) -> tuple[ConsumerGroupHealth, str]:
        """Assess the health of a consumer group based on its status."""

        # Check for critical issues
        if status.state == "ERROR":
            return ConsumerGroupHealth.UNHEALTHY, "Group is in error state"

        if status.member_count < self.min_members_threshold:
            return ConsumerGroupHealth.UNHEALTHY, f"Insufficient members: {status.member_count}"

        # Check for rebalancing issues
        if status.state in ("REBALANCING", "COMPLETING_REBALANCE"):
            # This could be normal, but we'll mark as degraded
            return ConsumerGroupHealth.DEGRADED, f"Group is rebalancing: {status.state}"

        # Check lag if available
        if status.total_lag >= self.critical_lag_threshold:
            return ConsumerGroupHealth.UNHEALTHY, f"Critical lag: {status.total_lag} messages"

        if status.total_lag >= self.warning_lag_threshold:
            return ConsumerGroupHealth.DEGRADED, f"High lag: {status.total_lag} messages"

        # Check partition distribution
        if status.partition_distribution:
            max_partitions = max(status.partition_distribution.values())
            min_partitions = min(status.partition_distribution.values())

            # Warn if partition distribution is very uneven
            if max_partitions > 0 and (max_partitions - min_partitions) > max_partitions * 0.5:
                return ConsumerGroupHealth.DEGRADED, "Uneven partition distribution"

        # Check if group is stable and consuming
        if status.state == "STABLE" and status.assigned_partitions > 0:
            return ConsumerGroupHealth.HEALTHY, f"Group is stable with {status.member_count} members"

        # Default case
        return ConsumerGroupHealth.UNKNOWN, f"Group state: {status.state}"

    def get_health_summary(self, status: ConsumerGroupStatus) -> Dict[str, Any]:
        """Get a health summary for a consumer group."""
        return {
            "group_id": status.group_id,
            "health": status.health.value,
            "health_message": status.health_message,
            "state": status.state,
            "members": status.member_count,
            "assigned_partitions": status.assigned_partitions,
            "total_lag": status.total_lag,
            "coordinator": status.coordinator,
            "timestamp": status.timestamp.isoformat() if status.timestamp else None,
            "partition_distribution": status.partition_distribution
        }

    def clear_cache(self) -> None:
        """Clear the status cache."""
        self._group_status_cache.clear()


def create_consumer_group_monitor(
        bootstrap_servers: str | None = None,
        **kwargs: Any
) -> NativeConsumerGroupMonitor:
    return NativeConsumerGroupMonitor(bootstrap_servers=bootstrap_servers, **kwargs)
