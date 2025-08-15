"""
Consumer group management module for Kafka operations.

This module provides high-level abstractions for managing Kafka consumer groups,
their offsets, and related operations using modern Python 3.11+ features.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from functools import lru_cache
from typing import Any, TypeAlias

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.errors import KafkaError
from aiokafka.structs import OffsetAndMetadata
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import get_settings
from app.core.logging import logger
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.schemas_avro.event_schemas import BaseEvent

# Type aliases for handlers
EventHandler: TypeAlias = Callable[[BaseEvent | dict[str, Any], Any], Any]
ErrorHandler: TypeAlias = Callable[[Exception, Any, BaseEvent | dict[str, Any] | None], Any]

# Type aliases
GroupId: TypeAlias = str
PartitionOffsets: TypeAlias = dict[TopicPartition, int]
OffsetMap: TypeAlias = dict[TopicPartition, OffsetAndMetadata]


# Custom Exceptions
class ConsumerGroupError(Exception):
    """Base exception for consumer group operations."""
    pass


class ConsumerGroupNotFoundError(ConsumerGroupError):
    """Raised when a consumer group is not found."""
    pass


class OffsetCommitError(ConsumerGroupError):
    """Raised when offset commit fails."""
    pass


class AdminClientNotStartedError(ConsumerGroupError):
    """Raised when admin client operations are attempted before starting."""
    pass


# Enums
class ConsumerGroupState(StrEnum):
    """Consumer group states."""
    UNKNOWN = "Unknown"
    PREPARING_REBALANCE = "PreparingRebalance"
    COMPLETING_REBALANCE = "CompletingRebalance"
    STABLE = "Stable"
    DEAD = "Dead"
    EMPTY = "Empty"


class OffsetResetStrategy(StrEnum):
    """Offset reset strategies."""
    EARLIEST = "earliest"
    LATEST = "latest"
    NONE = "none"


# Pydantic Models
class ConsumerGroupMember(BaseModel):
    """Consumer group member information."""

    model_config = ConfigDict(
        frozen=True,
        str_strip_whitespace=True,
        populate_by_name=True
    )

    member_id: str
    client_id: str = ""
    host: str = ""
    assigned_partitions: list[tuple[str, int]] = Field(default_factory=list)

    @field_validator("member_id")
    @classmethod
    def validate_member_id(cls, v: str) -> str:
        """Validate member ID is not empty."""
        if not v:
            raise ValueError("Member ID cannot be empty")
        return v


class ConsumerGroupCoordinator(BaseModel):
    """Consumer group coordinator information."""

    model_config = ConfigDict(frozen=True)

    node_id: int
    host: str
    port: int

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port is in valid range."""
        if not 1 <= v <= 65535:
            raise ValueError(f"Invalid port number: {v}")
        return v


class ConsumerGroupDescription(BaseModel):
    """Detailed consumer group information."""

    model_config = ConfigDict(frozen=True)

    group_id: str
    state: ConsumerGroupState
    protocol_type: str = "consumer"
    protocol: str = ""
    members: list[ConsumerGroupMember] = Field(default_factory=list)
    coordinator: ConsumerGroupCoordinator | None = None

    @property
    def is_active(self) -> bool:
        """Check if the consumer group is active."""
        return self.state == ConsumerGroupState.STABLE

    @property
    def member_count(self) -> int:
        """Get the number of members in the group."""
        return len(self.members)

    @property
    def assigned_topics(self) -> set[str]:
        """Get all topics assigned to this consumer group."""
        topics: set[str] = set()
        for member in self.members:
            topics.update(topic for topic, _ in member.assigned_partitions)
        return topics


