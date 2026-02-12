#!/usr/bin/env python3
"""
Create all required Kafka topics for the Integr8sCode backend.

Topics are created with Kafka broker defaults (partitions, replication, retention).
Configure these via broker-level settings, not in application code.
"""

import asyncio
import os
import sys

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError
from app.core.logging import setup_logger
from app.domain.enums import EventType
from app.settings import Settings

logger = setup_logger(os.environ.get("LOG_LEVEL", "INFO"))


async def create_topics(settings: Settings) -> None:
    """Create all required Kafka topics using broker defaults."""

    admin_client = AIOKafkaAdminClient(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        client_id="topic-creator",
    )

    try:
        await admin_client.start()
        logger.info(f"Connected to Kafka brokers: {settings.KAFKA_BOOTSTRAP_SERVERS}")

        existing_topics: list[str] = await admin_client.list_topics()
        existing_topics_set = set(existing_topics)

        all_topics = {str(et) for et in EventType}
        topic_prefix = settings.KAFKA_TOPIC_PREFIX
        logger.info(f"Total required topics: {len(all_topics)} (prefix: '{topic_prefix}')")

        topics_to_create: list[NewTopic] = []

        for topic in all_topics:
            topic_name = f"{topic_prefix}{topic}"
            if topic_name not in existing_topics_set:
                topics_to_create.append(NewTopic(name=topic_name, num_partitions=-1, replication_factor=-1))
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

        final_topics: list[str] = await admin_client.list_topics()
        logger.info(f"Final topics count: {len(final_topics)}")
        for topic_name in sorted(final_topics):
            if not topic_name.startswith("__"):
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
    asyncio.run(main())
