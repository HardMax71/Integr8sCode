import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Final

import redis.asyncio as aioredis
from faststream import BaseMiddleware
from faststream.message import StreamMessage

from app.domain.idempotency import KeyStrategy


@dataclass(frozen=True)
class Rule:
    strategy: KeyStrategy
    ttl: int


# Topic name -> idempotency rule
# Topic names match event class names in snake_case (e.g., "execution_requested")
RULES: Final[Mapping[str, Rule]] = {
    "execution_requested": Rule(KeyStrategy.EVENT_BASED, 7200),
    "execution_completed": Rule(KeyStrategy.EVENT_BASED, 7200),
    "execution_failed": Rule(KeyStrategy.EVENT_BASED, 7200),
    "execution_cancelled": Rule(KeyStrategy.EVENT_BASED, 7200),
    "execution_timeout": Rule(KeyStrategy.EVENT_BASED, 7200),
    "create_pod_command": Rule(KeyStrategy.CONTENT_HASH, 3600),
    "delete_pod_command": Rule(KeyStrategy.CONTENT_HASH, 3600),
}


def extract_event_id(body: bytes) -> str:
    """Extract event_id from JSON body."""
    try:
        data = json.loads(body)
        return str(data.get("event_id", ""))
    except (json.JSONDecodeError, TypeError):
        return ""


def get_topic_name(msg: StreamMessage[Any], prefix: str = "") -> str:
    """Get topic name from message, stripping prefix if present."""
    raw = msg.raw_message
    topic = getattr(raw, "topic", "") or ""
    if prefix and topic.startswith(prefix):
        return topic[len(prefix):]
    return topic


def compute_key(rule: Rule, topic: str, msg: StreamMessage[Any]) -> str:
    """Compute idempotency key based on strategy."""
    if rule.strategy == KeyStrategy.EVENT_BASED:
        event_id = extract_event_id(msg.body)
        return f"idem:{topic}:{event_id}" if event_id else ""
    elif rule.strategy == KeyStrategy.CONTENT_HASH:
        return f"idem:{topic}:{sha256(msg.body).hexdigest()}" if msg.body else ""
    return ""


class IdempotencyMiddleware:
    """Factory that creates per-message middleware instances.

    Minimal Kafka idempotency using Redis SET NX EX:
    - Reserve: SET key "1" NX EX ttl
    - Complete: key expires naturally
    - Fail: DEL key to allow retry
    """

    def __init__(self, redis: aioredis.Redis, topic_prefix: str = "") -> None:
        self._redis = redis
        self._topic_prefix = topic_prefix

    def __call__(self, msg: Any = None, **kwargs: Any) -> "_IdempotencyMiddleware":
        return _IdempotencyMiddleware(self._redis, self._topic_prefix, msg, **kwargs)


class _IdempotencyMiddleware(BaseMiddleware[Any, Any]):
    """Per-message middleware instance."""

    def __init__(self, redis: aioredis.Redis, topic_prefix: str, msg: Any = None, **kwargs: Any) -> None:
        super().__init__(msg, **kwargs)
        self._redis = redis
        self._topic_prefix = topic_prefix

    async def consume_scope(
        self,
        call_next: Callable[[StreamMessage[Any]], Awaitable[Any]],
        msg: StreamMessage[Any],
    ) -> Any:
        topic = get_topic_name(msg, self._topic_prefix)
        rule = RULES.get(topic)

        if not rule:
            return await call_next(msg)

        key = compute_key(rule, topic, msg)
        if not key:
            return await call_next(msg)

        reserved = await self._redis.set(key, b"1", nx=True, ex=rule.ttl)
        if not reserved:
            return None

        try:
            return await call_next(msg)
        except BaseException:
            await self._redis.delete(key)
            raise
