from fastapi import APIRouter, Depends, Query

from app.api.dependencies import require_admin
from app.core.service_dependencies import KafkaMetricsRepositoryDep
from app.schemas_pydantic.kafka_metrics import (
    ConsumerGroupMetrics,
    KafkaClusterMetrics,
    LagMetrics,
    ThroughputMetrics,
    TopicMetrics,
)
from app.schemas_pydantic.user import UserResponse

router = APIRouter(prefix="/kafka/metrics", tags=["kafka-metrics"])


@router.get("/lag", response_model=list[LagMetrics])
async def get_consumer_lag(
        repository: KafkaMetricsRepositoryDep,
        consumer_group: str | None = Query(None, description="Filter by consumer group"),
        topic: str | None = Query(None, description="Filter by topic"),
        current_user: UserResponse = Depends(require_admin)
) -> list[LagMetrics]:
    """Get consumer lag metrics with real-time data from Kafka"""
    return await repository.get_consumer_lag_metrics(consumer_group, topic)


@router.get("/throughput", response_model=list[ThroughputMetrics])
async def get_throughput_metrics(
        repository: KafkaMetricsRepositoryDep,
        topic: str | None = Query(None, description="Filter by topic"),
        direction: str | None = Query(None, description="Filter by direction (in/out)"),
        current_user: UserResponse = Depends(require_admin)
) -> list[ThroughputMetrics]:
    """Get message throughput metrics with real-time calculations"""
    return await repository.get_throughput_metrics(topic, direction)


@router.get("/topics", response_model=list[TopicMetrics])
async def get_topic_metrics(
        repository: KafkaMetricsRepositoryDep,
        topic: str | None = Query(None, description="Filter by topic name"),
        current_user: UserResponse = Depends(require_admin)
) -> list[TopicMetrics]:
    """Get topic-level metrics with real Kafka metadata"""
    return await repository.get_topic_metrics(topic)


@router.get("/consumer-groups", response_model=list[ConsumerGroupMetrics])
async def get_consumer_group_metrics(
        repository: KafkaMetricsRepositoryDep,
        group_id: str | None = Query(None, description="Filter by consumer group ID"),
        current_user: UserResponse = Depends(require_admin)
) -> list[ConsumerGroupMetrics]:
    """Get consumer group metrics with real Kafka data"""
    return await repository.get_consumer_group_metrics(group_id)


@router.get("/cluster", response_model=KafkaClusterMetrics)
async def get_cluster_metrics(
        repository: KafkaMetricsRepositoryDep,
        current_user: UserResponse = Depends(require_admin)
) -> KafkaClusterMetrics:
    """Get overall Kafka cluster metrics with real cluster data"""
    return await repository.get_cluster_metrics()


@router.get("/lag/trend/{consumer_group}/{topic}/{partition}")
async def get_lag_trend(
        consumer_group: str,
        topic: str,
        partition: int,
        repository: KafkaMetricsRepositoryDep,
        window_minutes: int = Query(5, description="Time window in minutes for trend analysis"),
        current_user: UserResponse = Depends(require_admin)
) -> dict[str, object]:
    """Get lag trend analysis for a specific partition with historical data"""
    return await repository.get_lag_trend(consumer_group, topic, partition, window_minutes)
