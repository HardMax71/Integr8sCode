"""
Kafka connectivity health check implementation.

This module provides health monitoring for Kafka broker connectivity,
ensuring the cluster is reachable and operational.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from aiokafka.admin import AIOKafkaAdminClient

from app.config import get_settings
from app.core.health_checker import (
    HealthCheck,
    HealthCheckConfig,
    HealthCheckResult,
    HealthCheckType,
    HealthStatus,
)
from app.core.logging import logger


@dataclass(frozen=True, slots=True)
class BrokerInfo:
    """Kafka broker information."""
    node_id: int
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class ClusterMetadata:
    """Kafka cluster metadata."""
    brokers: list[BrokerInfo]
    controller_id: int

    @property
    def broker_count(self) -> int:
        """Get the number of brokers in the cluster."""
        return len(self.brokers)


class KafkaConnectivityHealthCheck(HealthCheck):
    """
    Health check for Kafka broker connectivity.
    
    Verifies that the Kafka cluster is accessible and returns
    information about the available brokers and controller.
    """

    def __init__(self, bootstrap_servers: str | None = None) -> None:
        super().__init__(
            name="kafka_connectivity",
            check_type=HealthCheckType.LIVENESS,
            config=HealthCheckConfig(
                timeout_seconds=5.0,
                interval_seconds=30.0,
                failure_threshold=3
            )
        )
        settings = get_settings()
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS

    async def check(self) -> HealthCheckResult:
        try:
            metadata = await self._fetch_cluster_metadata()
            return self._create_healthy_result(metadata)
        except Exception as e:
            logger.error(f"Kafka connectivity check failed: {e}")
            return self._create_unhealthy_result(e)

    async def _fetch_cluster_metadata(self) -> ClusterMetadata:
        async with self._create_admin_client() as client:
            raw_metadata = await client.describe_cluster()

            brokers = [
                BrokerInfo(
                    node_id=broker['node_id'],
                    host=broker['host'],
                    port=broker['port']
                )
                for broker in raw_metadata['brokers']
            ]

            return ClusterMetadata(
                brokers=brokers,
                controller_id=raw_metadata['controller_id']
            )

    @asynccontextmanager
    async def _create_admin_client(self) -> AsyncIterator[AIOKafkaAdminClient]:
        client = AIOKafkaAdminClient(
            bootstrap_servers=self.bootstrap_servers,
            request_timeout_ms=5000,
            connections_max_idle_ms=10000
        )

        try:
            await client.start()
            yield client
        finally:
            await client.close()

    def _create_healthy_result(self, metadata: ClusterMetadata) -> HealthCheckResult:
        return HealthCheckResult(
            name=self.name,
            status=HealthStatus.HEALTHY,
            message=f"Connected to Kafka cluster with {metadata.broker_count} brokers",
            details={
                "broker_count": metadata.broker_count,
                "controller_id": metadata.controller_id,
                "brokers": [
                    {
                        "id": broker.node_id,
                        "host": broker.host,
                        "port": broker.port
                    }
                    for broker in metadata.brokers
                ]
            }
        )

    def _create_unhealthy_result(self, error: Exception) -> HealthCheckResult:
        return HealthCheckResult(
            name=self.name,
            status=HealthStatus.UNHEALTHY,
            message=f"Cannot connect to Kafka brokers: {error}",
            error=type(error).__name__,
            details={"bootstrap_servers": self.bootstrap_servers}
        )
