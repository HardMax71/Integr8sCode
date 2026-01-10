#!/usr/bin/env python3
"""
Create all required Kafka topics for the Integr8sCode backend.
"""

import asyncio
import os
import sys
from typing import List

from app.core.logging import setup_logger
from app.infrastructure.kafka.topics import get_all_topics, get_topic_configs
from app.settings import Settings
from confluent_kafka import KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

logger = setup_logger(os.environ.get("LOG_LEVEL", "INFO"))


async def create_topics(settings: Settings) -> None:
    """Create all required Kafka topics using provided settings."""

    # Create admin client
    admin_client = AdminClient(
        {
            "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "client.id": "topic-creator",
        }
    )

    try:
        logger.info(f"Connected to Kafka brokers: {settings.KAFKA_BOOTSTRAP_SERVERS}")

        # Get existing topics
        metadata = admin_client.list_topics(timeout=10)
        existing_topics = set(metadata.topics.keys())
        logger.info(f"Existing topics: {existing_topics}")

        # Get all required topics and their configs
        all_topics = get_all_topics()
        topic_configs = get_topic_configs()
        topic_prefix = settings.KAFKA_TOPIC_PREFIX
        logger.info(f"Total required topics: {len(all_topics)} (prefix: '{topic_prefix}')")

        # Create topics
        topics_to_create: List[NewTopic] = []

        for topic in all_topics:
            # Apply topic prefix for consistency with consumers/producers
            topic_name = f"{topic_prefix}{topic.value}"
            if topic_name not in existing_topics:
                # Get config from topic_configs
                config = topic_configs.get(
                    topic,
                    {
                        "num_partitions": 3,
                        "replication_factor": 1,
                        "config": {
                            "retention.ms": "604800000",  # 7 days
                            "compression.type": "gzip",
                        },
                    },
                )

                new_topic = NewTopic(
                    topic=topic_name,
                    num_partitions=config.get("num_partitions", 3),
                    replication_factor=config.get("replication_factor", 1),
                    config=config.get("config", {}),
                )
                topics_to_create.append(new_topic)
                logger.info(f"Will create topic: {topic_name}")
            else:
                logger.info(f"Topic already exists: {topic_name}")

        if topics_to_create:
            try:
                fs = admin_client.create_topics(topics_to_create)
                # Wait for operations to complete
                for topic_name, future in fs.items():
                    try:
                        future.result()  # The result itself is None
                        logger.info(f"Successfully created topic: {topic_name}")
                    except KafkaException as e:
                        logger.warning(f"Failed to create topic {topic_name}: {e}")
            except Exception as e:
                logger.error(f"Error creating topics: {e}")
                raise
        else:
            logger.info("All topics already exist")

        # List final topics
        final_metadata = admin_client.list_topics(timeout=10)
        final_topics = set(final_metadata.topics.keys())
        logger.info(f"Final topics count: {len(final_topics)}")
        for topic_name in sorted(final_topics):
            if not topic_name.startswith("__"):  # Skip internal topics
                logger.info(f"  - {topic_name}")

    finally:
        pass  # AdminClient doesn't need explicit cleanup


async def main() -> None:
    """Main entry point - creates Settings() which reads from env vars then .env file."""
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