class ConsumerGroupStats(BaseModel):
    """Consumer group statistics."""

    model_config = ConfigDict(frozen=True)

    group_id: str
    state: ConsumerGroupState
    member_count: int = 0
    topics: list[str] = Field(default_factory=list)
    total_lag: int = 0
    partition_count: int = 0
    coordinator: ConsumerGroupCoordinator | None = None
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("total_lag", "partition_count", "member_count")
    @classmethod
    def validate_non_negative(cls, v: int) -> int:
        """Validate value is non-negative."""
        if v < 0:
            raise ValueError("Value must be non-negative")
        return v


class TopicPartitionOffset(BaseModel):
    """Topic partition with offset information."""

    model_config = ConfigDict(frozen=True)

    topic: str
    partition: int
    offset: int
    lag: int | None = None

    @field_validator("partition", "offset")
    @classmethod
    def validate_non_negative(cls, v: int) -> int:
        """Validate value is non-negative."""
        if v < 0:
            raise ValueError("Value must be non-negative")
        return v

    def to_topic_partition(self) -> TopicPartition:
        """Convert to aiokafka TopicPartition."""
        return TopicPartition(self.topic, self.partition)


# Data Classes for internal use
@dataclass(frozen=True)
class OffsetRange:
    """Represents an offset range for a partition."""
    start: int
    end: int
    current: int

    @property
    def lag(self) -> int:
        """Calculate lag."""
        return max(0, self.end - self.current)


@dataclass
class GroupMetadata:
    """Internal metadata for consumer groups."""
    group_id: str
    generation_id: int = -1
    protocol_type: str = "consumer"
    leader_id: str = ""
    member_assignment: dict[str, bytes] = field(default_factory=dict)
    last_heartbeat: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# Main Classes
