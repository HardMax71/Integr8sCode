"""Redis-backed pod state tracking repository.

Replaces in-memory pod state tracking (_tracked_pods, _active_creations)
for stateless, horizontally-scalable services.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import redis.asyncio as redis


@dataclass
class PodState:
    """State of a tracked pod."""

    pod_name: str
    execution_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, object] | None = None


class PodStateRepository:
    """Redis-backed pod state tracking.

    Provides atomic operations for pod creation tracking,
    replacing in-memory sets like `_active_creations` and `_tracked_pods`.
    """

    CREATION_KEY_PREFIX = "pod:creating"
    TRACKED_KEY_PREFIX = "pod:tracked"
    RESOURCE_VERSION_KEY = "pod:resource_version"

    def __init__(self, redis_client: redis.Redis, logger: logging.Logger) -> None:
        self._redis = redis_client
        self._logger = logger

    # --- Active Creations (for KubernetesWorker) ---

    async def try_claim_creation(self, execution_id: str, ttl_seconds: int = 300) -> bool:
        """Atomically claim a pod creation slot. Returns True if claimed."""
        key = f"{self.CREATION_KEY_PREFIX}:{execution_id}"
        result = await self._redis.set(key, "1", nx=True, ex=ttl_seconds)
        if result:
            self._logger.debug(f"Claimed pod creation for {execution_id}")
        return result is not None

    async def release_creation(self, execution_id: str) -> bool:
        """Release a pod creation claim."""
        key = f"{self.CREATION_KEY_PREFIX}:{execution_id}"
        deleted = await self._redis.delete(key)
        if deleted:
            self._logger.debug(f"Released pod creation for {execution_id}")
        return bool(deleted)

    async def get_active_creations_count(self) -> int:
        """Get count of active pod creations."""
        count = 0
        async for _ in self._redis.scan_iter(match=f"{self.CREATION_KEY_PREFIX}:*", count=100):
            count += 1
        return count

    async def is_creation_active(self, execution_id: str) -> bool:
        """Check if a pod creation is active."""
        key = f"{self.CREATION_KEY_PREFIX}:{execution_id}"
        result = await self._redis.exists(key)
        return bool(result)

    # --- Tracked Pods (for PodMonitor) ---

    async def track_pod(
        self,
        pod_name: str,
        execution_id: str,
        status: str,
        metadata: dict[str, object] | None = None,
        ttl_seconds: int = 7200,
    ) -> None:
        """Track a pod's state."""
        key = f"{self.TRACKED_KEY_PREFIX}:{pod_name}"
        now = datetime.now(timezone.utc).isoformat()

        data = {
            "pod_name": pod_name,
            "execution_id": execution_id,
            "status": status,
            "created_at": now,
            "updated_at": now,
            "metadata": json.dumps(metadata) if metadata else "{}",
        }

        await self._redis.hset(key, mapping=data)  # type: ignore[misc]
        await self._redis.expire(key, ttl_seconds)
        self._logger.debug(f"Tracking pod {pod_name} for execution {execution_id}")

    async def update_pod_status(self, pod_name: str, status: str) -> bool:
        """Update a tracked pod's status. Returns True if updated."""
        key = f"{self.TRACKED_KEY_PREFIX}:{pod_name}"
        exists = await self._redis.exists(key)
        if not exists:
            return False

        now = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(key, mapping={"status": status, "updated_at": now})  # type: ignore[misc]
        return True

    async def untrack_pod(self, pod_name: str) -> bool:
        """Remove a pod from tracking. Returns True if removed."""
        key = f"{self.TRACKED_KEY_PREFIX}:{pod_name}"
        deleted = await self._redis.delete(key)
        if deleted:
            self._logger.debug(f"Untracked pod {pod_name}")
        return bool(deleted)

    async def get_pod_state(self, pod_name: str) -> PodState | None:
        """Get state of a tracked pod."""
        key = f"{self.TRACKED_KEY_PREFIX}:{pod_name}"
        data: dict[bytes | str, bytes | str] = await self._redis.hgetall(key)  # type: ignore[misc]
        if not data:
            return None

        def get_str(k: str) -> str:
            val = data.get(k.encode(), data.get(k, ""))
            return val.decode() if isinstance(val, bytes) else str(val)

        metadata_str = get_str("metadata")
        try:
            metadata = json.loads(metadata_str) if metadata_str else None
        except json.JSONDecodeError:
            metadata = None

        return PodState(
            pod_name=get_str("pod_name"),
            execution_id=get_str("execution_id"),
            status=get_str("status"),
            created_at=datetime.fromisoformat(get_str("created_at")),
            updated_at=datetime.fromisoformat(get_str("updated_at")),
            metadata=metadata,
        )

    async def is_pod_tracked(self, pod_name: str) -> bool:
        """Check if a pod is being tracked."""
        key = f"{self.TRACKED_KEY_PREFIX}:{pod_name}"
        result = await self._redis.exists(key)
        return bool(result)

    async def get_tracked_pods_count(self) -> int:
        """Get count of tracked pods."""
        count = 0
        async for _ in self._redis.scan_iter(match=f"{self.TRACKED_KEY_PREFIX}:*", count=100):
            count += 1
        return count

    async def get_tracked_pod_names(self) -> set[str]:
        """Get set of all tracked pod names."""
        names: set[str] = set()
        prefix_len = len(self.TRACKED_KEY_PREFIX) + 1
        async for key in self._redis.scan_iter(match=f"{self.TRACKED_KEY_PREFIX}:*", count=100):
            key_str = key.decode() if isinstance(key, bytes) else key
            names.add(key_str[prefix_len:])
        return names

    # --- Resource Version (for PodMonitor watch) ---

    async def get_resource_version(self) -> str | None:
        """Get the last known resource version for watch resumption."""
        result = await self._redis.get(self.RESOURCE_VERSION_KEY)
        if result:
            return result.decode() if isinstance(result, bytes) else result
        return None

    async def set_resource_version(self, version: str) -> None:
        """Store the resource version for watch resumption."""
        await self._redis.set(self.RESOURCE_VERSION_KEY, version)
