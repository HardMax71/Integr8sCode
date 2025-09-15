import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, Dict

from app.core.logging import logger
from app.core.metrics.context import get_connection_metrics
from app.db.repositories.sse_repository import SSERepository
from app.domain.enums.events import EventType
from app.domain.sse import SSEHealthDomain
from app.infrastructure.kafka.events.base import BaseEvent
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge
from app.services.sse.redis_bus import SSERedisBus
from app.services.sse.sse_shutdown_manager import SSEShutdownManager
from app.settings import Settings


class SSEService:
    
    # Only result_stored should terminate the stream; other terminal-ish
    # execution events precede the final persisted result and must not close
    # the connection prematurely.
    TERMINAL_EVENT_TYPES: set[EventType] = {
        EventType.RESULT_STORED,
        EventType.EXECUTION_FAILED,
        EventType.EXECUTION_TIMEOUT,
        EventType.RESULT_FAILED,
    }

    def __init__(
        self,
        repository: SSERepository,
        router: SSEKafkaRedisBridge,
        sse_bus: SSERedisBus,
        shutdown_manager: SSEShutdownManager,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.router = router
        self.sse_bus = sse_bus
        self.shutdown_manager = shutdown_manager
        self.settings = settings
        self.metrics = get_connection_metrics()
        self.heartbeat_interval = getattr(settings, "SSE_HEARTBEAT_INTERVAL", 30)

    async def create_execution_stream(
        self,
        execution_id: str,
        user_id: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        connection_id = f"sse_{execution_id}_{datetime.now(timezone.utc).timestamp()}"
        
        shutdown_event = await self.shutdown_manager.register_connection(execution_id, connection_id)
        if shutdown_event is None:
            yield self._format_event("error", {
                "error": "Server is shutting down",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            return

        try:
            # Start opening subscription concurrently, then yield handshake
            sub_task = asyncio.create_task(self.sse_bus.open_subscription(execution_id))
            yield self._format_event("connected", {
                "execution_id": execution_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "connection_id": connection_id
            })

            # Complete Redis subscription after handshake
            logger.info(f"Opening Redis subscription for execution {execution_id}")
            subscription = await sub_task
            logger.info(f"Redis subscription opened for execution {execution_id}")

            initial_status = await self.repository.get_execution_status(execution_id)
            if initial_status:
                payload = {
                    "execution_id": initial_status.execution_id,
                    "status": initial_status.status,
                    "timestamp": initial_status.timestamp,
                }
                yield self._format_event("status", payload)
                self.metrics.record_sse_message_sent("executions", "status")

            async for event_data in self._stream_events_redis(
                execution_id,
                subscription,
                shutdown_event,
                include_heartbeat=False,
            ):
                yield event_data
                
        finally:
            # Close subscription and unregister
            try:
                if 'subscription' in locals() and subscription is not None:
                    await subscription.close()
            except Exception:
                pass
            await self.shutdown_manager.unregister_connection(execution_id, connection_id)
            logger.info(f"SSE connection closed: execution_id={execution_id}")

    async def _stream_events_redis(
        self,
        execution_id: str,
        subscription: Any,
        shutdown_event: asyncio.Event,
        include_heartbeat: bool = True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        last_heartbeat = datetime.now(timezone.utc)
        while True:
            if shutdown_event.is_set():
                yield self._format_event("shutdown", {
                    "message": "Server is shutting down",
                    "grace_period": 30,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                break

            now = datetime.now(timezone.utc)
            if include_heartbeat and (now - last_heartbeat).total_seconds() >= self.heartbeat_interval:
                yield self._format_event("heartbeat", {
                    "execution_id": execution_id,
                    "timestamp": now.isoformat(),
                    "message": "SSE connection active"
                })
                last_heartbeat = now

            msg = await subscription.get(timeout=0.5)
            if not msg:
                continue
            # msg contains {'event_type': str, 'execution_id': str, 'data': {...}}
            logger.info(f"Received Redis message for execution {execution_id}: {msg.get('event_type')}")
            try:
                raw_event_type = msg.get("event_type")
                # Normalize to EventType when possible
                try:
                    event_type = EventType(str(raw_event_type))
                except Exception:
                    event_type = None
                data = msg.get("data", {})
                # Build SSE payload similar to _event_to_sse_format
                sse_event: Dict[str, Any] = {
                    "event_id": data.get("event_id"),
                    "timestamp": data.get("timestamp"),
                    "type": str(event_type) if event_type is not None else str(raw_event_type),
                    "execution_id": execution_id,
                }
                if "status" in data:
                    sse_event["status"] = data["status"]
                # Include stdout/stderr/exit_code if present
                for key in ("stdout", "stderr", "exit_code", "timeout_seconds"):
                    if key in data:
                        sse_event[key] = data[key]
                # Include resource_usage if present
                if "resource_usage" in data:
                    sse_event["resource_usage"] = data["resource_usage"]

                # If this is result_stored, enrich with full execution result payload
                if event_type == EventType.RESULT_STORED:
                    exec_domain = await self.repository.get_execution(execution_id)
                    if exec_domain:
                        ru_payload = None
                        if getattr(exec_domain, "resource_usage", None) is not None:
                            ru_obj = exec_domain.resource_usage
                            ru_payload = ru_obj.to_dict() if ru_obj and hasattr(ru_obj, "to_dict") else ru_obj
                        sse_event["result"] = {
                            "execution_id": exec_domain.execution_id,
                            "status": exec_domain.status,
                            "stdout": exec_domain.stdout,
                            "stderr": exec_domain.stderr,
                            "lang": exec_domain.lang,
                            "lang_version": exec_domain.lang_version,
                            "resource_usage": ru_payload,
                            "exit_code": exec_domain.exit_code,
                            "error_type": exec_domain.error_type,
                        }

                yield self._format_event(str(event_type) if event_type is not None else str(raw_event_type), sse_event)

                # End on terminal event types
                if event_type in self.TERMINAL_EVENT_TYPES:
                    logger.info(f"Terminal event for execution {execution_id}: {event_type}")
                    break
            except Exception:
                # Ignore malformed messages
                continue

    async def create_notification_stream(
        self,
        user_id: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        subscription = None

        try:
            # Start opening subscription concurrently, then yield handshake
            sub_task = asyncio.create_task(self.sse_bus.open_notification_subscription(user_id))
            yield self._format_event("connected", {
                "message": "Connected to notification stream",
                "user_id": user_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            # Complete Redis subscription after handshake
            subscription = await sub_task

            last_heartbeat = datetime.now(timezone.utc)
            while not self.shutdown_manager.is_shutting_down():
                # Heartbeat
                now = datetime.now(timezone.utc)
                if (now - last_heartbeat).total_seconds() >= self.heartbeat_interval:
                    yield self._format_event("heartbeat", {
                        "timestamp": now.isoformat(),
                        "user_id": user_id,
                        "message": "Notification stream active"
                    })
                    last_heartbeat = now

                # Forward notification messages as SSE data
                msg = await subscription.get(timeout=0.5)
                if msg:
                    # msg already contains the notification payload
                    yield self._format_event("notification", msg)
        finally:
            try:
                if subscription is not None:
                    await subscription.close()
            except Exception:
                pass

    async def get_health_status(self) -> SSEHealthDomain:
        router_stats = self.router.get_stats()
        return SSEHealthDomain(
            status="draining" if self.shutdown_manager.is_shutting_down() else "healthy",
            kafka_enabled=True,
            active_connections=router_stats["active_executions"],
            active_executions=router_stats["active_executions"],
            active_consumers=router_stats["num_consumers"],
            max_connections_per_user=5,
            shutdown=self.shutdown_manager.get_shutdown_status(),
            timestamp=datetime.now(timezone.utc)
        )

    async def _event_to_sse_format(self, event: BaseEvent, execution_id: str) -> Dict[str, Any]:
        event_data = event.model_dump(mode="json")

        sse_event: Dict[str, Any] = {
            "event_id": event.event_id,
            "timestamp": event_data.get("timestamp"),
            "type": str(event.event_type),
            "execution_id": execution_id,
        }

        if "status" in event_data:
            sse_event["status"] = event_data["status"]

        if event.event_type == EventType.RESULT_STORED:
            exec_domain = await self.repository.get_execution(execution_id)
            if exec_domain:
                ru_payload = None
                if getattr(exec_domain, "resource_usage", None) is not None:
                    ru_obj = exec_domain.resource_usage
                    ru_payload = ru_obj.to_dict() if ru_obj and hasattr(ru_obj, "to_dict") else ru_obj
                sse_event["result"] = {
                    "execution_id": exec_domain.execution_id,
                    "status": exec_domain.status,
                    "stdout": exec_domain.stdout,
                    "stderr": exec_domain.stderr,
                    "lang": exec_domain.lang,
                    "lang_version": exec_domain.lang_version,
                    "resource_usage": ru_payload,
                    "exit_code": exec_domain.exit_code,
                    "error_type": exec_domain.error_type,
                }

        skip_fields = {"event_id", "timestamp", "event_type", "metadata", "payload"}
        for key, value in event_data.items():
            if key not in skip_fields and key not in sse_event:
                sse_event[key] = value

        return sse_event

    def _format_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        data["event_type"] = event_type
        return {"data": json.dumps(data)}
