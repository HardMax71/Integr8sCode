from __future__ import annotations

import json
from typing import Mapping

import redis.asyncio as redis

from app.infrastructure.kafka.events.base import BaseEvent


class SSERedisSubscription:
    def __init__(self, pubsub: redis.client.PubSub, channel: str) -> None:
        self._pubsub = pubsub
        self._channel = channel

    async def get(self, timeout: float = 0.5) -> dict[str, object] | None:
        """Get next message from the subscription with timeout seconds."""
        msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
        if not msg or msg.get("type") != "message":
            return None
        data = msg.get("data")
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(data) if isinstance(data, str) else data
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    async def close(self) -> None:
        try:
            await self._pubsub.unsubscribe(self._channel)
        finally:
            await self._pubsub.aclose()  # type: ignore[no-untyped-call]


class SSERedisBus:
    """Redis-backed pub/sub bus for SSE event fan-out across workers."""

    def __init__(
        self, redis_client: redis.Redis, exec_prefix: str = "sse:exec:", notif_prefix: str = "sse:notif:"
    ) -> None:
        self._redis = redis_client
        self._exec_prefix = exec_prefix
        self._notif_prefix = notif_prefix

    def _exec_channel(self, execution_id: str) -> str:
        return f"{self._exec_prefix}{execution_id}"

    def _notif_channel(self, user_id: str) -> str:
        return f"{self._notif_prefix}{user_id}"

    async def publish_event(self, execution_id: str, event: BaseEvent) -> None:
        payload: dict[str, object] = {
            "event_type": str(event.event_type),
            "execution_id": getattr(event, "execution_id", None),
            "data": event.model_dump(mode="json"),
        }
        await self._redis.publish(self._exec_channel(execution_id), json.dumps(payload))

    async def open_subscription(self, execution_id: str) -> SSERedisSubscription:
        pubsub = self._redis.pubsub()
        channel = self._exec_channel(execution_id)
        await pubsub.subscribe(channel)
        return SSERedisSubscription(pubsub, channel)

    async def publish_notification(self, user_id: str, payload: Mapping[str, object]) -> None:
        # Expect a JSON-serializable mapping
        await self._redis.publish(self._notif_channel(user_id), json.dumps(dict(payload)))

    async def open_notification_subscription(self, user_id: str) -> SSERedisSubscription:
        pubsub = self._redis.pubsub()
        channel = self._notif_channel(user_id)
        await pubsub.subscribe(channel)
        return SSERedisSubscription(pubsub, channel)
