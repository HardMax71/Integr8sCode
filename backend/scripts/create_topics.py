#!/usr/bin/env python3
"""
Create all required Kafka topics for the Integr8sCode backend.

With FastStream, topics are derived from event class names.
This script discovers all event classes and creates their topics.
"""

import asyncio
import os
import sys
from typing import Any

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError
from app.core.logging import setup_logger
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import BaseEvent
from app.settings import Settings

logger = setup_logger(os.environ.get("LOG_LEVEL", "INFO"))


def get_all_event_topics() -> set[str]:
    """Discover all topics from BaseEvent subclasses."""
    topics: set[str] = set()

    def collect_subclasses(cls: type[BaseEvent]) -> None:
        for subclass in cls.__subclasses__():
            # Skip abstract/base classes
            if not subclass.__name__.startswith("_"):
                topics.add(subclass.topic())
            collect_subclasses(subclass)

    collect_subclasses(BaseEvent)
    return topics


def get_infrastructure_topics() -> set[str]:
    """Get infrastructure topics (DLQ) from KafkaTopic enum."""
    return {str(t) for t in KafkaTopic}


def get_topic_config(topic: str) -> dict[str, Any]:
    """Get configuration for a topic based on its name."""
    # DLQ topics need longer retention
    if "dlq" in topic or "dead_letter" in topic:
        return {
            "num_partitions": 3,
            "replication_factor": 1,
            "config": {
                "retention.ms": "1209600000",  # 14 days
                "compression.type": "gzip",
            },
        }

    # Execution-related topics need more partitions
    if "execution" in topic:
        return {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            },
        }

    # Pod events
    if "pod" in topic:
        return {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "86400000",  # 1 day
                "compression.type": "gzip",
            },
        }

    # Default config
    return {
        "num_partitions": 5,
        "replication_factor": 1,
        "config": {
            "retention.ms": "604800000",  # 7 days
            "compression.type": "gzip",
        },
    }


async def create_topics(settings: Settings) -> None:
    """Create all required Kafka topics using provided settings."""

    # Create admin client
    admin_client = AIOKafkaAdminClient(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        client_id="topic-creator",
    )

    try:
        await admin_client.start()
        logger.info(f"Connected to Kafka brokers: {settings.KAFKA_BOOTSTRAP_SERVERS}")

        # Get existing topics
        existing_topics: list[str] = await admin_client.list_topics()
        existing_topics_set = set(existing_topics)
        logger.info(f"Existing topics: {existing_topics_set}")

        # Collect all required topics
        event_topics = get_all_event_topics()
        infra_topics = get_infrastructure_topics()
        all_topics = event_topics | infra_topics

        topic_prefix = settings.KAFKA_TOPIC_PREFIX
        logger.info(f"Total required topics: {len(all_topics)} (prefix: '{topic_prefix}')")

        # Create topics
        topics_to_create: list[NewTopic] = []

        for topic in sorted(all_topics):
            # Apply topic prefix for consistency with consumers/producers
            topic_name = f"{topic_prefix}{topic}"
            if topic_name not in existing_topics_set:
                config = get_topic_config(topic)

                new_topic = NewTopic(
                    name=topic_name,
                    num_partitions=config.get("num_partitions", 3),
                    replication_factor=config.get("replication_factor", 1),
                    topic_configs=config.get("config", {}),
                )
                topics_to_create.append(new_topic)
                logger.info(f"Will create topic: {topic_name}")
            else:
                logger.info(f"Topic already exists: {topic_name}")

        if topics_to_create:
            try:
                await admin_client.create_topics(topics_to_create)
                for topic in topics_to_create:
                    logger.info(f"Successfully created topic: {topic.name}")
            except TopicAlreadyExistsError as e:
                logger.warning(f"Some topics already exist: {e}")
            except Exception as e:
                logger.error(f"Error creating topics: {e}")
                raise
        else:
            logger.info("All topics already exist")

        # List final topics
        final_topics: list[str] = await admin_client.list_topics()
        logger.info(f"Final topics count: {len(final_topics)}")
        for topic_name in sorted(final_topics):
            if not topic_name.startswith("__"):  # Skip internal topics
                logger.info(f"  - {topic_name}")

    finally:
        await admin_client.close()


async def main() -> None:
    """Main entry point - loads settings from config.toml."""
    logger.info("Starting Kafka topic creation...")

    try:
        await create_topics(Settings())
        logger.info("Topic creation completed successfully")
    except Exception as e:
        logger.error(f"Topic creation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Run with proper event loop
    asyncio.run(main())
