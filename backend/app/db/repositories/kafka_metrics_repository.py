from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Dict, List, Optional, Set

from aiokafka import AIOKafkaClient
from aiokafka.structs import TopicPartition
from fastapi import HTTPException, Request
from prometheus_client import REGISTRY

from app.config import get_settings
from app.core.health_checker import HealthStatus
from app.core.logging import logger
from app.db.mongodb import DatabaseManager
from app.events.core.consumer_group import ConsumerGroupManager
from app.events.kafka.metrics.metrics import (
    KAFKA_CONSUMER_ERRORS,
    KAFKA_CONSUMER_MESSAGES_CONSUMED,
    KAFKA_MESSAGES_FAILED,
    KAFKA_MESSAGES_SENT,
)
from app.events.kafka.metrics.metrics_collector import ConsumerLagTracker, ConsumerLagTrackerRegistry
from app.events.kafka.metrics.metrics_service import get_metrics_manager
from app.schemas_avro.event_schemas import EventType
from app.schemas_pydantic.kafka_metrics import (
    ConsumerGroupMetrics,
    KafkaClusterMetrics,
    LagMetrics,
    ThroughputMetrics,
    TopicMetrics,
)

# Python 3.12 type aliases
type TopicName = str
type PartitionId = int
type ConsumerGroupName = str
type MetricsData = Dict[str, Any]
type TopicData = Dict[TopicName, MetricsData]
type GroupData = Dict[ConsumerGroupName, MetricsData]
type MetricName = str
type MetricValue = float | int


# Metric aggregation strategies
class AggregationStrategy(StrEnum):
    """How to aggregate metric values."""
    SUM = "sum"
    LATEST = "latest"
    MAX = "max"
    MIN = "min"


# Metric mappings for topics
TOPIC_METRIC_MAPPINGS: Dict[MetricName, tuple[str, AggregationStrategy]] = {
    KAFKA_MESSAGES_SENT._name: ("total_messages_produced", AggregationStrategy.LATEST),
    KAFKA_CONSUMER_MESSAGES_CONSUMED._name: ("total_messages_consumed", AggregationStrategy.SUM),
    KAFKA_MESSAGES_FAILED._name: ("total_errors", AggregationStrategy.SUM),
    KAFKA_CONSUMER_ERRORS._name: ("total_errors", AggregationStrategy.SUM),
}

# Metric mappings for consumer groups
GROUP_METRIC_MAPPINGS: Dict[MetricName, tuple[str, AggregationStrategy]] = {
    KAFKA_CONSUMER_MESSAGES_CONSUMED._name: ("total_messages_consumed", AggregationStrategy.LATEST),
    KAFKA_CONSUMER_ERRORS._name: ("total_errors", AggregationStrategy.SUM),
}

# Cluster-level metrics to aggregate
CLUSTER_METRICS: Set[MetricName] = {
    KAFKA_MESSAGES_SENT._name,
    KAFKA_CONSUMER_MESSAGES_CONSUMED._name,
    KAFKA_MESSAGES_FAILED._name,
    KAFKA_CONSUMER_ERRORS._name,
}

# Constants for directions
DIRECTION_IN = "in"
DIRECTION_OUT = "out"

# MongoDB collection names
EVENTS_COLLECTION = "events"
KAFKA_LAG_HISTORY_COLLECTION = "kafka_lag_history"

# Constants
SYSTEM_TOPIC_PREFIX = "__"
DEFAULT_LAG_WINDOW_MINUTES = 5
LAG_HISTORY_TTL_DAYS = 7
METRICS_AGGREGATION_WINDOW_SECONDS = 60.0
DEFAULT_MESSAGE_SIZE_BYTES = 100


