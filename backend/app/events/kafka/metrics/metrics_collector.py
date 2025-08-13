import asyncio
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from prometheus_client import Counter, Gauge, Histogram

from app.config import get_settings
from app.core.logging import logger
from app.events.kafka.metrics.metrics import (
    KAFKA_CONSUMER_BYTES_CONSUMED,
    KAFKA_CONSUMER_COMMITTED_OFFSET,
    KAFKA_CONSUMER_ERRORS,
    KAFKA_CONSUMER_LAG,
    KAFKA_CONSUMER_REBALANCES,
    KAFKA_MESSAGES_FAILED,
    KAFKA_MESSAGES_RECEIVED,
    KAFKA_MESSAGES_SENT,
    KAFKA_PRODUCER_BYTES_SENT,
    KAFKA_SEND_DURATION,
)

# Consumer-specific processing time with event_type label
CONSUMER_PROCESSING_TIME = Histogram(
    "kafka_consumer_processing_time_seconds",
    "Time taken to process messages",
    ["consumer_group", "topic", "event_type"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]
)

# Kafka-specific metrics
KAFKA_CIRCUIT_BREAKER_FALLBACKS = Counter(
    "kafka_circuit_breaker_fallbacks_total",
    "Total Kafka circuit breaker fallback operations",
    ["operation", "topic"]
)

KAFKA_CIRCUIT_BREAKER_RECOVERY = Histogram(
    "kafka_circuit_breaker_recovery_seconds",
    "Time to recover from circuit breaker open state",
    ["operation"],
    buckets=[10, 30, 60, 120, 300, 600]
)

# Topic/Partition Metrics
TOPIC_PARTITION_COUNT = Gauge(
    "kafka_topic_partition_count",
    "Number of partitions for a topic",
    ["topic"]
)

TOPIC_REPLICATION_FACTOR = Gauge(
    "kafka_topic_replication_factor",
    "Replication factor for a topic",
    ["topic"]
)

PARTITION_LEADER = Gauge(
    "kafka_partition_leader",
    "Leader broker ID for a partition",
    ["topic", "partition"]
)

PARTITION_IN_SYNC_REPLICAS = Gauge(
    "kafka_partition_in_sync_replicas",
    "Number of in-sync replicas for a partition",
    ["topic", "partition"]
)

PARTITION_HIGH_WATER_MARK = Gauge(
    "kafka_partition_high_water_mark",
    "High water mark offset for a partition",
    ["topic", "partition"]
)

PARTITION_LOG_START_OFFSET = Gauge(
    "kafka_partition_log_start_offset",
    "Log start offset for a partition",
    ["topic", "partition"]
)

# Broker Metrics
BROKER_COUNT = Gauge(
    "kafka_broker_count",
    "Number of brokers in the cluster"
)

BROKER_STATUS = Gauge(
    "kafka_broker_status",
    "Status of a broker (1=up, 0=down)",
    ["broker_id", "host", "port"]
)

# Connection Metrics
CONNECTION_COUNT = Gauge(
    "kafka_connection_count",
    "Number of active connections",
    ["connection_type"]  # producer, consumer, admin
)

CONNECTION_ERRORS = Counter(
    "kafka_connection_errors_total",
    "Total number of connection errors",
    ["connection_type", "error_type"]
)

# Throughput Metrics
MESSAGE_THROUGHPUT = Gauge(
    "kafka_message_throughput_per_second",
    "Messages per second throughput",
    ["direction", "topic"]  # direction: in/out
)

BYTES_THROUGHPUT = Gauge(
    "kafka_bytes_throughput_per_second",
    "Bytes per second throughput",
    ["direction", "topic"]  # direction: in/out
)


