from __future__ import annotations

import logging
from typing import AsyncIterator

import redis.asyncio as redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from beanie import init_beanie
from dishka import Provider, Scope, from_context, provide
from faststream.kafka import KafkaBroker
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio import config as k8s_config
from kubernetes_asyncio.client.rest import ApiException
from pymongo.asynchronous.mongo_client import AsyncMongoClient

from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.metrics import (
    ConnectionMetrics,
    CoordinatorMetrics,
    DatabaseMetrics,
    DLQMetrics,
    EventMetrics,
    ExecutionMetrics,
    HealthMetrics,
    KubernetesMetrics,
    NotificationMetrics,
    RateLimitMetrics,
    ReplayMetrics,
    SecurityMetrics,
)
from app.core.security import SecurityService
from app.core.tracing import TracerManager
from app.db.docs import ALL_DOCUMENTS
from app.db.repositories import (
    EventRepository,
    ExecutionRepository,
    NotificationRepository,
    SagaRepository,
    SavedScriptRepository,
    SSERepository,
    UserRepository,
)
from app.db.repositories.admin.admin_events_repository import AdminEventsRepository
from app.db.repositories.admin.admin_settings_repository import AdminSettingsRepository
from app.db.repositories.admin.admin_user_repository import AdminUserRepository
from app.db.repositories.dlq_repository import DLQRepository
from app.db.repositories.replay_repository import ReplayRepository
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.db.repositories.user_settings_repository import UserSettingsRepository
from app.dlq.manager import DLQManager
from app.domain.rate_limit import RateLimitConfig
from app.domain.saga.models import SagaConfig
from app.events.core import EventPublisher
from app.services.admin import AdminEventsService, AdminSettingsService, AdminUserService
from app.services.auth_service import AuthService
from app.services.coordinator.coordinator import ExecutionCoordinator
from app.services.event_replay.replay_service import EventReplayService
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService
from app.services.grafana_alert_processor import GrafanaAlertProcessor
from app.services.idempotency import IdempotencyConfig, IdempotencyManager, IdempotencyMiddleware
from app.services.idempotency.redis_repository import RedisIdempotencyRepository
from app.services.k8s_worker import KubernetesWorker
from app.services.notification_scheduler import NotificationScheduler
from app.services.notification_service import NotificationService
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper
from app.services.pod_monitor.monitor import ErrorType, PodMonitor
from app.services.rate_limit_service import RateLimitService
from app.services.result_processor.processor import ResultProcessor
from app.services.result_processor.resource_cleaner import ResourceCleaner
from app.services.saga import SagaOrchestrator
from app.services.saga.saga_service import SagaService
from app.services.saved_script_service import SavedScriptService
from app.services.sse.redis_bus import SSERedisBus
from app.services.sse.sse_service import SSEService
from app.services.user_settings_service import UserSettingsService
from app.settings import Settings


class SettingsProvider(Provider):
    """Provides Settings from context (passed to make_async_container)."""

    settings = from_context(provides=Settings, scope=Scope.APP)


class LoggingProvider(Provider):
    scope = Scope.APP

    @provide
    def get_logger(self, settings: Settings) -> logging.Logger:
        return setup_logger(settings.LOG_LEVEL)


class RedisProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_redis_client(self, settings: Settings, logger: logging.Logger) -> AsyncIterator[redis.Redis]:
        # Create Redis client - it will automatically use the current event loop
        client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            ssl=settings.REDIS_SSL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=settings.REDIS_DECODE_RESPONSES,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        # Test connection
        await client.ping()  # type: ignore[misc]  # redis-py returns Awaitable[bool] | bool
        logger.info(f"Redis connected: {settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}")
        try:
            yield client
        finally:
            await client.aclose()

    @provide
    async def get_rate_limit_service(
            self,
            redis_client: redis.Redis,
            settings: Settings,
            rate_limit_metrics: RateLimitMetrics,
            logger: logging.Logger,
    ) -> RateLimitService:
        service = RateLimitService(redis_client, settings, rate_limit_metrics)
        try:
            config_key = f"{settings.RATE_LIMIT_REDIS_PREFIX}config"
            existing_config = await redis_client.get(config_key)
            if not existing_config:
                logger.info("Initializing default rate limit configuration in Redis")
                default_config = RateLimitConfig.get_default_config()
                await service.update_config(default_config)
                logger.info(f"Initialized {len(default_config.default_rules)} default rate limit rules")
        except Exception as e:
            logger.error(f"Failed to initialize rate limits: {e}")
        return service


class DatabaseProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_database(self, settings: Settings, logger: logging.Logger) -> AsyncIterator[Database]:
        client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
            settings.MONGODB_URL, tz_aware=True, serverSelectionTimeoutMS=5000
        )
        database = client[settings.DATABASE_NAME]
        await init_beanie(database=database, document_models=ALL_DOCUMENTS)
        logger.info(f"MongoDB connected and Beanie initialized: {settings.DATABASE_NAME}")
        try:
            yield database
        finally:
            await client.close()


class CoreServicesProvider(Provider):
    scope = Scope.APP

    @provide
    def get_security_service(self, settings: Settings) -> SecurityService:
        return SecurityService(settings)

    @provide
    def get_tracer_manager(self, settings: Settings) -> TracerManager:
        return TracerManager(tracer_name=settings.TRACING_SERVICE_NAME)


class MessagingProvider(Provider):
    scope = Scope.APP

    broker = from_context(provides=KafkaBroker, scope=Scope.APP)

    @provide
    def get_event_publisher(
            self,
            broker: KafkaBroker,
            event_repository: EventRepository,
            logger: logging.Logger,
            settings: Settings,
    ) -> EventPublisher:
        return EventPublisher(broker, event_repository, logger, settings)

    @provide
    def get_idempotency_repository(self, redis_client: redis.Redis) -> RedisIdempotencyRepository:
        return RedisIdempotencyRepository(redis_client, key_prefix="idempotency")

    @provide
    def get_idempotency_manager(
            self, repo: RedisIdempotencyRepository, logger: logging.Logger, database_metrics: DatabaseMetrics
    ) -> IdempotencyManager:
        return IdempotencyManager(IdempotencyConfig(), repo, logger, database_metrics)


class IdempotencyMiddlewareProvider(Provider):
    """Provides APP-scoped IdempotencyMiddleware for broker registration."""

    scope = Scope.APP

    @provide
    def get_middleware(self, redis_client: redis.Redis, settings: Settings) -> IdempotencyMiddleware:
        return IdempotencyMiddleware(redis_client, settings.KAFKA_TOPIC_PREFIX)


class DLQProvider(Provider):
    """Provides DLQManager without scheduling. Used by all containers except the DLQ worker."""

    scope = Scope.APP

    @provide
    def get_dlq_manager(
            self,
            broker: KafkaBroker,
            settings: Settings,
            logger: logging.Logger,
            dlq_metrics: DLQMetrics,
            repository: DLQRepository,
    ) -> DLQManager:
        return DLQManager(
            settings=settings,
            broker=broker,
            logger=logger,
            dlq_metrics=dlq_metrics,
            repository=repository,
        )


class DLQWorkerProvider(Provider):
    """Provides DLQManager with APScheduler-managed retry monitoring.

    Used by the DLQ worker container only. DLQManager configures its own
    retry policies and filters; the provider only handles scheduling.
    """

    scope = Scope.APP

    @provide
    async def get_dlq_manager(
            self,
            broker: KafkaBroker,
            settings: Settings,
            logger: logging.Logger,
            dlq_metrics: DLQMetrics,
            repository: DLQRepository,
            database: Database,
    ) -> AsyncIterator[DLQManager]:
        manager = DLQManager(
            settings=settings,
            broker=broker,
            logger=logger,
            dlq_metrics=dlq_metrics,
            repository=repository,
        )

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            manager.process_monitoring_cycle,
            trigger="interval",
            seconds=10,
            id="dlq_monitor_retries",
            max_instances=1,
            misfire_grace_time=60,
        )
        scheduler.start()
        logger.info("DLQManager retry monitor started (APScheduler interval=10s)")

        try:
            yield manager
        finally:
            scheduler.shutdown(wait=False)
            logger.info("DLQManager retry monitor stopped")


class KubernetesProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_api_client(self, settings: Settings, logger: logging.Logger) -> AsyncIterator[k8s_client.ApiClient]:
        """Provide Kubernetes ApiClient with config loading and cleanup."""
        await k8s_config.load_kube_config(config_file=settings.KUBERNETES_CONFIG_PATH)
        api_client = k8s_client.ApiClient()
        logger.info(f"Kubernetes API host: {api_client.configuration.host}")
        try:
            yield api_client
        finally:
            await api_client.close()


class ResourceCleanerProvider(Provider):
    scope = Scope.APP

    @provide
    def get_resource_cleaner(self, api_client: k8s_client.ApiClient, logger: logging.Logger) -> ResourceCleaner:
        return ResourceCleaner(api_client=api_client, logger=logger)


class MetricsProvider(Provider):
    """Provides all metrics instances via DI (no contextvars needed)."""

    scope = Scope.APP

    @provide
    def get_event_metrics(self, settings: Settings) -> EventMetrics:
        return EventMetrics(settings)

    @provide
    def get_connection_metrics(self, settings: Settings) -> ConnectionMetrics:
        return ConnectionMetrics(settings)

    @provide
    def get_rate_limit_metrics(self, settings: Settings) -> RateLimitMetrics:
        return RateLimitMetrics(settings)

    @provide
    def get_execution_metrics(self, settings: Settings) -> ExecutionMetrics:
        return ExecutionMetrics(settings)

    @provide
    def get_database_metrics(self, settings: Settings) -> DatabaseMetrics:
        return DatabaseMetrics(settings)

    @provide
    def get_health_metrics(self, settings: Settings) -> HealthMetrics:
        return HealthMetrics(settings)

    @provide
    def get_kubernetes_metrics(self, settings: Settings) -> KubernetesMetrics:
        return KubernetesMetrics(settings)

    @provide
    def get_coordinator_metrics(self, settings: Settings) -> CoordinatorMetrics:
        return CoordinatorMetrics(settings)

    @provide
    def get_dlq_metrics(self, settings: Settings) -> DLQMetrics:
        return DLQMetrics(settings)

    @provide
    def get_notification_metrics(self, settings: Settings) -> NotificationMetrics:
        return NotificationMetrics(settings)

    @provide
    def get_replay_metrics(self, settings: Settings) -> ReplayMetrics:
        return ReplayMetrics(settings)

    @provide
    def get_security_metrics(self, settings: Settings) -> SecurityMetrics:
        return SecurityMetrics(settings)


class RepositoryProvider(Provider):
    """Provides all repository instances. Repositories are stateless facades over database operations."""

    scope = Scope.APP

    @provide
    def get_execution_repository(self, logger: logging.Logger) -> ExecutionRepository:
        return ExecutionRepository(logger)

    @provide
    def get_saga_repository(self) -> SagaRepository:
        return SagaRepository()

    @provide
    def get_resource_allocation_repository(self) -> ResourceAllocationRepository:
        return ResourceAllocationRepository()

    @provide
    def get_saved_script_repository(self) -> SavedScriptRepository:
        return SavedScriptRepository()

    @provide
    def get_dlq_repository(self, logger: logging.Logger) -> DLQRepository:
        return DLQRepository(logger)

    @provide
    def get_replay_repository(self, logger: logging.Logger) -> ReplayRepository:
        return ReplayRepository(logger)

    @provide
    def get_event_repository(self, logger: logging.Logger) -> EventRepository:
        return EventRepository(logger)

    @provide
    def get_user_settings_repository(self, logger: logging.Logger) -> UserSettingsRepository:
        return UserSettingsRepository(logger)

    @provide
    def get_admin_events_repository(self) -> AdminEventsRepository:
        return AdminEventsRepository()

    @provide
    def get_admin_settings_repository(self, logger: logging.Logger) -> AdminSettingsRepository:
        return AdminSettingsRepository(logger)

    @provide
    def get_admin_user_repository(self, security_service: SecurityService) -> AdminUserRepository:
        return AdminUserRepository(security_service)

    @provide
    def get_notification_repository(self, logger: logging.Logger) -> NotificationRepository:
        return NotificationRepository(logger)

    @provide
    def get_sse_repository(self) -> SSERepository:
        return SSERepository()

    @provide
    def get_user_repository(self) -> UserRepository:
        return UserRepository()


