from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import redis.asyncio as redis
from pydantic import BaseModel

from app.domain.events.typed import DomainEvent
from app.schemas_pydantic.sse import RedisNotificationMessage, RedisSSEMessage


class SSERedisSubscription:
    """Subscription wrapper for Redis pubsub with typed message parsing."""

    def __init__(self, pubsub: redis.client.PubSub, channel: str, logger: logging.Logger) -> None:
        self._pubsub = pubsub
        self._channel = channel
        self.logger = logger

    async def get[T: BaseModel](self, model: type[T]) -> T | None:
        """Get next typed message from the subscription."""
        msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if not msg or msg.get("type") != "message":
            return None
        try:
            return model.model_validate_json(msg["data"])
        except Exception as e:
            self.logger.warning(
                f"Failed to parse Redis message on channel {self._channel}: {e}",
                extra={"channel": self._channel, "model": model.__name__},
            )
            return None

    async def close(self) -> None:
        try:
            await self._pubsub.unsubscribe(self._channel)
        finally:
            await self._pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py PubSub.aclose lacks annotations


class SSERedisBus:
    """Redis-backed pub/sub bus for SSE event fan-out and internal messaging across workers.

    Supports:
    - SSE execution event streaming (publish_event, open_subscription)
    - SSE notification streaming (publish_notification, open_notification_subscription)
    - Generic internal pub/sub for cross-instance coordination (publish_internal, subscribe_internal)
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        logger: logging.Logger,
        exec_prefix: str = "sse:exec:",
        notif_prefix: str = "sse:notif:",
        internal_prefix: str = "internal:",
    ) -> None:
        self._redis = redis_client
        self.logger = logger
        self._exec_prefix = exec_prefix
        self._notif_prefix = notif_prefix
        self._internal_prefix = internal_prefix

    def _exec_channel(self, execution_id: str) -> str:
        return f"{self._exec_prefix}{execution_id}"

    def _notif_channel(self, user_id: str) -> str:
        return f"{self._notif_prefix}{user_id}"

    async def publish_event(self, execution_id: str, event: DomainEvent) -> None:
        message = RedisSSEMessage(
            event_type=event.event_type,
            execution_id=execution_id,
            data=event.model_dump(mode="json"),
        )
        await self._redis.publish(self._exec_channel(execution_id), message.model_dump_json())

    async def open_subscription(self, execution_id: str) -> SSERedisSubscription:
        pubsub = self._redis.pubsub()
        channel = self._exec_channel(execution_id)
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1.0)
        return SSERedisSubscription(pubsub, channel, self.logger)

    async def publish_notification(self, user_id: str, notification: RedisNotificationMessage) -> None:
        """Publish a typed notification message to Redis for SSE delivery."""
        await self._redis.publish(self._notif_channel(user_id), notification.model_dump_json())

    async def open_notification_subscription(self, user_id: str) -> SSERedisSubscription:
        pubsub = self._redis.pubsub()
        channel = self._notif_channel(user_id)
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1.0)
        return SSERedisSubscription(pubsub, channel, self.logger)

    # --- Internal Pub/Sub for Cross-Instance Coordination ---

    def _internal_channel(self, topic: str) -> str:
        return f"{self._internal_prefix}{topic}"

    async def publish_internal(self, topic: str, data: dict[str, object]) -> None:
        """Publish an internal event to Redis for cross-instance coordination.

        Unlike Kafka EventBus, this is fire-and-forget with no persistence.
        Use for cache invalidation, real-time sync, etc.

        Args:
            topic: Event topic (e.g., "user.settings.updated")
            data: Event payload
        """
        channel = self._internal_channel(topic)
        message = json.dumps(data)
        await self._redis.publish(channel, message)
        self.logger.debug(f"Published internal event to {channel}")

    async def subscribe_internal(
        self,
        topic: str,
        handler: Callable[[dict[str, object]], Awaitable[None]],
    ) -> InternalSubscription:
        """Subscribe to internal events on a topic.

        Returns a subscription object that must be started and eventually closed.

        Args:
            topic: Event topic (e.g., "user.settings.updated")
            handler: Async callback for each message

        Returns:
            Subscription object with start() and close() methods
        """
        pubsub = self._redis.pubsub()
        channel = self._internal_channel(topic)
        return InternalSubscription(pubsub, channel, handler, self.logger)


class InternalSubscription:
    """Manages an internal pub/sub subscription with background listener."""

    def __init__(
        self,
        pubsub: redis.client.PubSub,
        channel: str,
        handler: Callable[[dict[str, object]], Awaitable[None]],
        logger: logging.Logger,
    ) -> None:
        self._pubsub = pubsub
        self._channel = channel
        self._handler = handler
        self._logger = logger
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start listening for messages."""
        await self._pubsub.subscribe(self._channel)
        await self._pubsub.get_message(timeout=1.0)  # Consume subscribe confirmation

        async def listener() -> None:
            while True:
                try:
                    msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                    if msg and msg.get("type") == "message":
                        data = json.loads(msg["data"])
                        await self._handler(data)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self._logger.error(f"Error processing internal message on {self._channel}: {e}")

        self._task = asyncio.create_task(listener())
        self._logger.debug(f"Started internal subscription on {self._channel}")

    async def close(self) -> None:
        """Stop listening and cleanup."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        try:
            await self._pubsub.unsubscribe(self._channel)
        finally:
            await self._pubsub.aclose()  # type: ignore[no-untyped-call]
        self._logger.debug(f"Closed internal subscription on {self._channel}")