class ConsumerGroupManager:
    """
    Modern consumer group manager with full async support.
    
    This class provides high-level operations for managing Kafka consumer groups
    using the admin client API and modern Python patterns.
    """

    def __init__(self, bootstrap_servers: str | None = None):
        """
        Initialize the consumer group manager.
        
        Args:
            bootstrap_servers: Kafka bootstrap servers. If None, uses settings.
        """
        settings = get_settings()
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS
        self._admin_client: AIOKafkaAdminClient | None = None
        self._started = False
        self._lock = asyncio.Lock()

    @property
    def is_started(self) -> bool:
        """Check if the manager is started."""
        return self._started and self._admin_client is not None

    async def __aenter__(self) -> "ConsumerGroupManager":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.stop()

    async def start(self) -> None:
        """Start the admin client."""
        if self._started:
            logger.warning("ConsumerGroupManager already started")
            return

        async with self._lock:
            if self._started:  # Double-check pattern
                return

            try:
                self._admin_client = AIOKafkaAdminClient(
                    bootstrap_servers=self.bootstrap_servers
                )
                await self._admin_client.start()
                self._started = True
                logger.info("ConsumerGroupManager started successfully")
            except Exception as e:
                logger.error(f"Failed to start ConsumerGroupManager: {e}")
                raise ConsumerGroupError(f"Failed to start admin client: {e}") from e

    async def stop(self) -> None:
        """Stop the admin client."""
        if not self._started:
            return

        async with self._lock:
            if not self._started:
                return

            try:
                if self._admin_client:
                    await self._admin_client.close()
                self._started = False
                logger.info("ConsumerGroupManager stopped")
            except Exception as e:
                logger.error(f"Error stopping ConsumerGroupManager: {e}")
            finally:
                self._admin_client = None

    def _ensure_started(self) -> None:
        """Ensure the admin client is started."""
        if not self.is_started:
            raise AdminClientNotStartedError("Admin client not started. Call start() first.")

    async def list_consumer_groups(self) -> list[str]:
        """
        List all consumer groups in the cluster.
        
        Returns:
            List of consumer group IDs.
            
        Raises:
            AdminClientNotStartedError: If admin client not started.
            ConsumerGroupError: If operation fails.
        """
        self._ensure_started()

        try:
            if not self._admin_client:
                raise AdminClientNotStartedError("Admin client not initialized")
            groups = await self._admin_client.list_consumer_groups()
            return [group[0] for group in groups]  # group[0] is group_id
        except Exception as e:
            logger.error(f"Failed to list consumer groups: {e}")
            raise ConsumerGroupError(f"Failed to list consumer groups: {e}") from e

    async def describe_consumer_group(
            self,
            group_id: str
    ) -> ConsumerGroupDescription | None:
        """
        Get detailed information about a consumer group.
        
        Args:
            group_id: The consumer group ID.
            
        Returns:
            ConsumerGroupDescription or None if not found.
            
        Raises:
            AdminClientNotStartedError: If admin client not started.
            ConsumerGroupError: If operation fails.
        """
        self._ensure_started()

        try:
            if not self._admin_client:
                raise AdminClientNotStartedError("Admin client not initialized")
            responses = await self._admin_client.describe_consumer_groups([group_id])

            if not responses:
                return None

            # Parse the response - it's a list of response objects
            response = responses[0]  # We only requested one group

            # Convert response to object representation
            response_obj = response.to_object()

            # The response object has a 'groups' field containing group descriptions
            groups = response_obj.get('groups', [])

            for group in groups:
                if group.get('group_id') != group_id:
                    continue

                # Build members list
                members = []
                for member_data in group.get('members', []):
                    # Parse member assignment
                    assigned_partitions = []
                    member_assignment = member_data.get('member_assignment')
                    if member_assignment and isinstance(member_assignment, dict):
                        topic_partitions = member_assignment.get('topic_partitions', [])
                        for tp in topic_partitions:
                            topic = tp.get('topic', '')
                            partitions = tp.get('partitions', [])
                            for partition in partitions:
                                assigned_partitions.append((topic, partition))

                    members.append(ConsumerGroupMember(
                        member_id=member_data.get('member_id', ''),
                        client_id=member_data.get('client_id', ''),
                        host=member_data.get('host', ''),
                        assigned_partitions=assigned_partitions
                    ))

                # Build coordinator info if available
                coordinator = None
                error_code = response_obj.get('error_code', 0)
                if error_code == 0:  # No error
                    # Try to get coordinator from response
                    coordinator_id = response_obj.get('coordinator_id')
                    coordinator_host = response_obj.get('coordinator_host')
                    coordinator_port = response_obj.get('coordinator_port')

                    if coordinator_id is not None and coordinator_host:
                        coordinator = ConsumerGroupCoordinator(
                            node_id=coordinator_id,
                            host=coordinator_host,
                            port=coordinator_port or 9092
                        )

                return ConsumerGroupDescription(
                    group_id=group.get('group_id', group_id),
                    state=ConsumerGroupState(group.get('state', 'Unknown')),
                    protocol_type=group.get('protocol_type', 'consumer'),
                    protocol=group.get('protocol', ''),
                    members=members,
                    coordinator=coordinator
                )

            return None

        except Exception as e:
            logger.error(f"Failed to describe consumer group {group_id}: {e}")
            raise ConsumerGroupError(f"Failed to describe group: {e}") from e

    async def get_consumer_group_offsets(
            self,
            group_id: str,
            topic_partitions: list[TopicPartition] | None = None
    ) -> OffsetMap:
        """
        Get committed offsets for a consumer group.
        
        Args:
            group_id: The consumer group ID.
            topic_partitions: Specific partitions to query. None for all.
            
        Returns:
            Dictionary mapping TopicPartition to OffsetAndMetadata.
            
        Raises:
            AdminClientNotStartedError: If admin client not started.
            ConsumerGroupError: If operation fails.
        """
        self._ensure_started()

        try:
            if not self._admin_client:
                raise AdminClientNotStartedError("Admin client not initialized")
            offsets = await self._admin_client.list_consumer_group_offsets(
                group_id=group_id,
                partitions=topic_partitions
            )
            return dict(offsets)
        except Exception as e:
            logger.error(f"Failed to get offsets for group {group_id}: {e}")
            raise ConsumerGroupError(f"Failed to get offsets: {e}") from e

    async def get_consumer_lag(
            self,
            group_id: str,
            topics: list[str] | None = None
    ) -> PartitionOffsets:
        """
        Calculate consumer lag for each partition.
        
        Args:
            group_id: The consumer group ID.
            topics: Specific topics to check. None for all assigned topics.
            
        Returns:
            Dictionary mapping TopicPartition to lag value.
            
        Raises:
            ConsumerGroupError: If operation fails.
        """
        async with self._create_consumer(group_id=group_id) as consumer:
            # Get topic partitions
            if topics:
                partitions = []
                for topic in topics:
                    topic_partitions = consumer.partitions_for_topic(topic)
                    if topic_partitions:
                        partitions.extend([
                            TopicPartition(topic, p) for p in topic_partitions
                        ])
            else:
                # Get from consumer group description
                description = await self.describe_consumer_group(group_id)
                if not description:
                    raise ConsumerGroupNotFoundError(f"Group {group_id} not found")

                partitions = []
                for topic in description.assigned_topics:
                    topic_partitions = consumer.partitions_for_topic(topic)
                    if topic_partitions:
                        partitions.extend([
                            TopicPartition(topic, p) for p in topic_partitions
                        ])

            if not partitions:
                return {}

            # Get committed offsets
            committed_offsets = await self.get_consumer_group_offsets(group_id, partitions)

            # Get end offsets
            end_offsets = await consumer.end_offsets(partitions)

            # Calculate lag
            lag: PartitionOffsets = {}
            for tp, end_offset in end_offsets.items():
                committed = committed_offsets.get(tp)
                current_offset = committed.offset if committed else 0
                lag[tp] = max(0, end_offset - current_offset)

            return lag

    async def get_consumer_group_stats(
            self,
            group_id: str
    ) -> ConsumerGroupStats | None:
        """
        Get comprehensive statistics for a consumer group.
        
        Args:
            group_id: The consumer group ID.
            
        Returns:
            ConsumerGroupStats or None if group not found.
        """
        try:
            description = await self.describe_consumer_group(group_id)
            if not description:
                return None

            # Get lag information
            lag_info: PartitionOffsets = {}
            if description.assigned_topics:
                try:
                    lag_info = await self.get_consumer_lag(
                        group_id,
                        list(description.assigned_topics)
                    )
                except Exception as e:
                    logger.warning(f"Failed to get lag for group {group_id}: {e}")

            return ConsumerGroupStats(
                group_id=group_id,
                state=description.state,
                member_count=description.member_count,
                topics=list(description.assigned_topics),
                total_lag=sum(lag_info.values()),
                partition_count=len(lag_info),
                coordinator=description.coordinator
            )

        except Exception as e:
            logger.error(f"Failed to get stats for group {group_id}: {e}")
            return None

    async def get_all_consumer_group_stats(self) -> list[ConsumerGroupStats]:
        """
        Get statistics for all consumer groups.
        
        Returns:
            List of ConsumerGroupStats for all groups.
        """
        groups = await self.list_consumer_groups()

        # Process groups concurrently
        tasks = [self.get_consumer_group_stats(group_id) for group_id in groups]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        stats = []
        for group_id, result in zip(groups, results, strict=False):
            if isinstance(result, Exception):
                logger.error(f"Failed to get stats for group {group_id}: {result}")
                continue
            if result is not None:
                stats.append(result)

        return [s for s in stats if isinstance(s, ConsumerGroupStats)]

    async def reset_consumer_group_offset(
            self,
            group_id: str,
            topic_partition_offsets: Sequence[TopicPartitionOffset]
    ) -> bool:
        """
        Reset offsets for specific partitions.
        
        Args:
            group_id: The consumer group ID.
            topic_partition_offsets: List of partitions with new offsets.
            
        Returns:
            True if successful, False otherwise.
        """
        if not topic_partition_offsets:
            return True

        async with self._create_consumer(group_id=group_id) as consumer:
            try:
                # Prepare offset dict
                offsets: dict[TopicPartition, int] = {}
                for tpo in topic_partition_offsets:
                    tp = tpo.to_topic_partition()
                    consumer.seek(tp, tpo.offset)
                    offsets[tp] = tpo.offset

                # Commit the offsets
                await consumer.commit(offsets)

                logger.info(
                    f"Reset {len(offsets)} offsets for group {group_id}"
                )
                return True

            except Exception as e:
                logger.error(f"Failed to reset offsets: {e}")
                return False

    async def is_consumer_group_active(self, group_id: str) -> bool:
        """
        Check if a consumer group is active.
        
        Args:
            group_id: The consumer group ID.
            
        Returns:
            True if active (STABLE state), False otherwise.
        """
        description = await self.describe_consumer_group(group_id)
        return description.is_active if description else False

    async def get_topic_end_offsets(
            self,
            topics: list[str]
    ) -> dict[TopicPartition, int]:
        """
        Get end offsets for the specified topics.
        
        Args:
            topics: List of topic names.
            
        Returns:
            Dictionary mapping TopicPartition to end offset.
            
        Raises:
            ConsumerGroupError: If operation fails.
        """
        if not topics:
            return {}

        # Create a temporary consumer to get end offsets
        consumer_config = {
            "bootstrap_servers": self.bootstrap_servers,
            "group_id": f"temp-offset-reader-{datetime.now().timestamp()}",
            "enable_auto_commit": False
        }

        consumer = AIOKafkaConsumer(*topics, **consumer_config)

        try:
            await consumer.start()

            # Get all partitions for the topics
            all_partitions = []
            for topic in topics:
                partitions = consumer.partitions_for_topic(topic)
                if partitions:
                    all_partitions.extend([
                        TopicPartition(topic, p) for p in partitions
                    ])

            if not all_partitions:
                return {}

            # Get end offsets
            end_offsets = await consumer.end_offsets(all_partitions)
            return dict(end_offsets)

        except Exception as e:
            logger.error(f"Failed to get end offsets for topics {topics}: {e}")
            raise ConsumerGroupError(f"Failed to get end offsets: {e}") from e
        finally:
            await consumer.stop()

    @asynccontextmanager
    async def _create_consumer(
            self,
            group_id: str,
            topics: list[str] | None = None
    ) -> AsyncIterator[AIOKafkaConsumer]:
        """
        Create a temporary consumer for operations.
        
        Args:
            group_id: The consumer group ID.
            topics: Topics to subscribe to.
            
        Yields:
            AIOKafkaConsumer instance.
        """
        consumer_config = {
            "bootstrap_servers": self.bootstrap_servers,
            "group_id": group_id,
            "enable_auto_commit": False
        }

        if topics:
            consumer = AIOKafkaConsumer(*topics, **consumer_config)
        else:
            consumer = AIOKafkaConsumer(**consumer_config)

        try:
            await consumer.start()
            yield consumer
        finally:
            await consumer.stop()


