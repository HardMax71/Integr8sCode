from __future__ import annotations

from typing import AsyncIterator

import redis.asyncio as redis
import structlog
from dishka import Provider, Scope, from_context, provide
from faststream.kafka import KafkaBroker
from faststream.kafka.opentelemetry import KafkaTelemetryMiddleware
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio import config as k8s_config

from app.core.logging import setup_logger
from app.core.metrics import (
    ConnectionMetrics,
    DatabaseMetrics,
    DLQMetrics,
    EventMetrics,
    ExecutionMetrics,
    KubernetesMetrics,
    NotificationMetrics,
    QueueMetrics,
    RateLimitMetrics,
    ReplayMetrics,
    SecurityMetrics,
)
from app.core.security import SecurityService
from app.core.tracing import Tracer
from app.db.repositories import (
    AdminEventsRepository,
    AdminSettingsRepository,
    DLQRepository,
    EventRepository,
    ExecutionRepository,
    NotificationRepository,
    ReplayRepository,
    ResourceAllocationRepository,
    SagaRepository,
    SavedScriptRepository,
    UserRepository,
    UserSettingsRepository,
)
from app.dlq.manager import DLQManager
from app.domain.saga import SagaConfig
from app.events.core import UnifiedProducer
from app.services.admin import AdminEventsService, AdminSettingsService, AdminUserService
from app.services.admin.admin_execution_service import AdminExecutionService
from app.services.auth_service import AuthService
from app.services.event_replay import EventReplayService
from app.services.event_service import EventService
from app.services.execution_queue import ExecutionQueueService
from app.services.execution_service import ExecutionService
from app.services.idempotency import IdempotencyConfig, IdempotencyManager, RedisIdempotencyRepository
from app.services.k8s_worker import KubernetesWorker
from app.services.kafka_event_service import KafkaEventService
from app.services.login_lockout import LoginLockoutService
from app.services.notification_scheduler import NotificationScheduler
from app.services.notification_service import NotificationService
from app.services.pod_monitor import PodEventMapper, PodMonitor, PodMonitorConfig
from app.services.rate_limit_service import RateLimitService
from app.services.result_processor import ResultProcessor
from app.services.runtime_settings import RuntimeSettingsLoader
from app.services.saga import SagaOrchestrator, SagaService
from app.services.saved_script_service import SavedScriptService
from app.services.sse import SSERedisBus, SSEService
from app.services.user_settings_service import UserSettingsService
from app.settings import Settings


class BrokerProvider(Provider):
    """Provides KafkaBroker instance (creation only, no lifecycle management).

    The broker is created here but NOT started. This is required because:
    1. Subscribers must be registered before broker.start()
    2. setup_dishka() must be called before broker.start()

    Lifecycle is managed externally:
    - Workers: FastStream(broker).run() handles start/stop
    - Main app: dishka_lifespan handles broker.start() and broker.stop()
    """

    scope = Scope.APP

    @provide
    def get_broker(
        self, settings: Settings, logger: structlog.stdlib.BoundLogger, _tracer: Tracer,
    ) -> KafkaBroker:
        broker = KafkaBroker(
            settings.KAFKA_BOOTSTRAP_SERVERS,
            logger=logger,
            client_id=f"integr8scode-{settings.SERVICE_NAME}",
            request_timeout_ms=settings.KAFKA_REQUEST_TIMEOUT_MS,
            middlewares=(KafkaTelemetryMiddleware(),),
        )
        logger.info("Kafka broker created")
        return broker


class SettingsProvider(Provider):
    """Provides Settings from context (passed to make_async_container)."""

    settings = from_context(provides=Settings, scope=Scope.APP)


class LoggingProvider(Provider):
    scope = Scope.APP

    @provide
    def get_logger(self, settings: Settings) -> structlog.stdlib.BoundLogger:
        return setup_logger(settings.LOG_LEVEL)



class RedisProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_redis_client(
        self, settings: Settings, logger: structlog.stdlib.BoundLogger
    ) -> AsyncIterator[redis.Redis]:
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
    def get_rate_limit_service(
            self,
            redis_client: redis.Redis,
            settings: Settings,
            rate_limit_metrics: RateLimitMetrics,
    ) -> RateLimitService:
        return RateLimitService(redis_client, settings, rate_limit_metrics)


class CoreServicesProvider(Provider):
    scope = Scope.APP

    @provide
    def get_security_service(self, settings: Settings, security_metrics: SecurityMetrics) -> SecurityService:
        return SecurityService(settings, security_metrics)

    @provide
    def get_tracer(
        self, settings: Settings, logger: structlog.stdlib.BoundLogger,
    ) -> Tracer:
        return Tracer(settings, logger)


