from typing import Any, List, Optional, Set

from app.config import get_settings
from app.core.health_checker import HealthCheck
from app.events.core.consumer_group_names import CONSUMER_GROUP_TOPICS, get_consumer_groups_with_topics
from app.events.kafka.health_check.cb_healthcheck import KafkaCircuitBreakerHealthCheck
from app.events.kafka.health_check.connectivity_healthcheck import KafkaConnectivityHealthCheck
from app.events.kafka.health_check.consumer_healthcheck import KafkaConsumerHealthCheck
from app.events.kafka.health_check.producer_healthcheck import KafkaProducerHealthCheck
from app.events.kafka.health_check.schema_registry_healthcheck import KafkaSchemaRegistryHealthCheck
from app.events.kafka.health_check.topics_healthcheck import KafkaTopicsHealthCheck


async def create_kafka_health_checks(kafka_producer: Optional[Any] = None) -> List[HealthCheck]:
    """Create all Kafka health checks"""
    settings = get_settings()

    # Gather all unique topics from consumer groups
    all_topics: Set[str] = set()
    for topics in CONSUMER_GROUP_TOPICS.values():
        all_topics.update(topics)
    
    health_checks = [
        # Basic connectivity
        KafkaConnectivityHealthCheck(),

        # Topics check
        KafkaTopicsHealthCheck(
            required_topics=list(all_topics)
        ),

        # Producer health
        KafkaProducerHealthCheck(producer=kafka_producer),

        # Circuit breakers
        KafkaCircuitBreakerHealthCheck()
    ]

    # Add consumer health checks for known consumer groups
    for group_id, topics in get_consumer_groups_with_topics():
        health_checks.append(
            KafkaConsumerHealthCheck(
                consumer_group=group_id,
                topics=topics
            )
        )

    # Add Schema Registry check if URL is configured
    if settings.SCHEMA_REGISTRY_URL:
        health_checks.append(KafkaSchemaRegistryHealthCheck())

    return health_checks