class OffsetManager:
    """
    Manages offset operations with caching and batch commits.
    
    This class provides efficient offset management with in-memory caching
    and batch commit operations.
    """

    def __init__(self, consumer_group: str, bootstrap_servers: str | None = None):
        """
        Initialize the offset manager.
        
        Args:
            consumer_group: The consumer group ID.
            bootstrap_servers: Kafka bootstrap servers. If None, uses settings.
        """
        self.consumer_group = consumer_group
        settings = get_settings()
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS
        self._offset_cache: PartitionOffsets = {}
        self._lock = asyncio.Lock()
        self._last_commit_time = datetime.now(timezone.utc)

    async def save_offset(
            self,
            topic: str,
            partition: int,
            offset: int
    ) -> None:
        """
        Save offset to cache.
        
        Args:
            topic: Topic name.
            partition: Partition number.
            offset: Offset value.
        """
        if offset < 0:
            raise ValueError(f"Invalid offset: {offset}")

        async with self._lock:
            tp = TopicPartition(topic, partition)
            self._offset_cache[tp] = offset

    async def save_offsets_batch(
            self,
            offsets: Sequence[TopicPartitionOffset]
    ) -> None:
        """
        Save multiple offsets to cache.
        
        Args:
            offsets: List of TopicPartitionOffset objects.
        """
        async with self._lock:
            for tpo in offsets:
                tp = tpo.to_topic_partition()
                self._offset_cache[tp] = tpo.offset

    async def get_saved_offsets(self) -> PartitionOffsets:
        """
        Get all saved offsets from cache.
        
        Returns:
            Dictionary of TopicPartition to offset.
        """
        async with self._lock:
            return self._offset_cache.copy()

    async def commit_saved_offsets(self) -> bool:
        """
        Commit all saved offsets to Kafka.
        
        Returns:
            True if successful, False otherwise.
            
        Raises:
            OffsetCommitError: If commit fails.
        """
        if not self._offset_cache:
            logger.debug("No offsets to commit")
            return True

        async with self._lock:
            offsets_to_commit = self._offset_cache.copy()

        async with self._create_consumer() as consumer:
            try:
                await consumer.commit(offsets_to_commit)

                # Clear cache after successful commit
                async with self._lock:
                    self._offset_cache.clear()
                    self._last_commit_time = datetime.now(timezone.utc)

                logger.info(
                    f"Committed {len(offsets_to_commit)} offsets for "
                    f"consumer group: {self.consumer_group}"
                )
                return True

            except KafkaError as e:
                logger.error(f"Failed to commit offsets: {e}")
                raise OffsetCommitError(f"Failed to commit offsets: {e}") from e

    async def reset_to_position(
            self,
            topics: list[str],
            strategy: OffsetResetStrategy
    ) -> bool:
        """
        Reset offsets to a specific position.
        
        Args:
            topics: Topics to reset.
            strategy: Reset strategy (earliest/latest).
            
        Returns:
            True if successful, False otherwise.
        """
        async with self._create_consumer(topics) as consumer:
            try:
                # Seek to position
                match strategy:
                    case OffsetResetStrategy.EARLIEST:
                        await consumer.seek_to_beginning()
                    case OffsetResetStrategy.LATEST:
                        await consumer.seek_to_end()
                    case _:
                        raise ValueError(f"Unsupported strategy: {strategy}")

                # Get positions and commit
                positions: PartitionOffsets = {}
                for topic in topics:
                    partitions = consumer.partitions_for_topic(topic)
                    if partitions:
                        for partition in partitions:
                            tp = TopicPartition(topic, partition)
                            position = await consumer.position(tp)
                            positions[tp] = position

                await consumer.commit(positions)

                logger.info(
                    f"Reset offsets to {strategy.value} for {self.consumer_group} - "
                    f"topics: {topics}"
                )
                return True

            except Exception as e:
                logger.error(f"Failed to reset offsets: {e}")
                return False

    @property
    def pending_offset_count(self) -> int:
        """Get the number of pending offsets in cache."""
        return len(self._offset_cache)

    @property
    def time_since_last_commit(self) -> float:
        """Get seconds since last commit."""
        return (datetime.now(timezone.utc) - self._last_commit_time).total_seconds()

    @asynccontextmanager
    async def _create_consumer(
            self,
            topics: list[str] | None = None
    ) -> AsyncIterator[AIOKafkaConsumer]:
        """Create a temporary consumer for offset operations."""
        consumer_config = {
            "bootstrap_servers": self.bootstrap_servers,
            "group_id": self.consumer_group,
            "enable_auto_commit": False
        }

        if topics:
            consumer = AIOKafkaConsumer(*topics, **consumer_config)
        else:
            consumer = AIOKafkaConsumer(**consumer_config)

        try:
            await consumer.start()
            yield consumer
        finally:
            await consumer.stop()


