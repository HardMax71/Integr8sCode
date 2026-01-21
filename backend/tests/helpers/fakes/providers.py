"""Fake providers for unit testing with DI container."""

import logging

import fakeredis.aioredis
import redis.asyncio as redis
from aiokafka import AIOKafkaProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from dishka import Provider, Scope, provide
from kubernetes import client as k8s_client
from kubernetes import watch as k8s_watch

from tests.helpers.fakes.kafka import FakeAIOKafkaProducer
from tests.helpers.fakes.kubernetes import (
    FakeK8sApiClient,
    FakeK8sAppsV1Api,
    FakeK8sCoreV1Api,
    FakeK8sWatch,
)
from tests.helpers.fakes.schema_registry import FakeSchemaRegistryManager


class FakeBoundaryClientProvider(Provider):
    """Fake boundary clients for unit testing.

    Overrides BoundaryClientProvider - provides fake implementations
    for Redis, Kafka, and K8s clients so tests can run without external deps.
    """

    scope = Scope.APP

    @provide
    def get_redis_client(self, logger: logging.Logger) -> redis.Redis:
        logger.info("Using FakeRedis for testing")
        return fakeredis.aioredis.FakeRedis(decode_responses=False)

    @provide
    def get_kafka_producer_client(self) -> AIOKafkaProducer:
        return FakeAIOKafkaProducer()

    @provide
    def get_k8s_api_client(self, logger: logging.Logger) -> k8s_client.ApiClient:
        logger.info("Using FakeK8sApiClient for testing")
        return FakeK8sApiClient()

    @provide
    def get_k8s_core_v1_api(self, api_client: k8s_client.ApiClient) -> k8s_client.CoreV1Api:
        return FakeK8sCoreV1Api(api_client=api_client)

    @provide
    def get_k8s_apps_v1_api(self, api_client: k8s_client.ApiClient) -> k8s_client.AppsV1Api:
        return FakeK8sAppsV1Api(api_client=api_client)

    @provide
    def get_k8s_watch(self) -> k8s_watch.Watch:
        return FakeK8sWatch()


class FakeSchemaRegistryProvider(Provider):
    """Fake Schema Registry provider - must be placed after EventProvider to override."""

    scope = Scope.APP

    @provide
    def get_schema_registry(self, logger: logging.Logger) -> SchemaRegistryManager:
        logger.info("Using FakeSchemaRegistryManager for testing")
        return FakeSchemaRegistryManager(logger=logger)  # type: ignore[return-value]
