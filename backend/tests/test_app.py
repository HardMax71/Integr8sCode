from __future__ import annotations

"""
Test-only FastAPI app that mounts the same routes but wires lightweight fakes.

Use this app in in-process API tests to exercise route code and collect
coverage without external dependencies (Mongo/Redis/Kafka/K8s).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from dishka import Provider, Scope, provide
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from app.api.rate_limit import check_rate_limit
from app.api.routes import (
    alertmanager,
    auth,
    dlq,
    events,
    execution,
    health,
    notifications,
    replay,
    saga,
    saved_scripts,
    sse,
    user_settings,
)
from app.api.routes.admin import (
    events_router as admin_events_router,
)
from app.api.routes.admin import (
    settings_router as admin_settings_router,
)
from app.api.routes.admin import (
    users_router as admin_users_router,
)
from app.api.dependencies import AuthService
from app.core.metrics.health import HealthMetrics
from app.db.repositories.admin.admin_events_repository import AdminEventsRepository
from app.db.repositories.admin.admin_settings_repository import AdminSettingsRepository
from app.db.repositories.admin.admin_user_repository import AdminUserRepository
from app.events.core.producer import UnifiedProducer
from app.events.event_store import EventStore
from app.schemas_pydantic.admin_settings import SystemSettings
from app.schemas_pydantic.notification import NotificationSubscription
from app.schemas_pydantic.user import UserResponse, UserRole
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService
from app.services.kafka_event_service import KafkaEventService
from app.services.notification_service import NotificationService
from app.services.replay_service import ReplayService
from app.services.saga_service import SagaService
from app.services.saved_script_service import SavedScriptService
from app.services.sse.sse_service import SSEService
from app.services.user_settings_service import UserSettingsService
from app.services.idempotency import IdempotencyManager
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.services.rate_limit_service import RateLimitService
from app.db.repositories import UserRepository
from app.db.repositories.dlq_repository import DLQRepository
from app.dlq.manager import DLQManager
from app.services.admin_user_service import AdminUserService
from app.schemas_pydantic.admin_user_overview import AdminUserOverview, DerivedCounts, RateLimitSummary
from app.schemas_pydantic.events import EventStatistics
from app.domain.replay.models import ReplayConfig, ReplayFilter
from app.domain.enums.replay import ReplayType, ReplayTarget, ReplayStatus
from app.domain.rate_limit import RateLimitStatus, RateLimitAlgorithm


# ---------- Fake services and repositories ----------


class FakeRateLimitService(RateLimitService):
    def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
        # Don't call super().__init__, avoid Redis dependency
        pass
    
    async def check_rate_limit(
        self,
        user_id: str,
        endpoint: str,
        config: Any = None,
        username: Optional[str] = None
    ) -> RateLimitStatus:  # type: ignore[override]
        # Always allow in tests
        return RateLimitStatus(
            allowed=True,
            limit=1000,
            remaining=999,
            reset_at=datetime.now(timezone.utc) + timedelta(seconds=60),
            retry_after=None,
            matched_rule=None,
            algorithm=RateLimitAlgorithm.SLIDING_WINDOW
        )


class FakeAuthService(AuthService):
    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        pass

    async def get_current_user(self, request) -> UserResponse:  # type: ignore[override]
        return UserResponse(
            user_id="u1",
            username="tester",
            email="tester@example.com",
            role=UserRole.ADMIN,
            is_superuser=True,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    async def require_admin(self, request) -> UserResponse:  # type: ignore[override]
        return await self.get_current_user(request)


class FakeEventService(EventService):
    def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
        pass
    async def get_user_events_paginated(self, *args, **kwargs) -> Any:  # type: ignore[override]
        return type("R", (), {"events": [], "total": 0, "has_more": False})()

    async def get_execution_events(self, *args, **kwargs) -> list[Any]:  # type: ignore[override]
        return []

    async def get_events_by_correlation(self, *args, **kwargs) -> list[Any]:  # type: ignore[override]
        return []

    async def query_events_advanced(self, *args, **kwargs) -> Any:  # type: ignore[override]
        return type("R", (), {"events": [], "total": 0, "limit": 10, "skip": 0, "has_more": False})()

    async def get_events_by_aggregate(self, *args, **kwargs) -> list[Any]:  # type: ignore[override]
        return []

    async def get_event_statistics(self, *args, **kwargs) -> Any:  # type: ignore[override]
        return type("Stats", (), {
            "total_events": 0,
            "events_by_type": {},
            "events_by_service": {},
            "events_by_hour": [],
            "start_time": None,
            "end_time": None,
            "error_rate": 0.0,
            "avg_processing_time": 0.0,
        })()

    async def get_event(self, *args, **kwargs):  # type: ignore[override]
        return None

    async def list_event_types(self, *args, **kwargs) -> list[str]:  # type: ignore[override]
        return ["execution_requested", "execution_completed"]

    async def get_aggregate_replay_info(self, aggregate_id: str):  # type: ignore[override]
        from datetime import datetime, timezone
        class Ev:
            def __init__(self, idx: int) -> None:
                self.event_id = f"e{idx}"
                self.event_type = "execution_completed"
                self.payload = {"n": idx}
                self.timestamp = datetime.now(timezone.utc)
        class Info:
            def __init__(self) -> None:
                self.event_count = 2
                self.event_types: list[str] = ["execution_completed"]
                self.start_time = datetime.now(timezone.utc)
                self.end_time = datetime.now(timezone.utc)
                self.events: list[Any] = [Ev(1), Ev(2)]
        return Info()

    async def delete_event_with_archival(self, event_id: str, deleted_by: str):  # type: ignore[override]
        class Res:
            event_type = "execution_completed"
            aggregate_id = "agg1"
            correlation_id = "corr1"
        return Res()


class FakeExecutionService(ExecutionService):
    async def execute_script(self, *args, **kwargs):  # type: ignore[override]
        from app.domain.execution.models import DomainExecution
        from app.domain.enums.execution import ExecutionStatus

        return DomainExecution(script="print(1)", status=ExecutionStatus.QUEUED)

    async def get_example_scripts(self) -> dict[str, str]:  # type: ignore[override]
        return {"python": "print('hi')"}

    async def get_k8s_resource_limits(self) -> dict[str, Any]:  # type: ignore[override]
        return {"cpu_limit": "100m", "memory_limit": "128Mi", "cpu_request": "50m", "memory_request": "64Mi", "execution_timeout": 10, "supported_runtimes": {"python": ["3.11"]}}

    async def get_execution_result(self, execution_id: str):  # type: ignore[override]
        from app.domain.execution.models import DomainExecution
        from app.domain.enums.execution import ExecutionStatus

        return DomainExecution(execution_id=execution_id, script="print(1)", status=ExecutionStatus.COMPLETED)

    async def get_user_executions(self, *args, **kwargs):  # type: ignore[override]
        return []

    async def count_user_executions(self, *args, **kwargs) -> int:  # type: ignore[override]
        return 0

    async def delete_execution(self, *args, **kwargs) -> None:  # type: ignore[override]
        return None


class FakeKafkaEventService(KafkaEventService):
    def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
        pass
    async def publish_execution_event(self, *args, **kwargs) -> str:  # type: ignore[override]
        return "evt-1"
    async def publish_event(self, *args, **kwargs) -> str:  # type: ignore[override]
        return "evt-2"


class FakeUserSettingsService(UserSettingsService):
    def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
        pass
    async def get_user_settings(self, user_id: str):  # type: ignore[override]
        from app.schemas_pydantic.user_settings import UserSettings

        return UserSettings(user_id=user_id)

    async def update_theme(self, user_id: str, theme: str):  # type: ignore[override]
        from app.schemas_pydantic.user_settings import UserSettings

        s = UserSettings(user_id=user_id)
        s.theme = theme
        return s


class FakeSavedScriptService(SavedScriptService):
    async def list_saved_scripts(self, user_id: str):  # type: ignore[override]
        return []

    async def create_saved_script(self, *args, **kwargs):  # type: ignore[override]
        from app.domain.saved_script.models import DomainSavedScript
        from datetime import datetime, timezone
        return DomainSavedScript(script_id="sid", name="ex", lang="python", lang_version="3.11", script="print(1)", description=None, user_id="u1", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))

    async def get_saved_script(self, *args, **kwargs):  # type: ignore[override]
        from app.domain.saved_script.models import DomainSavedScript
        from datetime import datetime, timezone
        return DomainSavedScript(script_id="sid", name="ex", lang="python", lang_version="3.11", script="print(1)", description=None, user_id="u1", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))

    async def update_saved_script(self, *args, **kwargs):  # type: ignore[override]
        from app.domain.saved_script.models import DomainSavedScript
        from datetime import datetime, timezone
        return DomainSavedScript(script_id="sid", name="ex2", lang="python", lang_version="3.11", script="print(2)", description=None, user_id="u1", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))

    async def delete_saved_script(self, *args, **kwargs) -> None:  # type: ignore[override]
        return None


class FakeNotificationService(NotificationService):
    def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
        # Do not call super().__init__; keep lightweight
        self._state = None
    async def get_unread_count(self, user_id: str) -> int:  # type: ignore[override]
        return 0

    async def get_subscriptions(self, user_id: str) -> dict[str, NotificationSubscription]:  # type: ignore[override]
        return {}
    async def create_system_notification(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return None
    async def list_notifications(self, *args, **kwargs) -> Any:  # type: ignore[no-untyped-def]
        from app.domain.notification.models import DomainNotificationListResult
        return DomainNotificationListResult(notifications=[], total=0, unread_count=0)
    async def mark_as_read(self, *args, **kwargs) -> bool:  # type: ignore[no-untyped-def]
        return True
    async def mark_all_as_read(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return None
    async def update_subscription(self, user_id: str, channel: Any, enabled: bool, webhook_url: str | None, slack_webhook: str | None, notification_types: list[Any]):  # type: ignore[no-untyped-def]
        from app.domain.notification.models import DomainNotificationSubscription
        return DomainNotificationSubscription(user_id=user_id, channel=channel, enabled=enabled, notification_types=notification_types, webhook_url=webhook_url, slack_webhook=slack_webhook)
    async def delete_notification(self, *args, **kwargs) -> bool:  # type: ignore[no-untyped-def]
        return True


class FakeReplayService(ReplayService):
    def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
        pass
    async def create_session(self, request):  # type: ignore[override]
        from app.domain.enums.replay import ReplayStatus
        from app.schemas_pydantic.replay import ReplayResponse

        return ReplayResponse(session_id="rid", status=ReplayStatus.CREATED, message="ok")
    async def start_session(self, session_id: str):  # type: ignore[override]
        from app.domain.enums.replay import ReplayStatus
        from app.schemas_pydantic.replay import ReplayResponse
        return ReplayResponse(session_id=session_id, status=ReplayStatus.RUNNING, message="started")
    async def pause_session(self, session_id: str):  # type: ignore[override]
        from app.domain.enums.replay import ReplayStatus
        from app.schemas_pydantic.replay import ReplayResponse
        return ReplayResponse(session_id=session_id, status=ReplayStatus.PAUSED, message="paused")
    async def resume_session(self, session_id: str):  # type: ignore[override]
        from app.domain.enums.replay import ReplayStatus
        from app.schemas_pydantic.replay import ReplayResponse
        return ReplayResponse(session_id=session_id, status=ReplayStatus.RUNNING, message="resumed")
    async def cancel_session(self, session_id: str):  # type: ignore[override]
        from app.domain.enums.replay import ReplayStatus
        from app.schemas_pydantic.replay import ReplayResponse
        return ReplayResponse(session_id=session_id, status=ReplayStatus.CANCELLED, message="cancelled")
    def list_sessions(self, status=None, limit=100):  # type: ignore[override]
        from datetime import datetime, timezone
        from app.schemas_pydantic.replay import SessionSummary
        return [SessionSummary(
            session_id="rid",
            replay_type=ReplayType.EVENT_TYPE,
            target=ReplayTarget.KAFKA,
            status=ReplayStatus.CREATED,
            total_events=0,
            replayed_events=0,
            failed_events=0,
            skipped_events=0,
            created_at=datetime.now(timezone.utc),
            started_at=None,
            completed_at=None,
            duration_seconds=None,
            throughput_events_per_second=None,
        )]
    def get_session(self, session_id: str):  # type: ignore[override]
        from datetime import datetime, timezone
        from app.domain.enums.replay import ReplayStatus
        from app.domain.replay.models import ReplayConfig
        from app.schemas_pydantic.replay_models import ReplaySession
        cfg = ReplayConfig(
            replay_type=ReplayType.EVENT_TYPE,
            target=ReplayTarget.KAFKA,
            filter=ReplayFilter()
        )
        return ReplaySession(session_id=session_id, config=cfg, status=ReplayStatus.CREATED)

    async def cleanup_old_sessions(self, older_than_hours: int = 24):  # type: ignore[override]
        from app.schemas_pydantic.replay import CleanupResponse
        return CleanupResponse(removed_sessions=0, message="ok")


class FakeSagaService(SagaService):
    def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
        pass
    async def get_saga_with_access_check(self, *args, **kwargs):  # type: ignore[override]
        from app.domain.enums.saga import SagaState
        from app.domain.saga.models import Saga
        return Saga(saga_id="s1", saga_name="dummy", execution_id="e1", state=SagaState.CREATED)

    async def list_user_sagas(self, *args, **kwargs):  # type: ignore[override]
        return type("R", (), {"sagas": [], "total": 0})()

    async def get_execution_sagas(self, *args, **kwargs) -> list[Any]:  # type: ignore[override]
        return []

    async def cancel_saga(self, *args, **kwargs) -> bool:  # type: ignore[override]
        return True


class FakeSSEService(SSEService):
    def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
        pass
    
    async def create_execution_stream(
        self,
        execution_id: str,
        user_id: str
    ):  # type: ignore[override]
        """Mock implementation that yields test events without dependencies."""
        import json
        yield {"data": json.dumps({"event": "connected", "execution_id": execution_id})}
        yield {"data": json.dumps({"event": "status", "status": "completed"})}
    
    async def get_health_status(self):  # type: ignore[override]
        from datetime import datetime, timezone
        from app.schemas_pydantic.sse import SSEHealthResponse
        return SSEHealthResponse(
            status="healthy",
            kafka_enabled=True,
            active_connections=0,
            active_executions=0,
            active_consumers=0,
            max_connections_per_user=5,
            shutdown={"is_shutting_down": False, "pending_connections": 0},
            timestamp=datetime.now(timezone.utc)
        )


class FakeProducer(UnifiedProducer):
    def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
        pass
    async def is_connected(self) -> bool:  # type: ignore[override]
        return True


class FakeEventStore(EventStore):
    def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
        pass
    async def health_check(self) -> dict[str, Any]:  # type: ignore[override]
        return {"healthy": True, "message": "ok"}


class TestProvider(Provider):
    scope = Scope.APP

    @provide
    def get_auth_service(self) -> AuthService:
        return FakeAuthService()

    @provide
    def get_event_service(self) -> EventService:
        return FakeEventService(None)  # type: ignore[arg-type]

    @provide
    def get_execution_service(self) -> ExecutionService:
        return FakeExecutionService(None, None, None, None)  # type: ignore[arg-type]

    @provide
    def get_kafka_event_service(self) -> KafkaEventService:
        return FakeKafkaEventService()  # type: ignore[call-arg]

    @provide
    def get_user_settings_service(self) -> UserSettingsService:
        return FakeUserSettingsService(None)  # type: ignore[arg-type]

    @provide
    def get_saved_script_service(self) -> SavedScriptService:
        return FakeSavedScriptService(None)  # type: ignore[arg-type]

    @provide
    def get_notification_service(self) -> NotificationService:
        return FakeNotificationService(None, None)  # type: ignore[arg-type]

    @provide
    def get_replay_service(self) -> ReplayService:
        return FakeReplayService(None, None)  # type: ignore[arg-type]

    @provide
    def get_saga_service(self) -> SagaService:
        return FakeSagaService(None, None)  # type: ignore[arg-type]

    @provide
    def get_sse_service(self) -> SSEService:
        return FakeSSEService(None, None, None)  # type: ignore[arg-type]

    @provide
    def get_producer(self) -> UnifiedProducer:
        return FakeProducer()

    @provide
    def get_event_store(self) -> EventStore:
        return FakeEventStore()  # type: ignore[call-arg]

    @provide
    def get_health_metrics(self) -> HealthMetrics:
        return HealthMetrics()

    @provide
    def get_rate_limit_service(self) -> RateLimitService:
        return FakeRateLimitService()

    # Admin repos
    @provide
    def get_admin_events_repository(self) -> AdminEventsRepository:
        class Fake(AdminEventsRepository):  # type: ignore[misc]
            def __init__(self, db: Optional[Any] = None) -> None:  # type: ignore[no-untyped-def]
                # Avoid calling super().__init__ to skip get_collection on real DB
                self.db = db
            async def browse_events(self, *args, **kwargs):  # type: ignore[override]
                return type("R", (), {"events": [], "total": 0, "skip": 0, "limit": 10})()

            async def get_event_stats(self, *args, **kwargs):  # type: ignore[override]
                class Stats:
                    total_events = 0
                    events_by_type = {}
                    events_by_service = {}
                    events_by_hour = []
                    top_users = []
                    error_rate = 0.0
                    avg_processing_time = 0.0
                    start_time = None
                    end_time = None

                return Stats()

            async def get_event_detail(self, *args, **kwargs):  # type: ignore[override]
                return None

            async def export_events_csv(self, *args, **kwargs):  # type: ignore[override]
                return []

            async def get_replay_status_with_progress(self, *args, **kwargs):  # type: ignore[override]
                return None

            async def archive_event(self, *args, **kwargs):  # type: ignore[override]
                return True

            async def delete_event(self, *args, **kwargs):  # type: ignore[override]
                return False

        return Fake(None)  # type: ignore[arg-type]

    @provide
    def get_admin_settings_repository(self) -> AdminSettingsRepository:
        class Fake(AdminSettingsRepository):  # type: ignore[misc]
            def __init__(self, db: Optional[Any] = None) -> None:  # type: ignore[no-untyped-def]
                self.db = db
            async def get_system_settings(self):  # type: ignore[override]
                from app.domain.admin.settings_models import SystemSettings as DomainSystemSettings
                return DomainSystemSettings()

            async def update_system_settings(self, settings, updated_by: str, user_id: str):  # type: ignore[override]
                return settings

            async def reset_system_settings(self, username: str, user_id: str):  # type: ignore[override]
                from app.domain.admin.settings_models import SystemSettings as DomainSystemSettings
                return DomainSystemSettings()

        return Fake(None)  # type: ignore[arg-type]

    @provide
    def get_admin_user_repository(self) -> AdminUserRepository:
        class Fake(AdminUserRepository):  # type: ignore[misc]
            def __init__(self, db: Optional[Any] = None) -> None:  # type: ignore[no-untyped-def]
                self.db = db
                self._users: dict[str, dict[str, Any]] = {}
            async def list_users(self, limit: int = 10, offset: int = 0, search: str | None = None, role: str | None = None):  # type: ignore[override]
                from app.infrastructure.mappers.admin_mapper import UserMapper
                mapper = UserMapper()
                docs = list(self._users.values())
                if search:
                    docs = [d for d in docs if search in d.get("username", "")]
                users = [mapper.from_mongo_document(d) for d in docs]
                return type("R", (), {"users": users, "total": len(users), "offset": 0, "limit": limit})()

            async def get_user_by_id(self, user_id: str):  # type: ignore[override]
                from app.infrastructure.mappers.admin_mapper import UserMapper
                doc = self._users.get(user_id)
                if not doc:
                    return None
                return UserMapper().from_mongo_document(doc)

            class users_collection:  # noqa: D401
                def __init__(self, outer) -> None:  # type: ignore[no-untyped-def]
                    self._outer = outer
                async def insert_one(self, doc):  # type: ignore[no-untyped-def]
                    self._outer._users[doc["user_id"]] = doc
                    return type("Res", (), {"inserted_id": doc["user_id"]})()

            async def update_user(self, user_id: str, domain_update):  # type: ignore[override]
                from app.infrastructure.mappers.admin_mapper import UserMapper
                if user_id not in self._users:
                    return None
                # apply updates
                if domain_update.username is not None:
                    self._users[user_id]["username"] = domain_update.username
                if domain_update.email is not None:
                    self._users[user_id]["email"] = domain_update.email
                if domain_update.role is not None:
                    self._users[user_id]["role"] = domain_update.role.value
                if domain_update.is_active is not None:
                    self._users[user_id]["is_active"] = domain_update.is_active
                self._users[user_id]["updated_at"] = datetime.now(timezone.utc)
                return UserMapper().from_mongo_document(self._users[user_id])

            async def delete_user(self, user_id: str, cascade: bool = True):  # type: ignore[override]
                if user_id in self._users:
                    del self._users[user_id]
                    return {"user": 1}
                return {"user": 0}

            async def reset_user_password(self, password_reset):  # type: ignore[override]
                return password_reset.user_id in self._users

        fake = Fake(None)  # type: ignore[arg-type]
        fake.users_collection = fake.users_collection(fake)  # type: ignore[attr-defined]
        return fake

    @provide
    def get_idempotency_manager(self) -> IdempotencyManager:
        class FakeIdem(IdempotencyManager):  # type: ignore[misc]
            def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
                pass
            async def check_and_reserve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                return type("R", (), {"is_duplicate": False, "result": None})()

            async def mark_completed(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
                return None

            async def mark_failed(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
                return None

        return FakeIdem(None)  # type: ignore[arg-type]

    @provide
    def get_db(self) -> AsyncIOMotorDatabase:
        class FakeDB:  # minimal methods used by health checks
            async def command(self, *_: Any, **__: Any) -> dict[str, int]:  # type: ignore[no-untyped-def]
                return {"ok": 1}

            def get_collection(self, *_: Any, **__: Any) -> Any:  # type: ignore[no-untyped-def]
                class Coll:
                    async def delete_many(self, *_: Any, **__: Any) -> Any:  # type: ignore[no-untyped-def]
                        return type("Res", (), {"deleted_count": 0})()

                return Coll()

        return FakeDB()  # type: ignore[return-value]

    @provide
    def get_rate_limit_service(self) -> RateLimitService:
        class FakeRL(RateLimitService):  # type: ignore[misc]
            def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
                pass
            async def get_user_rate_limit(self, *_: Any, **__: Any):  # type: ignore[no-untyped-def]
                return None
            async def get_usage_stats(self, *_: Any, **__: Any):  # type: ignore[no-untyped-def]
                return {}
            async def update_user_rate_limit(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
                return None
            async def reset_user_limits(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
                return None

        return FakeRL()  # type: ignore[call-arg]

    @provide
    def get_user_repository(self) -> UserRepository:
        class FakeUserRepo(UserRepository):  # type: ignore[misc]
            def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
                self._users: dict[str, Any] = {}
            async def get_user(self, username: str):  # type: ignore[no-untyped-def]
                return self._users.get(username)
            async def create_user(self, user):  # type: ignore[no-untyped-def]
                self._users[user.username] = user
                return user

        return FakeUserRepo()  # type: ignore[call-arg]

    @provide
    def get_dlq_manager(self) -> DLQManager:
        class FakeMgr(DLQManager):  # type: ignore[misc]
            def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
                pass
            async def retry_message_manually(self, *_: Any, **__: Any) -> bool:  # type: ignore[no-untyped-def]
                return True
            def set_retry_policy(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
                return None
            async def _discard_message(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
                return None

        return FakeMgr()  # type: ignore[call-arg]

    @provide
    def get_dlq_repository(self) -> DLQRepository:
        class FakeRepo(DLQRepository):  # type: ignore[misc]
            def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
                pass
            async def get_dlq_stats(self, *_: Any, **__: Any):  # type: ignore[no-untyped-def]
                from app.dlq.models import DLQStatistics, AgeStatistics
                return DLQStatistics(by_status={}, by_topic=[], by_event_type=[], age_stats=AgeStatistics(0, 0, 0))
            async def get_messages(self, *_: Any, **__: Any):  # type: ignore[no-untyped-def]
                from app.dlq.models import DLQMessageListResult
                return DLQMessageListResult(messages=[], total=0, offset=0, limit=50)
            async def get_message_by_id(self, *_: Any, **__: Any):  # type: ignore[no-untyped-def]
                return None
            async def get_topics_summary(self, *_: Any, **__: Any):  # type: ignore[no-untyped-def]
                return []
            async def retry_messages_batch(self, *_: Any, **__: Any):  # type: ignore[no-untyped-def]
                from app.dlq.models import DLQBatchRetryResult
                return DLQBatchRetryResult(total=0, successful=0, failed=0, details=[])
            async def mark_message_discarded(self, *_: Any, **__: Any) -> bool:  # type: ignore[no-untyped-def]
                return True
            async def get_message_for_retry(self, *_: Any, **__: Any):  # type: ignore[no-untyped-def]
                class M:
                    event_id = "x"
                return M()

        return FakeRepo()  # type: ignore[call-arg]

    @provide
    def get_admin_user_service(self) -> AdminUserService:
        class FakeSvc(AdminUserService):  # type: ignore[misc]
            def __init__(self, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
                pass
            async def get_user_overview(self, user_id: str, hours: int = 24) -> AdminUserOverview:  # type: ignore[override]
                from datetime import datetime, timezone
                user = UserResponse(
                    user_id=user_id,
                    username="api_user",
                    email="api_user@example.com",
                    role=UserRole.USER,
                    is_active=True,
                    is_superuser=False,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                stats = EventStatistics(
                    total_events=0,
                    events_by_type={},
                    events_by_service={},
                    events_by_hour=[],
                )
                return AdminUserOverview(
                    user=user,
                    stats=stats,
                    derived_counts=DerivedCounts(),
                    rate_limit_summary=RateLimitSummary(),
                    recent_events=[],
                )

        return FakeSvc()  # type: ignore[call-arg]


def create_test_app() -> FastAPI:
    app = FastAPI(title="test-app")

    # Wire Dishka with test container
    from dishka import make_async_container

    container = make_async_container(TestProvider())
    setup_dishka(container, app)

    # Include all application routers with the same prefixes as main app
    app.include_router(auth.router, prefix="/api/v1")
    # Include SSE before execution to ensure static /events/health matches correctly
    app.include_router(sse.router, prefix="/api/v1")
    app.include_router(execution.router, prefix="/api/v1")
    app.include_router(saved_scripts.router, prefix="/api/v1")
    app.include_router(replay.router, prefix="/api/v1")
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(dlq.router, prefix="/api/v1")
    # sse already included above
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(admin_events_router, prefix="/api/v1")
    app.include_router(admin_settings_router, prefix="/api/v1")
    app.include_router(admin_users_router, prefix="/api/v1")
    app.include_router(user_settings.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(saga.router, prefix="/api/v1")
    app.include_router(alertmanager.router, prefix="/api/v1")

    # Disable rate limit check in tests
    app.dependency_overrides[check_rate_limit] = lambda: None

    return app


# Useful default for tests
app = create_test_app()
