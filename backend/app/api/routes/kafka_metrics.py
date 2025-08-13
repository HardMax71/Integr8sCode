from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import require_admin
from app.db.repositories.kafka_metrics_repository import (
    KafkaMetricsRepository,
    get_kafka_metrics_repository,
)
from app.schemas_pydantic.kafka_metrics import (
    ConsumerGroupMetrics,
    KafkaClusterMetrics,
    LagMetrics,
    ThroughputMetrics,
    TopicMetrics,
)
from app.schemas_pydantic.user import UserResponse

router = APIRouter(prefix="/kafka/metrics", tags=["kafka-metrics"])


@router.get("/lag", response_model=List[LagMetrics])
async def get_consumer_lag(
        consumer_group: Optional[str] = Query(None, description="Filter by consumer group"),
        topic: Optional[str] = Query(None, description="Filter by topic"),
        repository: KafkaMetricsRepository = Depends(get_kafka_metrics_repository),
        current_user: UserResponse = Depends(require_admin)
) -> List[LagMetrics]:
    """Get consumer lag metrics with real-time data from Kafka"""
    return await repository.get_consumer_lag_metrics(consumer_group, topic)


@router.get("/throughput", response_model=List[ThroughputMetrics])
async def get_throughput_metrics(
        topic: Optional[str] = Query(None, description="Filter by topic"),
        direction: Optional[str] = Query(None, description="Filter by direction (in/out)"),
        repository: KafkaMetricsRepository = Depends(get_kafka_metrics_repository),
        current_user: UserResponse = Depends(require_admin)
) -> List[ThroughputMetrics]:
    """Get message throughput metrics with real-time calculations"""
    return await repository.get_throughput_metrics(topic, direction)


@router.get("/topics", response_model=List[TopicMetrics])
async def get_topic_metrics(
        topic: Optional[str] = Query(None, description="Filter by topic name"),
        repository: KafkaMetricsRepository = Depends(get_kafka_metrics_repository),
        current_user: UserResponse = Depends(require_admin)
) -> List[TopicMetrics]:
    """Get topic-level metrics with real Kafka metadata"""
    return await repository.get_topic_metrics(topic)


@router.get("/consumer-groups", response_model=List[ConsumerGroupMetrics])
async def get_consumer_group_metrics(
        group_id: Optional[str] = Query(None, description="Filter by consumer group ID"),
        repository: KafkaMetricsRepository = Depends(get_kafka_metrics_repository),
        current_user: UserResponse = Depends(require_admin)
) -> List[ConsumerGroupMetrics]:
    """Get consumer group metrics with real Kafka data"""
    return await repository.get_consumer_group_metrics(group_id)


@router.get("/cluster", response_model=KafkaClusterMetrics)
async def get_cluster_metrics(
        repository: KafkaMetricsRepository = Depends(get_kafka_metrics_repository),
        current_user: UserResponse = Depends(require_admin)
) -> KafkaClusterMetrics:
    """Get overall Kafka cluster metrics with real cluster data"""
    return await repository.get_cluster_metrics()


@router.get("/lag/trend/{consumer_group}/{topic}/{partition}")
async def get_lag_trend(
        consumer_group: str,
        topic: str,
        partition: int,
        window_minutes: int = Query(5, description="Time window in minutes for trend analysis"),
        repository: KafkaMetricsRepository = Depends(get_kafka_metrics_repository),
        current_user: UserResponse = Depends(require_admin)
) -> Dict[str, Any]:
    """Get lag trend analysis for a specific partition with historical data"""
    return await repository.get_lag_trend(consumer_group, topic, partition, window_minutes)
