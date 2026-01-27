"""Redis-backed resource allocation repository.

Replaces in-memory resource tracking (ResourceManager) with Redis
for stateless, horizontally-scalable services.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import redis.asyncio as redis


@dataclass
class ResourceAllocation:
    """Resource allocation for an execution."""

    execution_id: str
    cpu_cores: float
    memory_mb: int
    gpu_count: int = 0

    @property
    def cpu_millicores(self) -> int:
        """Get CPU in millicores for Kubernetes."""
        return int(self.cpu_cores * 1000)

    @property
    def memory_bytes(self) -> int:
        """Get memory in bytes."""
        return self.memory_mb * 1024 * 1024


@dataclass
class ResourceStats:
    """Resource statistics."""

    total_cpu: float
    total_memory_mb: int
    total_gpu: int
    available_cpu: float
    available_memory_mb: int
    available_gpu: int
    allocation_count: int


class ResourceRepository:
    """Redis-backed resource allocation tracking.

    Uses Redis for atomic resource allocation with Lua scripts.
    Replaces in-memory ResourceManager._allocations dict.
    """

    POOL_KEY = "resource:pool"
    ALLOC_KEY_PREFIX = "resource:alloc"

    # Default allocations by language
    DEFAULT_ALLOCATIONS = {
        "python": (0.5, 512),
        "javascript": (0.5, 512),
        "go": (0.25, 256),
        "rust": (0.5, 512),
        "java": (1.0, 1024),
        "cpp": (0.5, 512),
        "r": (1.0, 2048),
    }

    def __init__(
        self,
        redis_client: redis.Redis,
        logger: logging.Logger,
        total_cpu_cores: float = 32.0,
        total_memory_mb: int = 65536,
        total_gpu_count: int = 0,
        overcommit_factor: float = 1.2,
        max_cpu_per_execution: float = 4.0,
        max_memory_per_execution_mb: int = 8192,
        min_reserve_cpu: float = 2.0,
        min_reserve_memory_mb: int = 4096,
    ) -> None:
        self._redis = redis_client
        self._logger = logger

        # Apply overcommit
        self._total_cpu = total_cpu_cores * overcommit_factor
        self._total_memory = int(total_memory_mb * overcommit_factor)
        self._total_gpu = total_gpu_count

        self._max_cpu_per_exec = max_cpu_per_execution
        self._max_memory_per_exec = max_memory_per_execution_mb

        # Adjust reserves for small pools (max 10% of total)
        self._min_reserve_cpu = min(min_reserve_cpu, 0.1 * self._total_cpu)
        self._min_reserve_memory = min(min_reserve_memory_mb, int(0.1 * self._total_memory))

    async def initialize(self) -> None:
        """Initialize the resource pool if not exists."""
        exists = await self._redis.exists(self.POOL_KEY)
        if not exists:
            await self._redis.hset(  # type: ignore[misc]
                self.POOL_KEY,
                mapping={
                    "total_cpu": str(self._total_cpu),
                    "total_memory": str(self._total_memory),
                    "total_gpu": str(self._total_gpu),
                    "available_cpu": str(self._total_cpu),
                    "available_memory": str(self._total_memory),
                    "available_gpu": str(self._total_gpu),
                },
            )
            self._logger.info(
                f"Initialized resource pool: {self._total_cpu} CPU, "
                f"{self._total_memory}MB RAM, {self._total_gpu} GPU"
            )

    async def allocate(
        self,
        execution_id: str,
        language: str,
        requested_cpu: float | None = None,
        requested_memory_mb: int | None = None,
        requested_gpu: int = 0,
    ) -> ResourceAllocation | None:
        """Allocate resources for execution. Returns allocation or None if insufficient."""
        # Check if already allocated
        alloc_key = f"{self.ALLOC_KEY_PREFIX}:{execution_id}"
        existing = await self._redis.hgetall(alloc_key)  # type: ignore[misc]
        if existing:
            self._logger.warning(f"Execution {execution_id} already has allocation")
            return ResourceAllocation(
                execution_id=execution_id,
                cpu_cores=float(existing.get(b"cpu", existing.get("cpu", 0))),
                memory_mb=int(existing.get(b"memory", existing.get("memory", 0))),
                gpu_count=int(existing.get(b"gpu", existing.get("gpu", 0))),
            )

        # Determine requested resources
        if requested_cpu is None or requested_memory_mb is None:
            default_cpu, default_memory = self.DEFAULT_ALLOCATIONS.get(language, (0.5, 512))
            requested_cpu = requested_cpu or default_cpu
            requested_memory_mb = requested_memory_mb or default_memory

        # Apply limits
        requested_cpu = min(requested_cpu, self._max_cpu_per_exec)
        requested_memory_mb = min(requested_memory_mb, self._max_memory_per_exec)

        # Atomic allocation using Lua script
        lua_script = """
        local pool_key = KEYS[1]
        local alloc_key = KEYS[2]
        local req_cpu = tonumber(ARGV[1])
        local req_memory = tonumber(ARGV[2])
        local req_gpu = tonumber(ARGV[3])
        local min_cpu = tonumber(ARGV[4])
        local min_memory = tonumber(ARGV[5])

        local avail_cpu = tonumber(redis.call('HGET', pool_key, 'available_cpu') or '0')
        local avail_memory = tonumber(redis.call('HGET', pool_key, 'available_memory') or '0')
        local avail_gpu = tonumber(redis.call('HGET', pool_key, 'available_gpu') or '0')

        local cpu_after = avail_cpu - req_cpu
        local memory_after = avail_memory - req_memory
        local gpu_after = avail_gpu - req_gpu

        if cpu_after < min_cpu or memory_after < min_memory or gpu_after < 0 then
            return 0
        end

        redis.call('HSET', pool_key, 'available_cpu', tostring(cpu_after))
        redis.call('HSET', pool_key, 'available_memory', tostring(memory_after))
        redis.call('HSET', pool_key, 'available_gpu', tostring(gpu_after))

        redis.call('HSET', alloc_key, 'cpu', tostring(req_cpu), 'memory', tostring(req_memory),
            'gpu', tostring(req_gpu))
        redis.call('EXPIRE', alloc_key, 7200)

        return 1
        """

        result = await self._redis.eval(  # type: ignore[misc]
            lua_script,
            2,
            self.POOL_KEY,
            alloc_key,
            str(requested_cpu),
            str(requested_memory_mb),
            str(requested_gpu),
            str(self._min_reserve_cpu),
            str(self._min_reserve_memory),
        )

        if not result:
            pool = await self._redis.hgetall(self.POOL_KEY)  # type: ignore[misc]
            avail_cpu = float(pool.get(b"available_cpu", pool.get("available_cpu", 0)))
            avail_memory = int(float(pool.get(b"available_memory", pool.get("available_memory", 0))))
            self._logger.warning(
                f"Insufficient resources for {execution_id}. "
                f"Requested: {requested_cpu} CPU, {requested_memory_mb}MB. "
                f"Available: {avail_cpu} CPU, {avail_memory}MB"
            )
            return None

        self._logger.info(
            f"Allocated resources for {execution_id}: "
            f"{requested_cpu} CPU, {requested_memory_mb}MB RAM, {requested_gpu} GPU"
        )

        return ResourceAllocation(
            execution_id=execution_id,
            cpu_cores=requested_cpu,
            memory_mb=requested_memory_mb,
            gpu_count=requested_gpu,
        )

    async def release(self, execution_id: str) -> bool:
        """Release resource allocation. Returns True if released."""
        alloc_key = f"{self.ALLOC_KEY_PREFIX}:{execution_id}"

        # Get current allocation
        alloc = await self._redis.hgetall(alloc_key)  # type: ignore[misc]
        if not alloc:
            self._logger.warning(f"No allocation found for {execution_id}")
            return False

        cpu = float(alloc.get(b"cpu", alloc.get("cpu", 0)))
        memory = int(float(alloc.get(b"memory", alloc.get("memory", 0))))
        gpu = int(alloc.get(b"gpu", alloc.get("gpu", 0)))

        # Release atomically
        pipe = self._redis.pipeline()
        pipe.hincrbyfloat(self.POOL_KEY, "available_cpu", cpu)
        pipe.hincrbyfloat(self.POOL_KEY, "available_memory", memory)
        pipe.hincrby(self.POOL_KEY, "available_gpu", gpu)
        pipe.delete(alloc_key)
        await pipe.execute()

        self._logger.info(f"Released resources for {execution_id}: {cpu} CPU, {memory}MB RAM, {gpu} GPU")
        return True

    async def get_allocation(self, execution_id: str) -> ResourceAllocation | None:
        """Get current allocation for execution."""
        alloc_key = f"{self.ALLOC_KEY_PREFIX}:{execution_id}"
        alloc = await self._redis.hgetall(alloc_key)  # type: ignore[misc]
        if not alloc:
            return None

        return ResourceAllocation(
            execution_id=execution_id,
            cpu_cores=float(alloc.get(b"cpu", alloc.get("cpu", 0))),
            memory_mb=int(float(alloc.get(b"memory", alloc.get("memory", 0)))),
            gpu_count=int(alloc.get(b"gpu", alloc.get("gpu", 0))),
        )

    async def get_stats(self) -> ResourceStats:
        """Get resource statistics."""
        pool = await self._redis.hgetall(self.POOL_KEY)  # type: ignore[misc]

        # Decode bytes if needed
        def get_val(key: str, default: str = "0") -> str:
            return str(pool.get(key.encode(), pool.get(key, default)))

        total_cpu = float(get_val("total_cpu"))
        total_memory = int(float(get_val("total_memory")))
        total_gpu = int(get_val("total_gpu"))
        available_cpu = float(get_val("available_cpu"))
        available_memory = int(float(get_val("available_memory")))
        available_gpu = int(get_val("available_gpu"))

        # Count allocations
        count = 0
        async for _ in self._redis.scan_iter(match=f"{self.ALLOC_KEY_PREFIX}:*", count=100):
            count += 1

        return ResourceStats(
            total_cpu=total_cpu,
            total_memory_mb=total_memory,
            total_gpu=total_gpu,
            available_cpu=available_cpu,
            available_memory_mb=available_memory,
            available_gpu=available_gpu,
            allocation_count=count,
        )

    async def can_allocate(self, cpu_cores: float, memory_mb: int, gpu_count: int = 0) -> bool:
        """Check if resources can be allocated."""
        pool = await self._redis.hgetall(self.POOL_KEY)  # type: ignore[misc]

        def get_val(key: str) -> float:
            return float(pool.get(key.encode(), pool.get(key, 0)))

        available_cpu = get_val("available_cpu")
        available_memory = get_val("available_memory")
        available_gpu = get_val("available_gpu")

        return (
            (available_cpu - cpu_cores) >= self._min_reserve_cpu
            and (available_memory - memory_mb) >= self._min_reserve_memory
            and (available_gpu - gpu_count) >= 0
        )