class MessagingProvider(Provider):
    scope = Scope.APP

    @provide
    def get_unified_producer(
            self,
            broker: KafkaBroker,
            event_repository: EventRepository,
            logger: structlog.stdlib.BoundLogger,
            event_metrics: EventMetrics,
    ) -> UnifiedProducer:
        return UnifiedProducer(broker, event_repository, logger, event_metrics)

    @provide
    def get_idempotency_repository(self, redis_client: redis.Redis) -> RedisIdempotencyRepository:
        return RedisIdempotencyRepository(redis_client, key_prefix="idempotency")

    @provide
    def get_idempotency_manager(
            self,
            repo: RedisIdempotencyRepository,
            logger: structlog.stdlib.BoundLogger,
            database_metrics: DatabaseMetrics,
    ) -> IdempotencyManager:
        return IdempotencyManager(IdempotencyConfig(), repo, logger, database_metrics)


class DLQProvider(Provider):
    """Provides DLQManager without scheduling. Used by all containers except the DLQ worker."""

    scope = Scope.APP

    @provide
    def get_dlq_manager(
            self,
            broker: KafkaBroker,
            settings: Settings,
            logger: structlog.stdlib.BoundLogger,
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


class KubernetesProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_api_client(
        self, settings: Settings, logger: structlog.stdlib.BoundLogger
    ) -> AsyncIterator[k8s_client.ApiClient]:
        """Provide Kubernetes ApiClient with config loading and cleanup."""
        await k8s_config.load_kube_config(config_file=settings.KUBERNETES_CONFIG_PATH)
        api_client = k8s_client.ApiClient()
        logger.info(f"Kubernetes API host: {api_client.configuration.host}")
        try:
            yield api_client
        finally:
            await api_client.close()


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
    def get_kubernetes_metrics(self, settings: Settings) -> KubernetesMetrics:
        return KubernetesMetrics(settings)

    @provide
    def get_queue_metrics(self, settings: Settings) -> QueueMetrics:
        return QueueMetrics(settings)

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
    """Provides all repository instances.

    Repositories are stateless facades over Beanie document operations.
    Database (with init_beanie already called) is available from context.
    """

    scope = Scope.APP

    @provide
    def get_execution_repository(self, logger: structlog.stdlib.BoundLogger) -> ExecutionRepository:
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
    def get_dlq_repository(self, logger: structlog.stdlib.BoundLogger) -> DLQRepository:
        return DLQRepository(logger)

    @provide
    def get_replay_repository(self, logger: structlog.stdlib.BoundLogger) -> ReplayRepository:
        return ReplayRepository(logger)

    @provide
    def get_event_repository(
            self, logger: structlog.stdlib.BoundLogger, database_metrics: DatabaseMetrics,
    ) -> EventRepository:
        return EventRepository(logger, database_metrics)

    @provide
    def get_user_settings_repository(self, logger: structlog.stdlib.BoundLogger) -> UserSettingsRepository:
        return UserSettingsRepository(logger)

    @provide
    def get_admin_events_repository(self) -> AdminEventsRepository:
        return AdminEventsRepository()

    @provide
    def get_admin_settings_repository(self, logger: structlog.stdlib.BoundLogger) -> AdminSettingsRepository:
        return AdminSettingsRepository(logger)

    @provide
    def get_notification_repository(self, logger: structlog.stdlib.BoundLogger) -> NotificationRepository:
        return NotificationRepository(logger)

    @provide
    def get_user_repository(self) -> UserRepository:
        return UserRepository()


class SSEProvider(Provider):
    """Provides SSE (Server-Sent Events) related services."""

    scope = Scope.APP

    @provide
    def get_sse_redis_bus(
        self,
        redis_client: redis.Redis,
        logger: structlog.stdlib.BoundLogger,
        connection_metrics: ConnectionMetrics,
    ) -> SSERedisBus:
        return SSERedisBus(redis_client, logger, connection_metrics)

    @provide
    def get_sse_service(
            self,
            bus: SSERedisBus,
            execution_repository: ExecutionRepository,
            logger: structlog.stdlib.BoundLogger,
    ) -> SSEService:
        return SSEService(bus=bus, execution_repository=execution_repository, logger=logger)


class AuthProvider(Provider):
    scope = Scope.APP

    @provide
    def get_auth_service(
            self,
            user_repository: UserRepository,
            security_service: SecurityService,
            security_metrics: SecurityMetrics,
            logger: structlog.stdlib.BoundLogger,
            lockout_service: LoginLockoutService,
            runtime_settings: RuntimeSettingsLoader,
            producer: UnifiedProducer,
            settings: Settings,
    ) -> AuthService:
        return AuthService(
            user_repo=user_repository,
            security_service=security_service,
            security_metrics=security_metrics,
            logger=logger,
            lockout_service=lockout_service,
            runtime_settings=runtime_settings,
            producer=producer,
            settings=settings,
        )


class KafkaServicesProvider(Provider):
    """Provides Kafka-related event services used by both main app and workers."""

    scope = Scope.APP

    @provide
    def get_event_service(self, event_repository: EventRepository) -> EventService:
        return EventService(event_repository)

    @provide
    def get_kafka_event_service(
            self,
            kafka_producer: UnifiedProducer,
            settings: Settings,
            logger: structlog.stdlib.BoundLogger,
            event_metrics: EventMetrics,
    ) -> KafkaEventService:
        return KafkaEventService(
            kafka_producer=kafka_producer,
            settings=settings,
            logger=logger,
            event_metrics=event_metrics,
        )


class UserServicesProvider(Provider):
    scope = Scope.APP

    @provide
    def get_user_settings_service(
            self,
            repository: UserSettingsRepository,
            kafka_event_service: KafkaEventService,
            settings: Settings,
            logger: structlog.stdlib.BoundLogger,
    ) -> UserSettingsService:
        return UserSettingsService(repository, kafka_event_service, settings, logger)


class RuntimeSettingsProvider(Provider):
    scope = Scope.APP

    @provide
    def get_runtime_settings_loader(
            self,
            admin_settings_repository: AdminSettingsRepository,
            settings: Settings,
            logger: structlog.stdlib.BoundLogger,
    ) -> RuntimeSettingsLoader:
        return RuntimeSettingsLoader(admin_settings_repository, settings, logger)


class AdminServicesProvider(Provider):
    scope = Scope.APP

    @provide
    def get_login_lockout_service(
            self,
            redis_client: redis.Redis,
            runtime_settings: RuntimeSettingsLoader,
            logger: structlog.stdlib.BoundLogger,
    ) -> LoginLockoutService:
        return LoginLockoutService(redis_client, runtime_settings, logger)

    @provide(scope=Scope.REQUEST)
    def get_admin_events_service(
            self,
            admin_events_repository: AdminEventsRepository,
            event_replay_service: EventReplayService,
            logger: structlog.stdlib.BoundLogger,
    ) -> AdminEventsService:
        return AdminEventsService(admin_events_repository, event_replay_service, logger)

    @provide
    def get_admin_settings_service(
            self,
            admin_settings_repository: AdminSettingsRepository,
            runtime_settings: RuntimeSettingsLoader,
            logger: structlog.stdlib.BoundLogger,
    ) -> AdminSettingsService:
        return AdminSettingsService(admin_settings_repository, runtime_settings, logger)

    @provide
    def get_notification_service(
            self,
            notification_repository: NotificationRepository,
            kafka_event_service: KafkaEventService,
            sse_redis_bus: SSERedisBus,
            settings: Settings,
            logger: structlog.stdlib.BoundLogger,
            notification_metrics: NotificationMetrics,
    ) -> NotificationService:
        return NotificationService(
            notification_repository=notification_repository,
            event_service=kafka_event_service,
            sse_bus=sse_redis_bus,
            settings=settings,
            logger=logger,
            notification_metrics=notification_metrics,
        )

    @provide
    def get_notification_scheduler(
            self,
            notification_repository: NotificationRepository,
            notification_service: NotificationService,
            logger: structlog.stdlib.BoundLogger,
    ) -> NotificationScheduler:
        return NotificationScheduler(
            notification_repository=notification_repository,
            notification_service=notification_service,
            logger=logger,
        )


def _create_default_saga_config() -> SagaConfig:
    """Factory for default SagaConfig used by orchestrators."""
    return SagaConfig(
        name="main-orchestrator",
        timeout_seconds=300,
        max_retries=3,
        retry_delay_seconds=5,
        enable_compensation=True,
        store_events=True,
        publish_commands=True,
    )


class ExecutionQueueProvider(Provider):
    scope = Scope.APP

    @provide
    def get_execution_queue_service(
        self,
        redis_client: redis.Redis,
        logger: structlog.stdlib.BoundLogger,
        queue_metrics: QueueMetrics,
    ) -> ExecutionQueueService:
        return ExecutionQueueService(redis_client, logger, queue_metrics)


class BusinessServicesProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def get_saga_service(
            self,
            saga_repository: SagaRepository,
            execution_repository: ExecutionRepository,
            saga_orchestrator: SagaOrchestrator,
            logger: structlog.stdlib.BoundLogger,
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
            kafka_producer: UnifiedProducer,
            settings: Settings,
            logger: structlog.stdlib.BoundLogger,
            execution_metrics: ExecutionMetrics,
            idempotency_manager: IdempotencyManager,
            runtime_settings: RuntimeSettingsLoader,
    ) -> ExecutionService:
        return ExecutionService(
            execution_repo=execution_repository,
            producer=kafka_producer,
            settings=settings,
            logger=logger,
            execution_metrics=execution_metrics,
            idempotency_manager=idempotency_manager,
            runtime_settings=runtime_settings,
        )

    @provide
    def get_saved_script_service(
            self, saved_script_repository: SavedScriptRepository, logger: structlog.stdlib.BoundLogger
    ) -> SavedScriptService:
        return SavedScriptService(saved_script_repository, logger)

    @provide
    def get_admin_user_service(
            self,
            user_repository: UserRepository,
            event_service: EventService,
            execution_service: ExecutionService,
            rate_limit_service: RateLimitService,
            security_service: SecurityService,
            security_metrics: SecurityMetrics,
            logger: structlog.stdlib.BoundLogger,
    ) -> AdminUserService:
        return AdminUserService(
            user_repository=user_repository,
            event_service=event_service,
            execution_service=execution_service,
            rate_limit_service=rate_limit_service,
            security_service=security_service,
            security_metrics=security_metrics,
            logger=logger,
        )

    @provide
    def get_admin_execution_service(
            self,
            execution_repository: ExecutionRepository,
            queue_service: ExecutionQueueService,
            runtime_settings: RuntimeSettingsLoader,
            logger: structlog.stdlib.BoundLogger,
    ) -> AdminExecutionService:
        return AdminExecutionService(
            execution_repo=execution_repository,
            queue_service=queue_service,
            runtime_settings=runtime_settings,
            logger=logger,
        )


class K8sWorkerProvider(Provider):
    scope = Scope.APP

    @provide
    def get_kubernetes_worker(
        self,
        api_client: k8s_client.ApiClient,
        kafka_producer: UnifiedProducer,
        settings: Settings,
        logger: structlog.stdlib.BoundLogger,
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
        logger: structlog.stdlib.BoundLogger,
        api_client: k8s_client.ApiClient,
    ) -> PodEventMapper:
        return PodEventMapper(logger=logger, k8s_api=k8s_client.CoreV1Api(api_client))

    @provide
    def get_pod_monitor_config(self, settings: Settings) -> PodMonitorConfig:
        return PodMonitorConfig(
            namespace=settings.K8S_NAMESPACE,
            kubeconfig_path=settings.KUBERNETES_CONFIG_PATH,
        )

    @provide
    def get_pod_monitor(
        self,
        config: PodMonitorConfig,
        kafka_event_service: KafkaEventService,
        api_client: k8s_client.ApiClient,
        logger: structlog.stdlib.BoundLogger,
        event_mapper: PodEventMapper,
        kubernetes_metrics: KubernetesMetrics,
    ) -> PodMonitor:
        return PodMonitor(
            config=config,
            kafka_event_service=kafka_event_service,
            logger=logger,
            api_client=api_client,
            event_mapper=event_mapper,
            kubernetes_metrics=kubernetes_metrics,
        )


class SagaOrchestratorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_saga_orchestrator(
        self,
        saga_repository: SagaRepository,
        kafka_producer: UnifiedProducer,
        resource_allocation_repository: ResourceAllocationRepository,
        logger: structlog.stdlib.BoundLogger,
        queue_service: ExecutionQueueService,
        runtime_settings: RuntimeSettingsLoader,
    ) -> SagaOrchestrator:
        return SagaOrchestrator(
            config=_create_default_saga_config(),
            saga_repository=saga_repository,
            producer=kafka_producer,
            resource_allocation_repository=resource_allocation_repository,
            logger=logger,
            queue_service=queue_service,
            runtime_settings=runtime_settings,
        )


class ResultProcessorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_result_processor(
        self,
        execution_repo: ExecutionRepository,
        kafka_producer: UnifiedProducer,
        settings: Settings,
        logger: structlog.stdlib.BoundLogger,
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
            kafka_producer: UnifiedProducer,
            replay_metrics: ReplayMetrics,
            logger: structlog.stdlib.BoundLogger,
    ) -> EventReplayService:
        return EventReplayService(
            repository=replay_repository,
            producer=kafka_producer,
            replay_metrics=replay_metrics,
            logger=logger,
        )