# Utility functions
@lru_cache(maxsize=128)
def parse_group_protocol(protocol: str) -> str:
    """
    Parse and normalize consumer group protocol.
    
    Args:
        protocol: Raw protocol string.
        
    Returns:
        Normalized protocol string.
    """
    protocol = protocol.lower().strip()
    return protocol if protocol in {"consumer", "connect"} else "consumer"


async def get_healthy_consumer_groups(
        manager: ConsumerGroupManager,
        min_members: int = 1
) -> list[ConsumerGroupDescription]:
    """
    Get all healthy (stable) consumer groups with minimum members.
    
    Args:
        manager: ConsumerGroupManager instance.
        min_members: Minimum number of members required.
        
    Returns:
        List of healthy consumer group descriptions.
    """
    groups = await manager.list_consumer_groups()

    # Check groups concurrently
    tasks = [manager.describe_consumer_group(group_id) for group_id in groups]
    descriptions = await asyncio.gather(*tasks, return_exceptions=True)

    healthy_groups = []
    for desc in descriptions:
        if isinstance(desc, Exception):
            continue
        # Explicitly check for ConsumerGroupDescription type to help type checker
        if isinstance(desc, ConsumerGroupDescription) and desc.is_active and desc.member_count >= min_members:
            healthy_groups.append(desc)

    return healthy_groups