class SSEProvider(Provider):
    """Provides SSE (Server-Sent Events) related services."""

    scope = Scope.APP

    @provide
    def get_sse_redis_bus(self, redis_client: redis.Redis, logger: logging.Logger) -> SSERedisBus:
        return SSERedisBus(redis_client, logger)

    @provide(scope=Scope.REQUEST)
    def get_sse_service(
            self,
            sse_repository: SSERepository,
            sse_redis_bus: SSERedisBus,
            settings: Settings,
            logger: logging.Logger,
            connection_metrics: ConnectionMetrics,
    ) -> SSEService:
        return SSEService(
            repository=sse_repository,
            sse_bus=sse_redis_bus,
            settings=settings,
            logger=logger,
            connection_metrics=connection_metrics,
        )


class AuthProvider(Provider):
    scope = Scope.APP

    @provide
    def get_auth_service(
            self, user_repository: UserRepository, security_service: SecurityService, logger: logging.Logger
    ) -> AuthService:
        return AuthService(user_repository, security_service, logger)


class KafkaServicesProvider(Provider):
    """Provides Kafka-related event services used by both main app and workers."""

    scope = Scope.APP

    @provide
    def get_event_service(self, event_repository: EventRepository) -> EventService:
        return EventService(event_repository)


class UserServicesProvider(Provider):
    scope = Scope.APP

    @provide
    def get_user_settings_service(
            self,
            repository: UserSettingsRepository,
            settings: Settings,
            logger: logging.Logger,
    ) -> UserSettingsService:
        return UserSettingsService(repository, settings, logger)


class AdminServicesProvider(Provider):
    scope = Scope.APP

    @provide(scope=Scope.REQUEST)
    def get_admin_events_service(
            self,
            admin_events_repository: AdminEventsRepository,
            event_replay_service: EventReplayService,
            logger: logging.Logger,
    ) -> AdminEventsService:
        return AdminEventsService(admin_events_repository, event_replay_service, logger)

    @provide
    def get_admin_settings_service(
            self,
            admin_settings_repository: AdminSettingsRepository,
            logger: logging.Logger,
    ) -> AdminSettingsService:
        return AdminSettingsService(admin_settings_repository, logger)

    @provide
    def get_notification_service(
            self,
            notification_repository: NotificationRepository,
            sse_redis_bus: SSERedisBus,
            settings: Settings,
            logger: logging.Logger,
            notification_metrics: NotificationMetrics,
    ) -> NotificationService:
        return NotificationService(
            notification_repository=notification_repository,
            sse_bus=sse_redis_bus,
            settings=settings,
            logger=logger,
            notification_metrics=notification_metrics,
        )

    @provide
    async def get_notification_scheduler(
            self,
            notification_repository: NotificationRepository,
            notification_service: NotificationService,
            logger: logging.Logger,
            database: Database,  # ensures init_beanie completes before scheduler starts
    ) -> AsyncIterator[NotificationScheduler]:

        scheduler_service = NotificationScheduler(
            notification_repository=notification_repository,
            notification_service=notification_service,
            logger=logger,
        )

        apscheduler = AsyncIOScheduler()
        apscheduler.add_job(
            scheduler_service.process_due_notifications,
            trigger="interval",
            seconds=15,
            id="process_due_notifications",
            max_instances=1,
            misfire_grace_time=60,
        )
        apscheduler.start()
        logger.info("NotificationScheduler started (APScheduler interval=15s)")

        try:
            yield scheduler_service
        finally:
            apscheduler.shutdown(wait=False)
            logger.info("NotificationScheduler stopped")

    @provide
    def get_grafana_alert_processor(
            self,
            notification_service: NotificationService,
            logger: logging.Logger,
    ) -> GrafanaAlertProcessor:
        return GrafanaAlertProcessor(notification_service, logger)


def _create_default_saga_config() -> SagaConfig:
    """Factory for default SagaConfig used by orchestrators.

    Note: publish_commands=False because the coordinator worker handles
    publishing CreatePodCommand events. The saga orchestrator tracks state
    and handles completion events without duplicating command publishing.
    """
    return SagaConfig(
        name="main-orchestrator",
        timeout_seconds=300,
        max_retries=3,
        retry_delay_seconds=5,
        enable_compensation=True,
        store_events=True,
        publish_commands=False,
    )


class BusinessServicesProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def get_saga_service(
            self,
            saga_repository: SagaRepository,
            execution_repository: ExecutionRepository,
            saga_orchestrator: SagaOrchestrator,
            logger: logging.Logger,
    ) -> SagaService:
        return SagaService(
            saga_repo=saga_repository,
            execution_repo=execution_repository,
            orchestrator=saga_orchestrator,
            logger=logger,
        )

    @provide
    def get_execution_service(
            self,
            execution_repository: ExecutionRepository,
            kafka_producer: EventPublisher,
            event_repository: EventRepository,
            settings: Settings,
            logger: logging.Logger,
            execution_metrics: ExecutionMetrics,
    ) -> ExecutionService:
        return ExecutionService(
            execution_repo=execution_repository,
            producer=kafka_producer,
            event_repository=event_repository,
            settings=settings,
            logger=logger,
            execution_metrics=execution_metrics,
        )

    @provide
    def get_saved_script_service(
            self, saved_script_repository: SavedScriptRepository, logger: logging.Logger
    ) -> SavedScriptService:
        return SavedScriptService(saved_script_repository, logger)

    @provide
    def get_admin_user_service(
            self,
            admin_user_repository: AdminUserRepository,
            event_service: EventService,
            execution_service: ExecutionService,
            rate_limit_service: RateLimitService,
            security_service: SecurityService,
            logger: logging.Logger,
    ) -> AdminUserService:
        return AdminUserService(
            user_repository=admin_user_repository,
            event_service=event_service,
            execution_service=execution_service,
            rate_limit_service=rate_limit_service,
            security_service=security_service,
            logger=logger,
        )


class CoordinatorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_execution_coordinator(
        self,
        producer: EventPublisher,
        execution_repository: ExecutionRepository,
        logger: logging.Logger,
        coordinator_metrics: CoordinatorMetrics,
    ) -> ExecutionCoordinator:
        return ExecutionCoordinator(
            producer=producer,
            execution_repository=execution_repository,
            logger=logger,
            coordinator_metrics=coordinator_metrics,
        )


class K8sWorkerProvider(Provider):
    scope = Scope.APP

    @provide
    def get_kubernetes_worker(
        self,
        api_client: k8s_client.ApiClient,
        kafka_producer: EventPublisher,
        settings: Settings,
        logger: logging.Logger,
        event_metrics: EventMetrics,
    ) -> KubernetesWorker:
        return KubernetesWorker(
            api_client=api_client,
            producer=kafka_producer,
            settings=settings,
            logger=logger,
            event_metrics=event_metrics,
        )


class PodMonitorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_event_mapper(
        self,
        logger: logging.Logger,
        api_client: k8s_client.ApiClient,
    ) -> PodEventMapper:
        return PodEventMapper(logger=logger, k8s_api=k8s_client.CoreV1Api(api_client))

    @provide
    async def get_pod_monitor(
        self,
        producer: EventPublisher,
        api_client: k8s_client.ApiClient,
        logger: logging.Logger,
        event_mapper: PodEventMapper,
        kubernetes_metrics: KubernetesMetrics,
        database: Database,
    ) -> AsyncIterator[PodMonitor]:

        config = PodMonitorConfig()
        monitor = PodMonitor(
            config=config,
            producer=producer,
            logger=logger,
            api_client=api_client,
            event_mapper=event_mapper,
            kubernetes_metrics=kubernetes_metrics,
        )

        async def _watch_cycle() -> None:
            try:
                await monitor.watch_pod_events()
            except ApiException as e:
                if e.status == 410:
                    logger.warning("Resource version expired, resetting watch cursor")
                    monitor._last_resource_version = None
                    kubernetes_metrics.record_pod_monitor_watch_error(ErrorType.RESOURCE_VERSION_EXPIRED)
                else:
                    logger.error(f"API error in watch: {e}")
                    kubernetes_metrics.record_pod_monitor_watch_error(ErrorType.API_ERROR)
                kubernetes_metrics.increment_pod_monitor_watch_reconnects()
            except Exception as e:
                logger.error(f"Unexpected error in watch: {e}", exc_info=True)
                kubernetes_metrics.record_pod_monitor_watch_error(ErrorType.UNEXPECTED)
                kubernetes_metrics.increment_pod_monitor_watch_reconnects()

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            _watch_cycle,
            trigger="interval",
            seconds=5,
            id="pod_monitor_watch",
            max_instances=1,
            misfire_grace_time=60,
        )
        scheduler.start()
        logger.info("PodMonitor scheduler started (list-then-watch)")

        try:
            yield monitor
        finally:
            scheduler.shutdown(wait=False)


class SagaOrchestratorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_saga_orchestrator(
        self,
        saga_repository: SagaRepository,
        kafka_producer: EventPublisher,
        resource_allocation_repository: ResourceAllocationRepository,
        logger: logging.Logger,
    ) -> SagaOrchestrator:
        return SagaOrchestrator(
            config=_create_default_saga_config(),
            saga_repository=saga_repository,
            producer=kafka_producer,
            resource_allocation_repository=resource_allocation_repository,
            logger=logger,
        )


class SagaWorkerProvider(Provider):
    """Provides SagaOrchestrator with APScheduler-managed timeout checking.

    Used by the saga worker container only. The main app container uses
    SagaOrchestratorProvider (no scheduler needed).
    """

    scope = Scope.APP

    @provide
    async def get_saga_orchestrator(
        self,
        saga_repository: SagaRepository,
        kafka_producer: EventPublisher,
        resource_allocation_repository: ResourceAllocationRepository,
        logger: logging.Logger,
        database: Database,
    ) -> AsyncIterator[SagaOrchestrator]:

        orchestrator = SagaOrchestrator(
            config=_create_default_saga_config(),
            saga_repository=saga_repository,
            producer=kafka_producer,
            resource_allocation_repository=resource_allocation_repository,
            logger=logger,
        )

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            orchestrator.check_timeouts,
            trigger="interval",
            seconds=30,
            id="saga_check_timeouts",
            max_instances=1,
            misfire_grace_time=60,
        )
        scheduler.start()
        logger.info("SagaOrchestrator timeout scheduler started (APScheduler interval=30s)")

        try:
            yield orchestrator
        finally:
            scheduler.shutdown(wait=False)
            logger.info("SagaOrchestrator timeout scheduler stopped")


class ResultProcessorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_result_processor(
        self,
        execution_repo: ExecutionRepository,
        kafka_producer: EventPublisher,
        settings: Settings,
        logger: logging.Logger,
        execution_metrics: ExecutionMetrics,
    ) -> ResultProcessor:
        return ResultProcessor(
            execution_repo=execution_repo,
            producer=kafka_producer,
            settings=settings,
            logger=logger,
            execution_metrics=execution_metrics,
        )


class EventReplayProvider(Provider):
    scope = Scope.APP

    @provide
    def get_event_replay_service(
            self,
            replay_repository: ReplayRepository,
            kafka_producer: EventPublisher,
            replay_metrics: ReplayMetrics,
            logger: logging.Logger,
    ) -> EventReplayService:
        return EventReplayService(
            repository=replay_repository,
            producer=kafka_producer,
            replay_metrics=replay_metrics,
            logger=logger,
        )


class EventReplayWorkerProvider(Provider):
    """Provides EventReplayService with APScheduler-managed session cleanup.

    Used by the event replay worker container only. The main app container
    uses EventReplayProvider (no scheduled cleanup needed).
    """

    scope = Scope.APP

    @provide
    async def get_event_replay_service(
            self,
            replay_repository: ReplayRepository,
            kafka_producer: EventPublisher,
            replay_metrics: ReplayMetrics,
            logger: logging.Logger,
            database: Database,
    ) -> AsyncIterator[EventReplayService]:

        service = EventReplayService(
            repository=replay_repository,
            producer=kafka_producer,
            replay_metrics=replay_metrics,
            logger=logger,
        )

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            service.cleanup_old_sessions,
            trigger="interval",
            hours=6,
            kwargs={"older_than_hours": 48},
            id="replay_cleanup_old_sessions",
            max_instances=1,
            misfire_grace_time=300,
        )
        scheduler.start()
        logger.info("EventReplayService cleanup scheduler started (APScheduler interval=6h)")

        try:
            yield service
        finally:
            scheduler.shutdown(wait=False)
            logger.info("EventReplayService cleanup scheduler stopped")