class KafkaMetricsCollector:
    """Collects and exposes Kafka metrics"""

    def __init__(self, update_interval: float = 30.0):
        self.settings = get_settings()
        self.update_interval = update_interval
        self._running = False
        self._admin_client: Optional[AIOKafkaAdminClient] = None
        self._collection_task: Optional[asyncio.Task] = None

        # Throughput tracking
        self._message_counts: Dict[str, Dict[str, int]] = {
            "in": defaultdict(int),
            "out": defaultdict(int)
        }
        self._byte_counts: Dict[str, Dict[str, int]] = {
            "in": defaultdict(int),
            "out": defaultdict(int)
        }
        self._last_throughput_update = time.time()

        # Consumer group tracking
        self._tracked_consumer_groups: Set[str] = set()
        self._consumer_clients: Dict[str, AIOKafkaConsumer] = {}

    async def start(self) -> None:
        """Start metrics collection"""
        if self._running:
            return

        self._running = True

        # Initialize admin client
        self._admin_client = AIOKafkaAdminClient(
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            client_id="kafka-metrics-collector"
        )
        await self._admin_client.start()

        # Start collection task
        self._collection_task = asyncio.create_task(self._collect_metrics_loop())

        logger.info("Kafka metrics collector started")

    async def stop(self) -> None:
        """Stop metrics collection"""
        self._running = False

        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass

        # Close consumers
        for consumer in self._consumer_clients.values():
            await consumer.stop()
        self._consumer_clients.clear()

        # Close admin client
        if self._admin_client:
            await self._admin_client.close()

        logger.info("Kafka metrics collector stopped")

    def track_consumer_group(self, group_id: str) -> None:
        """Add a consumer group to track"""
        self._tracked_consumer_groups.add(group_id)

    def untrack_consumer_group(self, group_id: str) -> None:
        """Remove a consumer group from tracking"""
        self._tracked_consumer_groups.discard(group_id)

    def record_message_consumed(
            self,
            consumer_group: str,
            topic: str,
            partition: int,
            message_size: int,
            event_type: str,
            processing_time: float
    ) -> None:
        """Record metrics for a consumed message"""
        # Note: KAFKA_MESSAGES_RECEIVED doesn't have partition label
        KAFKA_MESSAGES_RECEIVED.labels(
            consumer_group=consumer_group,
            topic=topic
        ).inc()

        KAFKA_CONSUMER_BYTES_CONSUMED.labels(
            consumer_group=consumer_group,
            topic=topic
        ).inc(message_size)

        CONSUMER_PROCESSING_TIME.labels(
            consumer_group=consumer_group,
            topic=topic,
            event_type=event_type
        ).observe(processing_time)

        # Update throughput tracking
        self._message_counts["in"][topic] += 1
        self._byte_counts["in"][topic] += message_size

    def record_message_produced(
            self,
            topic: str,
            partition: int,
            message_size: int,
            send_latency: float
    ) -> None:
        """Record metrics for a produced message"""
        # Note: KAFKA_MESSAGES_SENT doesn't have partition label
        KAFKA_MESSAGES_SENT.labels(
            topic=topic
        ).inc()

        KAFKA_PRODUCER_BYTES_SENT.labels(topic=topic).inc(message_size)

        KAFKA_SEND_DURATION.labels(topic=topic).observe(send_latency)

        # Update throughput tracking
        self._message_counts["out"][topic] += 1
        self._byte_counts["out"][topic] += message_size

    def record_producer_error(self, topic: str, error_type: str) -> None:
        """Record producer error"""
        KAFKA_MESSAGES_FAILED.labels(topic=topic, error_type=error_type).inc()

    def record_consumer_error(
            self,
            consumer_group: str,
            topic: str,
            error_type: str
    ) -> None:
        """Record consumer error"""
        # Note: KAFKA_CONSUMER_ERRORS doesn't have topic label
        KAFKA_CONSUMER_ERRORS.labels(
            consumer_group=consumer_group,
            error_type=error_type
        ).inc()

    def record_rebalance(self, consumer_group: str) -> None:
        """Record consumer group rebalance"""
        KAFKA_CONSUMER_REBALANCES.labels(consumer_group=consumer_group).inc()

    async def _collect_metrics_loop(self) -> None:
        """Main metrics collection loop"""
        while self._running:
            try:
                # Collect various metrics
                await asyncio.gather(
                    self._collect_broker_metrics(),
                    self._collect_topic_metrics(),
                    self._collect_consumer_group_metrics(),
                    self._update_throughput_metrics(),
                    return_exceptions=True
                )

                # Wait before next collection
                await asyncio.sleep(self.update_interval)

            except Exception as e:
                logger.error(f"Error in metrics collection loop: {e}")
                await asyncio.sleep(self.update_interval)

    async def _collect_broker_metrics(self) -> None:
        """Collect broker-level metrics"""
        try:
            # Skip if admin client not initialized
            if not self._admin_client:
                return

            # Get cluster metadata
            metadata = await self._admin_client.describe_cluster()

            # aiokafka 0.12.0's describe_cluster() returns a dict
            brokers = metadata['brokers']

            # Update broker count
            BROKER_COUNT.set(len(brokers))

            # Update individual broker status
            for broker in brokers:
                BROKER_STATUS.labels(
                    broker_id=str(broker['node_id']),
                    host=broker['host'],
                    port=str(broker['port'])
                ).set(1)  # Broker is up if we can get metadata

        except Exception as e:
            logger.error(f"Error collecting broker metrics: {e}")

    async def _collect_topic_metrics(self) -> None:
        """Collect topic and partition metrics"""
        try:
            # Skip if admin client not initialized
            if not self._admin_client:
                return
            
            # Get all topics - returns a list of topic names
            topic_names = await self._admin_client.list_topics()

            for topic_name in topic_names:
                if topic_name.startswith("__"):  # Skip internal topics
                    continue

                # Get metadata for this specific topic
                if self._admin_client:
                    topic_metadata_list = await self._admin_client.describe_topics([topic_name])
                else:
                    continue
                if not topic_metadata_list:
                    continue

                # describe_topics returns a list of topic metadata dicts
                topic_info = None
                for topic_meta in topic_metadata_list:
                    if topic_meta.get('topic') == topic_name:
                        topic_info = topic_meta
                        break
                
                if not topic_info:
                    continue

                # Get partitions info
                partitions = topic_info.get('partitions', [])
                if not partitions:
                    continue

                # Update partition count
                TOPIC_PARTITION_COUNT.labels(topic=topic_name).set(len(partitions))

                # Get replication factor from first partition
                if partitions:
                    first_partition = partitions[0]
                    replicas = first_partition.get('replicas', [])
                    TOPIC_REPLICATION_FACTOR.labels(topic=topic_name).set(len(replicas))

                # Update partition metrics
                partition_ids = []
                for partition in partitions:
                    partition_id = partition.get('partition')
                    if partition_id is None:
                        continue
                    
                    partition_ids.append(partition_id)
                    
                    # Get leader
                    leader = partition.get('leader')
                    if leader is not None:
                        PARTITION_LEADER.labels(
                            topic=topic_name,
                            partition=str(partition_id)
                        ).set(leader)

                    # Get in-sync replicas
                    isrs = partition.get('isrs', [])
                    PARTITION_IN_SYNC_REPLICAS.labels(
                        topic=topic_name,
                        partition=str(partition_id)
                    ).set(len(isrs))

                # Get partition offsets
                if partition_ids:
                    await self._collect_partition_offsets(topic_name, partition_ids)

        except Exception as e:
            logger.error(f"Error collecting topic metrics: {e}")

    async def _collect_partition_offsets(
            self,
            topic: str,
            partitions: List[int]
    ) -> None:
        """Collect partition offset information"""
        try:
            # Create temporary consumer to get offsets
            consumer = AIOKafkaConsumer(
                bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id=None,  # No group needed
                enable_auto_commit=False
            )

            await consumer.start()

            try:
                for partition_id in partitions:
                    tp = TopicPartition(topic, partition_id)
                    
                    # Get high water mark
                    hw = consumer.highwater(tp)
                    if hw is not None:
                        PARTITION_HIGH_WATER_MARK.labels(
                            topic=topic,
                            partition=str(partition_id)
                        ).set(hw)

                    # Get log start offset
                    beginning_offsets = await consumer.beginning_offsets([tp])
                    if tp in beginning_offsets:
                        PARTITION_LOG_START_OFFSET.labels(
                            topic=topic,
                            partition=str(partition_id)
                        ).set(beginning_offsets[tp])

            finally:
                await consumer.stop()

        except Exception as e:
            logger.error(f"Error collecting partition offsets for {topic}: {e}")

    async def _collect_consumer_group_metrics(self) -> None:
        """Collect consumer group metrics"""
        for group_id in self._tracked_consumer_groups:
            try:
                await self._collect_group_metrics(group_id)
            except Exception as e:
                logger.error(f"Error collecting metrics for group {group_id}: {e}")

    async def _collect_group_metrics(self, group_id: str) -> None:
        """Collect metrics for a specific consumer group"""
        try:
            # Skip if admin client not initialized
            if not self._admin_client:
                return
            
            # Get consumer group info
            group_info = await self._admin_client.describe_consumer_groups([group_id])

            if group_info and group_id in group_info:
                # Get committed offsets
                offsets = await self._admin_client.list_consumer_group_offsets(group_id)

                for (topic, partition), offset_metadata in offsets.items():
                    # Update committed offset
                    KAFKA_CONSUMER_COMMITTED_OFFSET.labels(
                        consumer_group=group_id,
                        topic=topic,
                        partition=str(partition)
                    ).set(offset_metadata.offset)

                    # Calculate lag
                    # Get high water mark for partition
                    hw = await self._get_partition_high_water_mark(topic, partition)
                    if hw is not None:
                        lag = hw - offset_metadata.offset
                        KAFKA_CONSUMER_LAG.labels(
                            consumer_group=group_id,
                            topic=topic,
                            partition=str(partition)
                        ).set(max(0, lag))

        except Exception as e:
            logger.error(f"Error collecting group metrics for {group_id}: {e}")

    async def _get_partition_high_water_mark(
            self,
            topic: str,
            partition: int
    ) -> Optional[int]:
        """Get high water mark for a partition"""
        try:
            # Use cached consumer if available
            cache_key = f"{topic}:{partition}"
            if cache_key not in self._consumer_clients:
                consumer = AIOKafkaConsumer(
                    bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
                    group_id=None,
                    enable_auto_commit=False
                )
                await consumer.start()
                self._consumer_clients[cache_key] = consumer

            consumer = self._consumer_clients[cache_key]
            tp = TopicPartition(topic, partition)
            highwater = consumer.highwater(tp)
            return int(highwater) if highwater is not None else None

        except Exception as e:
            logger.error(f"Error getting high water mark for {topic}:{partition}: {e}")
            return None

    async def _update_throughput_metrics(self) -> None:
        """Update throughput metrics"""
        current_time = time.time()
        time_diff = current_time - self._last_throughput_update

        if time_diff < 1.0:  # Update at most once per second
            return

        # Calculate throughput
        for direction in ["in", "out"]:
            for topic, count in self._message_counts[direction].items():
                throughput = count / time_diff
                MESSAGE_THROUGHPUT.labels(
                    direction=direction,
                    topic=topic
                ).set(throughput)

                # Reset counter
                self._message_counts[direction][topic] = 0

            for topic, bytes_count in self._byte_counts[direction].items():
                throughput = bytes_count / time_diff
                BYTES_THROUGHPUT.labels(
                    direction=direction,
                    topic=topic
                ).set(throughput)

                # Reset counter
                self._byte_counts[direction][topic] = 0

        self._last_throughput_update = current_time