async def batch_process_groups(
        manager: ConsumerGroupManager,
        processor: Any,  # Callable[[str], Awaitable[Any]]
        batch_size: int = 10
) -> list[Any]:
    """
    Process consumer groups in batches for better performance.
    
    Args:
        manager: ConsumerGroupManager instance.
        processor: Async function to process each group.
        batch_size: Number of groups to process concurrently.
        
    Returns:
        List of processing results.
    """
    groups = await manager.list_consumer_groups()
    results = []

    for i in range(0, len(groups), batch_size):
        batch = groups[i:i + batch_size]
        batch_tasks = [processor(group_id) for group_id in batch]
        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        results.extend(batch_results)

    return results


class ConsumerGroup:
    """
    Manages a group of consumers for parallel processing.
    
    This allows scaling out message processing across multiple
    consumer instances within the same consumer group.
    """

    def __init__(
            self,
            group_id: str,
            topics: list[str],
            num_consumers: int = 1,
            config_template: ConsumerConfig | None = None,
            schema_registry_manager: SchemaRegistryManager | None = None
    ) -> None:
        self.group_id = group_id
        self.topics = topics
        self.num_consumers = num_consumers
        self.config_template = config_template or ConsumerConfig()
        self.consumers: list[UnifiedConsumer] = []
        self._lock = asyncio.Lock()
        self._schema_registry_manager = schema_registry_manager

    async def start(self) -> None:
        """Start all consumers in the group."""
        async with self._lock:
            if self.consumers:
                logger.warning(f"Consumer group '{self.group_id}' already started")
                return

            tasks = []
            for _i in range(self.num_consumers):
                # Create config for this consumer instance
                config = ConsumerConfig(
                    **{
                        k: v for k, v in self.config_template.__dict__.items()
                        if not k.startswith('_')
                    }
                )
                # Override group_id and topics
                object.__setattr__(config, "group_id", self.group_id)
                object.__setattr__(config, "topics", self.topics)

                consumer = UnifiedConsumer(config, self._schema_registry_manager)
                self.consumers.append(consumer)
                tasks.append(consumer.start())

            await asyncio.gather(*tasks)
            logger.info(f"Started consumer group '{self.group_id}' with {self.num_consumers} consumers")

    async def stop(self) -> None:
        """Stop all consumers in the group."""
        async with self._lock:
            if not self.consumers:
                return

            logger.info(f"Stopping consumer group '{self.group_id}'")
            await asyncio.gather(*[c.stop() for c in self.consumers])
            self.consumers.clear()
            logger.info(f"Consumer group '{self.group_id}' stopped")

    async def scale(self, new_count: int) -> None:
        """Scale the number of consumers up or down."""
        async with self._lock:
            current_count = len(self.consumers)

            if new_count == current_count:
                return

            if new_count > current_count:
                # Scale up
                tasks = []
                for _i in range(new_count - current_count):
                    config = ConsumerConfig(
                        **{
                            k: v for k, v in self.config_template.__dict__.items()
                            if not k.startswith('_')
                        }
                    )
                    object.__setattr__(config, "group_id", self.group_id)
                    object.__setattr__(config, "topics", self.topics)

                    consumer = UnifiedConsumer(config, self._schema_registry_manager)
                    self.consumers.append(consumer)
                    tasks.append(consumer.start())

                await asyncio.gather(*tasks)
                logger.info(f"Scaled up consumer group '{self.group_id}' from {current_count} to {new_count}")

            else:
                # Scale down
                consumers_to_stop = self.consumers[new_count:]
                self.consumers = self.consumers[:new_count]

                await asyncio.gather(*[c.stop() for c in consumers_to_stop])
                logger.info(f"Scaled down consumer group '{self.group_id}' from {current_count} to {new_count}")

    async def pause_all(self) -> None:
        """Pause all consumers."""
        await asyncio.gather(*[c.pause() for c in self.consumers])

    async def resume_all(self) -> None:
        """Resume all consumers."""
        await asyncio.gather(*[c.resume() for c in self.consumers])

    async def get_total_lag(self) -> int:
        """Get total lag across all consumers."""
        total_lag = 0
        for consumer in self.consumers:
            total_lag += sum(consumer.metrics.current_lag.values())
        return total_lag

    async def get_metrics(self) -> dict[str, Any]:
        """Get aggregated metrics for the consumer group."""
        metrics = {
            "group_id": self.group_id,
            "topics": self.topics,
            "num_consumers": len(self.consumers),
            "total_lag": await self.get_total_lag(),
            "total_messages_processed": sum(c.metrics.messages_processed for c in self.consumers),
            "total_messages_failed": sum(c.metrics.messages_failed for c in self.consumers),
            "total_messages_dlq": sum(c.metrics.messages_dlq for c in self.consumers),
            "consumer_metrics": []
        }

        for i, consumer in enumerate(self.consumers):
            consumer_status = await consumer.get_status()
            consumer_status["instance_id"] = i
            consumer_metrics = metrics.get("consumer_metrics")
            if isinstance(consumer_metrics, list):
                consumer_metrics.append(consumer_status)

        return metrics

    def register_handler(self, event_type: str, handler: EventHandler) -> None:
        """Register handler on all consumers."""
        for consumer in self.consumers:
            consumer.register_handler(event_type, handler)

    def register_error_handler(self, handler: ErrorHandler) -> None:
        """Register error handler on all consumers."""
        for consumer in self.consumers:
            consumer.register_error_handler(handler)

    async def __aenter__(self) -> "ConsumerGroup":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.stop()


# Convenience function for creating consumer groups
@asynccontextmanager
async def create_consumer_group(
        group_id: str,
        topics: list[str],
        num_consumers: int = 1,
        handlers: dict[str, EventHandler] | None = None,
        config_template: ConsumerConfig | None = None
) -> AsyncIterator[ConsumerGroup]:
    """
    Create a consumer group with handlers in a context manager.
    
    Example:
        async with create_consumer_group("my-group", ["events"], num_consumers=3) as group:
            group.register_handler("user.created", handle_user)
            # Consumers are running
            await asyncio.sleep(60)
        # All consumers are stopped
    """
    group = ConsumerGroup(group_id, topics, num_consumers, config_template)

    await group.start()

    # Register handlers
    if handlers:
        for event_type, handler in handlers.items():
            group.register_handler(event_type, handler)

    try:
        yield group
    finally:
        await group.stop()
