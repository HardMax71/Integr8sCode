import asyncio
import pytest

from app.services.coordinator.resource_manager import ResourceManager


@pytest.mark.asyncio
async def test_request_allocation_defaults_and_limits() -> None:
    rm = ResourceManager(total_cpu_cores=8.0, total_memory_mb=16384, total_gpu_count=0)

    # Default for python
    alloc = await rm.request_allocation("e1", "python")
    assert alloc is not None
    assert alloc.cpu_cores > 0
    assert alloc.memory_mb > 0

    # Respect per-exec max cap
    alloc2 = await rm.request_allocation("e2", "python", requested_cpu=100.0, requested_memory_mb=999999)
    assert alloc2 is not None
    assert alloc2.cpu_cores <= rm.pool.max_cpu_per_execution
    assert alloc2.memory_mb <= rm.pool.max_memory_per_execution_mb


@pytest.mark.asyncio
async def test_release_and_can_allocate() -> None:
    rm = ResourceManager(total_cpu_cores=4.0, total_memory_mb=8192, total_gpu_count=0)

    a = await rm.request_allocation("e1", "python", requested_cpu=1.0, requested_memory_mb=512)
    assert a is not None

    ok = await rm.release_allocation("e1")
    assert ok is True

    # After release, can allocate near limits while preserving headroom.
    # Use a tiny epsilon to avoid edge rounding issues in >= comparisons.
    epsilon_cpu = 1e-6
    epsilon_mem = 1
    can = await rm.can_allocate(cpu_cores=rm.pool.total_cpu_cores - rm.pool.min_available_cpu_cores - epsilon_cpu,
                                memory_mb=rm.pool.total_memory_mb - rm.pool.min_available_memory_mb - epsilon_mem,
                                gpu_count=0)
    assert can is True


@pytest.mark.asyncio
async def test_resource_stats() -> None:
    rm = ResourceManager(total_cpu_cores=2.0, total_memory_mb=4096, total_gpu_count=0)
    # Make sure the allocation succeeds
    alloc = await rm.request_allocation("e1", "python", requested_cpu=0.5, requested_memory_mb=256)
    assert alloc is not None, "Allocation should have succeeded"
    
    stats = await rm.get_resource_stats()

    assert stats.total.cpu_cores > 0
    assert stats.available.cpu_cores >= 0
    assert stats.allocated.cpu_cores > 0  # Should be > 0 since we allocated
    assert stats.utilization["cpu_percent"] >= 0
    assert stats.allocation_count >= 1  # Should be at least 1 (may have system allocations)