class ConsumerLagTrackerRegistry:
    """Registry for ConsumerLagTracker instances"""
    _trackers: Dict[str, 'ConsumerLagTracker'] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def get_tracker(cls, tracker_key: str) -> Optional['ConsumerLagTracker']:
        """Get tracker by key"""
        async with cls._lock:
            return cls._trackers.get(tracker_key)

    @classmethod
    async def set_tracker(cls, tracker_key: str, tracker: 'ConsumerLagTracker') -> None:
        """Store tracker instance"""
        async with cls._lock:
            cls._trackers[tracker_key] = tracker

    @classmethod
    def get_tracker_sync(cls, tracker_key: str) -> Optional['ConsumerLagTracker']:
        """Synchronous get for compatibility"""
        return cls._trackers.get(tracker_key)

    @classmethod
    def set_tracker_sync(cls, tracker_key: str, tracker: 'ConsumerLagTracker') -> None:
        """Synchronous set for compatibility"""
        cls._trackers[tracker_key] = tracker


class ConsumerLagTracker:
    """Tracks consumer lag in real-time for a specific consumer group/topic/partition"""

    # Use the registry for static access
    _trackers = ConsumerLagTrackerRegistry._trackers

    @classmethod
    def get_tracker(cls, tracker_key: str) -> Optional['ConsumerLagTracker']:
        """Get tracker instance by key"""
        return ConsumerLagTrackerRegistry.get_tracker_sync(tracker_key)

    def __init__(self, consumer_group: str, topics: List[str]):
        self.consumer_group = consumer_group
        self.topics = topics
        self.lag_history: List[Tuple[datetime, int]] = []
        self._max_history_size = 1000

        # Track min/max/sum for statistics
        self.min_lag: Optional[int] = None
        self.max_lag: Optional[int] = None
        self._sum_lag: int = 0
        self._count: int = 0

    def record_lag(self, lag: int) -> None:
        """Record lag value"""
        timestamp = datetime.now(timezone.utc)
        self.lag_history.append((timestamp, lag))

        # Update statistics
        if self.min_lag is None or lag < self.min_lag:
            self.min_lag = lag
        if self.max_lag is None or lag > self.max_lag:
            self.max_lag = lag
        self._sum_lag += lag
        self._count += 1

        # Trim history
        if len(self.lag_history) > self._max_history_size:
            # Remove oldest entries and update statistics
            removed = self.lag_history[:-self._max_history_size]
            self.lag_history = self.lag_history[-self._max_history_size:]

            # Recalculate statistics if we removed entries
            if removed:
                self._recalculate_statistics()

    def get_trend(self) -> str:
        """Get lag trend (increasing/decreasing/stable)"""
        if len(self.lag_history) < 2:
            return "stable"

        # Look at last 5 minutes of data
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        recent_history = [(ts, lag) for ts, lag in self.lag_history if ts >= cutoff_time]

        if len(recent_history) < 2:
            return "stable"

        # Calculate rate of change
        first_lag = recent_history[0][1]
        last_lag = recent_history[-1][1]
        time_diff = (recent_history[-1][0] - recent_history[0][0]).total_seconds() / 60

        if time_diff > 0:
            rate = (last_lag - first_lag) / time_diff
            if rate > 10:
                return "increasing"
            elif rate < -10:
                return "decreasing"

        return "stable"

    def get_rate_per_minute(self) -> float:
        """Get rate of lag change per minute"""
        if len(self.lag_history) < 2:
            return 0.0

        # Look at last 5 minutes
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        recent_history = [(ts, lag) for ts, lag in self.lag_history if ts >= cutoff_time]

        if len(recent_history) < 2:
            return 0.0

        first_lag = recent_history[0][1]
        last_lag = recent_history[-1][1]
        time_diff = (recent_history[-1][0] - recent_history[0][0]).total_seconds() / 60

        return (last_lag - first_lag) / time_diff if time_diff > 0 else 0.0

    def get_average(self) -> Optional[float]:
        """Get average lag"""
        if self._count == 0:
            return None
        return self._sum_lag / self._count

    def get_lag_trend(
            self,
            topic: str,
            partition: int,
            window_minutes: int = 5
    ) -> Dict[str, Any]:
        """Get detailed lag trend analysis"""
        if not self.lag_history:
            return {
                "current_lag": 0,
                "trend": "stable",
                "rate_per_minute": 0,
                "min_lag": None,
                "max_lag": None,
                "avg_lag": None
            }

        current_lag = self.lag_history[-1][1] if self.lag_history else 0
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

        # Filter by time window
        window_history = [(ts, lag) for ts, lag in self.lag_history if ts >= cutoff_time]

        if not window_history:
            return {
                "current_lag": current_lag,
                "trend": "stable",
                "rate_per_minute": 0,
                "min_lag": self.min_lag,
                "max_lag": self.max_lag,
                "avg_lag": self.get_average()
            }

        # Calculate metrics for window
        window_lags = [lag for _, lag in window_history]
        window_min = min(window_lags)
        window_max = max(window_lags)
        window_avg = sum(window_lags) / len(window_lags)

        # Calculate rate
        rate_per_minute = 0.0
        if len(window_history) >= 2:
            time_diff = (window_history[-1][0] - window_history[0][0]).total_seconds() / 60
            if time_diff > 0:
                rate_per_minute = (window_history[-1][1] - window_history[0][1]) / time_diff

        # Determine trend
        if rate_per_minute > 10:
            trend = "increasing"
        elif rate_per_minute < -10:
            trend = "decreasing"
        else:
            trend = "stable"

        return {
            "current_lag": current_lag,
            "trend": trend,
            "rate_per_minute": rate_per_minute,
            "min_lag": window_min,
            "max_lag": window_max,
            "avg_lag": window_avg
        }

    def _recalculate_statistics(self) -> None:
        """Recalculate min/max/sum after trimming history"""
        if not self.lag_history:
            self.min_lag = None
            self.max_lag = None
            self._sum_lag = 0
            self._count = 0
            return

        lags = [lag for _, lag in self.lag_history]
        self.min_lag = min(lags)
        self.max_lag = max(lags)
        self._sum_lag = sum(lags)
        self._count = len(lags)


class MetricsCollectorManager:
    """Manages KafkaMetricsCollector lifecycle without globals"""

    def __init__(self) -> None:
        self._collector: Optional[KafkaMetricsCollector] = None
        self._lock = asyncio.Lock()

    async def get_collector(self) -> KafkaMetricsCollector:
        """Get or create metrics collector instance"""
        async with self._lock:
            if self._collector is None:
                self._collector = KafkaMetricsCollector()
                await self._collector.start()
            return self._collector

    async def close_collector(self) -> None:
        """Close metrics collector if exists"""
        async with self._lock:
            if self._collector:
                await self._collector.stop()
                self._collector = None

    @property
    def is_running(self) -> bool:
        """Check if collector is running"""
        return self._collector is not None and self._collector._running
