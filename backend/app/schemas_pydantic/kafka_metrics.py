"""Kafka metrics schemas"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LagMetrics(BaseModel):
    consumer_group: str
    topic: str
    partition: int
    current_lag: int
    trend: str = Field(description="Trend: increasing, decreasing, stable")
    rate_per_minute: float
    min_lag: Optional[int] = None
    max_lag: Optional[int] = None
    avg_lag: Optional[float] = None


class ThroughputMetrics(BaseModel):
    topic: str
    direction: str = Field(description="Direction: in (consumed) or out (produced)")
    messages_per_second: float
    bytes_per_second: float
    timestamp: datetime


class TopicMetrics(BaseModel):
    topic: str
    partition_count: int
    replication_factor: int
    total_messages_produced: int
    total_messages_consumed: int
    total_errors: int


class ConsumerGroupMetrics(BaseModel):
    group_id: str
    topics: List[str]
    total_lag: int
    total_messages_consumed: int
    total_errors: int
    partitions: List[Dict[str, Any]]


class KafkaClusterMetrics(BaseModel):
    broker_count: int
    topic_count: int
    consumer_group_count: int
    total_messages_produced: int
    total_messages_consumed: int
    total_errors: int
    cluster_status: str
