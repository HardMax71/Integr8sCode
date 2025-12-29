import asyncio
import logging
from typing import Dict, List

from confluent_kafka.admin import AdminClient, NewTopic

from app.settings import get_settings


class AdminUtils:
    """Minimal admin utilities using native AdminClient."""

    def __init__(self, logger: logging.Logger, bootstrap_servers: str | None = None):
        self.logger = logger
        settings = get_settings()
        self._admin = AdminClient(
            {
                "bootstrap.servers": bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS,
                "client.id": "integr8scode-admin",
            }
        )

    @property
    def admin_client(self) -> AdminClient:
        """Get the native AdminClient instance."""
        return self._admin

    async def check_topic_exists(self, topic: str) -> bool:
        """Check if topic exists."""
        try:
            metadata = self._admin.list_topics(timeout=5.0)
            return topic in metadata.topics
        except Exception as e:
            self.logger.error(f"Failed to check topic {topic}: {e}")
            return False

    async def create_topic(self, topic: str, num_partitions: int = 1, replication_factor: int = 1) -> bool:
        """Create a single topic."""
        try:
            new_topic = NewTopic(topic, num_partitions=num_partitions, replication_factor=replication_factor)
            futures = self._admin.create_topics([new_topic], operation_timeout=30.0)

            # Wait for result - result() returns None on success, raises exception on failure
            await asyncio.get_event_loop().run_in_executor(None, lambda: futures[topic].result(timeout=30.0))
            self.logger.info(f"Topic {topic} created successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to create topic {topic}: {e}")
            return False

    async def ensure_topics_exist(self, topics: List[tuple[str, int]]) -> Dict[str, bool]:
        """Ensure topics exist, creating them if necessary."""
        results = {}
        for topic, partitions in topics:
            if await self.check_topic_exists(topic):
                results[topic] = True
            else:
                results[topic] = await self.create_topic(topic, partitions)
        return results

    def get_admin_client(self) -> AdminClient:
        """Get the native AdminClient for direct operations."""
        return self._admin


def create_admin_utils(logger: logging.Logger, bootstrap_servers: str | None = None) -> AdminUtils:
    """Create admin utilities."""
    return AdminUtils(logger, bootstrap_servers)