class KafkaMetricsRepository:
    """Repository for Kafka metrics data and monitoring."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager
        self.db = db_manager.get_database()

    def _aggregate_metric_value(
            self,
            data_dict: MetricsData,
            field_name: str,
            metric_key: str,
            value: MetricValue,
            strategy: AggregationStrategy
    ) -> None:
        """Apply aggregation strategy to metric value."""
        if metric_key not in data_dict:
            data_dict[metric_key] = 0

        if strategy == AggregationStrategy.SUM:
            data_dict[metric_key] += value
            data_dict[field_name] = data_dict.get(field_name, 0) + value
        elif strategy == AggregationStrategy.LATEST:
            data_dict[metric_key] = value
            data_dict[field_name] = value
        elif strategy == AggregationStrategy.MAX:
            data_dict[metric_key] = max(data_dict[metric_key], value)
            data_dict[field_name] = data_dict[metric_key]
        elif strategy == AggregationStrategy.MIN:
            data_dict[metric_key] = min(data_dict[metric_key], value)
            data_dict[field_name] = data_dict[metric_key]

    def _collect_metrics_from_prometheus(
            self,
            label_key: str,
            data_dict: Dict[str, MetricsData],
            metric_mappings: Dict[MetricName, tuple[str, AggregationStrategy]]
    ) -> None:
        """Generic method to collect metrics from Prometheus."""
        for metric in REGISTRY.collect():
            if metric.name in metric_mappings:
                field_name, aggregation = metric_mappings[metric.name]

                for sample in metric.samples:
                    label_value: Optional[str] = sample.labels.get(label_key)
                    if label_value and label_value in data_dict:
                        metric_key = f"metrics.{metric.name}"
                        value = int(sample.value)
                        self._aggregate_metric_value(
                            data_dict[label_value],
                            field_name,
                            metric_key,
                            value,
                            aggregation
                        )

    async def get_consumer_lag_metrics(
            self,
            consumer_group: Optional[ConsumerGroupName] = None,
            topic: Optional[TopicName] = None
    ) -> List[LagMetrics]:
        """Get consumer lag metrics with real-time data from Kafka"""
        try:
            manager = get_metrics_manager()
            collector = await manager.get_collector()

            if not collector:
                raise HTTPException(status_code=503, detail="Metrics collector not available")

            lag_metrics: List[LagMetrics] = []

            async with ConsumerGroupManager() as cg_manager:
                consumer_groups: List[ConsumerGroupName] = await cg_manager.list_consumer_groups()

                for group in consumer_groups:
                    if consumer_group and group != consumer_group:
                        continue

                    try:
                        group_offsets = await cg_manager.get_consumer_group_offsets(group)
                        topics_set: Set[TopicName] = {tp.topic for tp in group_offsets.keys()}

                        for topic_name in topics_set:
                            if topic and topic_name != topic:
                                continue

                            topic_partitions = [tp for tp in group_offsets.keys() if tp.topic == topic_name]
                            end_offsets = await cg_manager.get_topic_end_offsets([topic_name])

                            for tp in topic_partitions:
                                committed_offset = group_offsets[tp].offset
                                end_offset = end_offsets.get(tp, committed_offset)
                                lag = end_offset - committed_offset if committed_offset >= 0 else 0

                                tracker_key = f"{group}:{topic_name}:{tp.partition}"
                                tracker = ConsumerLagTracker.get_tracker(tracker_key)

                                if tracker:
                                    tracker.record_lag(lag)
                                else:
                                    tracker = ConsumerLagTracker(consumer_group=group, topics=[topic_name])
                                    tracker.record_lag(lag)
                                    ConsumerLagTrackerRegistry.set_tracker_sync(tracker_key, tracker)

                                lag_metric = LagMetrics(
                                    consumer_group=group,
                                    topic=topic_name,
                                    partition=tp.partition,
                                    current_lag=lag,
                                    trend=tracker.get_trend(),
                                    rate_per_minute=tracker.get_rate_per_minute(),
                                    min_lag=tracker.min_lag if tracker.lag_history else None,
                                    max_lag=tracker.max_lag if tracker.lag_history else None,
                                    avg_lag=tracker.get_average() if tracker.lag_history else None
                                )
                                lag_metrics.append(lag_metric)
                    except Exception as e:
                        logger.warning(f"Failed to get lag metrics for consumer group {group}: {e}")
                        continue

            return sorted(lag_metrics, key=lambda x: (x.consumer_group, x.topic, x.partition))

        except Exception as e:
            logger.error(f"Error retrieving lag metrics: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve lag metrics") from e

    async def get_throughput_metrics(
            self,
            topic: Optional[TopicName] = None,
            direction: Optional[str] = None
    ) -> List[ThroughputMetrics]:
        """Get message throughput metrics with real-time calculations"""
        try:
            manager = get_metrics_manager()
            collector = await manager.get_collector()

            if not collector:
                raise HTTPException(status_code=503, detail="Metrics collector not available")

            throughput_metrics: List[ThroughputMetrics] = []
            message_throughput_data: Dict[str, MetricsData] = {}
            bytes_throughput_data: Dict[str, float] = {}
            now = datetime.now(timezone.utc)
            one_minute_ago = now - timedelta(minutes=1)

            events_collection = self.db[EVENTS_COLLECTION]

            # Get producer metrics from events
            producer_pipeline: List[MetricsData] = [
                {
                    "$match": {
                        "timestamp": {"$gte": one_minute_ago},
                        "event_type": {
                            "$in": [
                                EventType.EXECUTION_REQUESTED,
                                EventType.EXECUTION_STARTED,
                                EventType.EXECUTION_RUNNING,
                                EventType.EXECUTION_COMPLETED,
                                EventType.EXECUTION_FAILED,
                                EventType.EXECUTION_TIMEOUT,
                                EventType.EXECUTION_CANCELLED
                            ]
                        }
                    }
                },
                {
                    "$group": {
                        "_id": {"topic": "$metadata.kafka_topic"},
                        "count": {"$sum": 1},
                        "bytes": {
                            "$sum": {
                                "$cond": [{"$ifNull": ["$metadata.message_size", 0]}, "$metadata.message_size",
                                          DEFAULT_MESSAGE_SIZE_BYTES]}}
                    }
                }
            ]

            async for result in events_collection.aggregate(producer_pipeline):
                topic_name: Optional[TopicName] = result["_id"].get("topic")
                if topic_name:
                    if topic and topic_name != topic:
                        continue
                    if direction and direction != DIRECTION_OUT:
                        continue

                    key = f"{topic_name}:{DIRECTION_OUT}"
                    messages_per_second = float(result["count"]) / METRICS_AGGREGATION_WINDOW_SECONDS
                    bytes_per_second = float(result["bytes"]) / METRICS_AGGREGATION_WINDOW_SECONDS

                    message_throughput_data[key] = {
                        'value': messages_per_second,
                        'labels': {
                            'topic': topic_name,
                            'direction': DIRECTION_OUT
                        }
                    }
                    bytes_throughput_data[key] = bytes_per_second

            # Get consumer metrics from Prometheus
            for metric in REGISTRY.collect():
                if metric.name == KAFKA_CONSUMER_MESSAGES_CONSUMED._name:
                    for sample in metric.samples:
                        topic_name = sample.labels.get('topic')
                        if topic and topic_name != topic:
                            continue
                        if direction and direction != DIRECTION_IN:
                            continue
                        if topic_name:
                            key = f"{topic_name}:{DIRECTION_IN}"
                            if key not in message_throughput_data:
                                message_throughput_data[key] = {
                                    'value': 0.0,
                                    'labels': {
                                        'topic': topic_name,
                                        'direction': DIRECTION_IN
                                    }
                                }
                                bytes_throughput_data[key] = 0.0

            for key, msg_data in message_throughput_data.items():
                throughput_metric = ThroughputMetrics(
                    topic=msg_data['labels']['topic'],
                    direction=msg_data['labels']['direction'],
                    messages_per_second=round(msg_data['value'], 2),
                    bytes_per_second=round(bytes_throughput_data.get(key, 0.0), 2),
                    timestamp=datetime.now(timezone.utc)
                )
                throughput_metrics.append(throughput_metric)

            return sorted(throughput_metrics, key=lambda x: (x.topic, x.direction))

        except Exception as e:
            logger.error(f"Error retrieving throughput metrics: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve throughput metrics") from e

    async def _collect_kafka_metadata(self, topic: Optional[TopicName] = None) -> TopicData:
        """Collect metadata from Kafka cluster"""
        topic_data: TopicData = {}
        settings = get_settings()
        client = AIOKafkaClient(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)

        try:
            await client.bootstrap()
            metadata = await client.fetch_all_metadata()

            for topic_name, topic_metadata in metadata.topics.items():
                if topic and topic_name != topic:
                    continue

                if not topic_name.startswith(SYSTEM_TOPIC_PREFIX):
                    partition_count = len(topic_metadata.partitions)
                    replication_factor = len(
                        topic_metadata.partitions[0].replicas) if topic_metadata.partitions else 1

                    topic_data[topic_name] = {
                        'partition_count': partition_count,
                        'replication_factor': replication_factor,
                        'total_messages_produced': 0,
                        'total_messages_consumed': 0,
                        'total_errors': 0,
                        # Initialize metric storage
                        'metrics': {}
                    }
        finally:
            await client.close()

        return topic_data

    async def get_topic_metrics(self, topic: Optional[TopicName] = None) -> List[TopicMetrics]:
        """Get topic-level metrics with real Kafka metadata"""
        manager = get_metrics_manager()
        collector = await manager.get_collector()

        if not collector:
            raise HTTPException(status_code=503, detail="Metrics collector not available")

        try:
            topic_metrics: List[TopicMetrics] = []

            # Get Kafka metadata
            topic_data = await self._collect_kafka_metadata(topic)

            # Collect metrics from Prometheus using generic collector
            self._collect_metrics_from_prometheus('topic', topic_data, TOPIC_METRIC_MAPPINGS)

            for topic_name, data in topic_data.items():
                topic_metric = TopicMetrics(
                    topic=topic_name,
                    partition_count=data.get('partition_count', 0),
                    replication_factor=data.get('replication_factor', 1),
                    total_messages_produced=data.get('total_messages_produced', 0),
                    total_messages_consumed=data.get('total_messages_consumed', 0),
                    total_errors=data.get('total_errors', 0)
                )
                topic_metrics.append(topic_metric)

            return sorted(topic_metrics, key=lambda x: x.topic)

        except Exception as e:
            logger.error(f"Error retrieving topic metrics: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve topic metrics") from e

    async def get_consumer_group_metrics(
            self,
            group_id: Optional[ConsumerGroupName] = None
    ) -> List[ConsumerGroupMetrics]:
        """Get consumer group metrics with real Kafka data"""
        try:
            manager = get_metrics_manager()
            collector = await manager.get_collector()

            if not collector:
                raise HTTPException(status_code=503, detail="Metrics collector not available")

            group_metrics: List[ConsumerGroupMetrics] = []
            group_data: GroupData = {}

            async with ConsumerGroupManager() as cg_manager:
                consumer_groups: List[ConsumerGroupName] = await cg_manager.list_consumer_groups()

                for group in consumer_groups:
                    if group_id and group != group_id:
                        continue

                    try:
                        group_offsets = await cg_manager.get_consumer_group_offsets(group)
                        topics_set: Set[TopicName] = {tp.topic for tp in group_offsets.keys()}

                        total_lag = 0
                        partitions_info: List[MetricsData] = []

                        for topic_name in topics_set:
                            topic_partitions = [tp for tp in group_offsets.keys() if tp.topic == topic_name]
                            end_offsets = await cg_manager.get_topic_end_offsets([topic_name])

                            for tp in topic_partitions:
                                committed_offset = group_offsets[tp].offset
                                end_offset = end_offsets.get(tp, committed_offset)
                                lag = end_offset - committed_offset if committed_offset >= 0 else 0
                                total_lag += lag

                                partitions_info.append({
                                    'topic': topic_name,
                                    'partition': tp.partition,
                                    'lag': lag,
                                    'committed_offset': committed_offset,
                                    'end_offset': end_offset
                                })

                        group_data[group] = {
                            'topics': list(topics_set),
                            'total_lag': total_lag,
                            'partitions': partitions_info,
                            'total_messages_consumed': 0,
                            'total_errors': 0,
                            # Initialize metric storage
                            'metrics': {}
                        }
                    except Exception as e:
                        logger.warning(f"Failed to get metrics for consumer group {group}: {e}")
                        continue

            # Collect metrics from Prometheus using generic collector
            self._collect_metrics_from_prometheus('consumer_group', group_data, GROUP_METRIC_MAPPINGS)

            for group_name, data in group_data.items():
                group_metric = ConsumerGroupMetrics(
                    group_id=group_name,
                    topics=data.get('topics', []),
                    total_lag=data.get('total_lag', 0),
                    total_messages_consumed=data.get('total_messages_consumed', 0),
                    total_errors=data.get('total_errors', 0),
                    partitions=data.get('partitions', [])
                )
                group_metrics.append(group_metric)

            return sorted(group_metrics, key=lambda x: x.group_id)

        except Exception as e:
            logger.error(f"Error retrieving consumer group metrics: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve consumer group metrics") from e

    async def get_cluster_metrics(self) -> KafkaClusterMetrics:
        """Get overall Kafka cluster metrics with real cluster data"""
        try:
            manager = get_metrics_manager()
            collector = await manager.get_collector()

            if not collector:
                raise HTTPException(status_code=503, detail="Metrics collector not available")

            broker_count = 0
            topic_count = 0
            consumer_groups: Set[ConsumerGroupName] = set()
            total_messages_produced = 0
            total_messages_consumed = 0
            total_errors = 0
            cluster_status = HealthStatus.HEALTHY

            settings = get_settings()
            client = AIOKafkaClient(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
            await client.bootstrap()

            try:
                metadata = await client.fetch_all_metadata()
                broker_count = len(metadata.brokers)
                topic_count = len([t for t in metadata.topics.keys() if not t.startswith(SYSTEM_TOPIC_PREFIX)])

                for broker in metadata.brokers.values():
                    if broker.host is None:
                        cluster_status = HealthStatus.DEGRADED
                        break
            except Exception as e:
                logger.error(f"Failed to get cluster metadata: {e}")
                cluster_status = HealthStatus.UNHEALTHY
            finally:
                await client.close()

            async with ConsumerGroupManager() as cg_manager:
                try:
                    groups: List[ConsumerGroupName] = await cg_manager.list_consumer_groups()
                    consumer_groups.update(groups)
                except Exception as e:
                    logger.warning(f"Failed to list consumer groups: {e}")

            # Collect metrics from Prometheus - simplified aggregation for cluster
            cluster_metrics: Dict[MetricName, MetricValue] = {}

            for metric in REGISTRY.collect():
                if metric.name in CLUSTER_METRICS:
                    for sample in metric.samples:
                        if metric.name not in cluster_metrics:
                            cluster_metrics[metric.name] = 0
                        cluster_metrics[metric.name] += int(sample.value)

            # Map to expected fields
            total_messages_produced = int(cluster_metrics.get(KAFKA_MESSAGES_SENT._name, 0))
            total_messages_consumed = int(cluster_metrics.get(KAFKA_CONSUMER_MESSAGES_CONSUMED._name, 0))
            total_errors = int(cluster_metrics.get(KAFKA_MESSAGES_FAILED._name, 0) +
                               cluster_metrics.get(KAFKA_CONSUMER_ERRORS._name, 0))

            # Determine cluster status based on metrics
            if broker_count == 0:
                cluster_status = HealthStatus.UNHEALTHY
            elif total_errors > 100:
                cluster_status = HealthStatus.UNHEALTHY
            elif total_errors > 10 and cluster_status == HealthStatus.HEALTHY:
                cluster_status = HealthStatus.DEGRADED

            return KafkaClusterMetrics(
                broker_count=broker_count,
                topic_count=topic_count,
                consumer_group_count=len(consumer_groups),
                total_messages_produced=total_messages_produced,
                total_messages_consumed=total_messages_consumed,
                total_errors=total_errors,
                cluster_status=cluster_status
            )

        except Exception as e:
            logger.error(f"Error retrieving cluster metrics: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve cluster metrics") from e

    async def get_lag_trend(
            self,
            consumer_group: ConsumerGroupName,
            topic: TopicName,
            partition: PartitionId,
            window_minutes: int = DEFAULT_LAG_WINDOW_MINUTES
    ) -> MetricsData:
        try:
            tracker_key = f"{consumer_group}:{topic}:{partition}"
            lag_tracker = ConsumerLagTracker.get_tracker(tracker_key)

            if not lag_tracker:
                async with ConsumerGroupManager() as cg_manager:
                    try:
                        tp = TopicPartition(topic, partition)

                        group_offsets = await cg_manager.get_consumer_group_offsets(consumer_group)
                        end_offsets = await cg_manager.get_topic_end_offsets([topic])

                        if tp in group_offsets and tp in end_offsets:
                            committed_offset = group_offsets[tp].offset
                            end_offset = end_offsets[tp]
                            current_lag = end_offset - committed_offset if committed_offset >= 0 else 0

                            lag_tracker = ConsumerLagTracker(consumer_group=consumer_group, topics=[topic])
                            lag_tracker.record_lag(current_lag)
                            ConsumerLagTrackerRegistry.set_tracker_sync(tracker_key, lag_tracker)
                        else:
                            raise HTTPException(
                                status_code=404,
                                detail=f"Partition {partition} not found for topic {topic} "
                                       f"in consumer group {consumer_group}"
                            )
                    except Exception as e:
                        logger.error(f"Failed to initialize lag tracker: {e}")
                        raise HTTPException(status_code=500, detail="Failed to get partition data") from e

            trend = lag_tracker.get_lag_trend(
                topic=topic,
                partition=partition,
                window_minutes=window_minutes
            )

            # Store historical data
            metrics_collection = self.db.get_collection(KAFKA_LAG_HISTORY_COLLECTION)

            now = datetime.now(timezone.utc)
            history_start = now - timedelta(minutes=window_minutes)

            historical_data: List[MetricsData] = []
            async for record in metrics_collection.find({
                "consumer_group": consumer_group,
                "topic": topic,
                "partition": partition,
                "timestamp": {"$gte": history_start}
            }).sort("timestamp", 1):
                historical_data.append({
                    "timestamp": record["timestamp"],
                    "lag": record["lag"]
                })

            if historical_data:
                trend["historical_data"] = historical_data

            # Insert current data point
            await metrics_collection.insert_one({
                "consumer_group": consumer_group,
                "topic": topic,
                "partition": partition,
                "lag": trend.get("current_lag", 0),
                "timestamp": now
            })

            # Create indexes
            await metrics_collection.create_index(
                [("consumer_group", 1), ("topic", 1), ("partition", 1), ("timestamp", -1)]
            )
            await metrics_collection.create_index(
                [("timestamp", 1)],
                expireAfterSeconds=LAG_HISTORY_TTL_DAYS * 24 * 60 * 60
            )

            return trend

        except Exception as e:
            logger.error(f"Error retrieving lag trend: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve lag trend") from e


def get_kafka_metrics_repository(request: Request) -> KafkaMetricsRepository:
    db_manager: DatabaseManager = request.app.state.db_manager
    return KafkaMetricsRepository(db_manager)
