import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List

from app.core.metrics.context import get_coordinator_metrics


@dataclass
class ResourceAllocation:
    """Resource allocation for an execution"""

    cpu_cores: float
    memory_mb: int
    gpu_count: int = 0

    @property
    def cpu_millicores(self) -> int:
        """Get CPU in millicores for Kubernetes"""
        return int(self.cpu_cores * 1000)

    @property
    def memory_bytes(self) -> int:
        """Get memory in bytes"""
        return self.memory_mb * 1024 * 1024


@dataclass
class ResourcePool:
    """Available resource pool"""

    total_cpu_cores: float
    total_memory_mb: int
    total_gpu_count: int

    available_cpu_cores: float
    available_memory_mb: int
    available_gpu_count: int

    # Resource limits per execution
    max_cpu_per_execution: float = 4.0
    max_memory_per_execution_mb: int = 8192
    max_gpu_per_execution: int = 1

    # Minimum resources to keep available
    min_available_cpu_cores: float = 2.0
    min_available_memory_mb: int = 4096


@dataclass
class ResourceGroup:
    """Resource group with usage information"""

    cpu_cores: float
    memory_mb: int
    gpu_count: int


@dataclass
class ResourceStats:
    """Resource statistics"""

    total: ResourceGroup
    available: ResourceGroup
    allocated: ResourceGroup
    utilization: Dict[str, float]
    allocation_count: int
    limits: Dict[str, int | float]


@dataclass
class ResourceAllocationInfo:
    """Information about a resource allocation"""

    execution_id: str
    cpu_cores: float
    memory_mb: int
    gpu_count: int
    cpu_percentage: float
    memory_percentage: float


class ResourceManager:
    """Manages resource allocation for executions"""

    def __init__(
        self,
        logger: logging.Logger,
        total_cpu_cores: float = 32.0,
        total_memory_mb: int = 65536,  # 64GB
        total_gpu_count: int = 0,
        overcommit_factor: float = 1.2,  # Allow 20% overcommit
    ):
        self.logger = logger
        self.metrics = get_coordinator_metrics()
        self.pool = ResourcePool(
            total_cpu_cores=total_cpu_cores * overcommit_factor,
            total_memory_mb=int(total_memory_mb * overcommit_factor),
            total_gpu_count=total_gpu_count,
            available_cpu_cores=total_cpu_cores * overcommit_factor,
            available_memory_mb=int(total_memory_mb * overcommit_factor),
            available_gpu_count=total_gpu_count,
        )

        # Adjust minimum reserve thresholds proportionally for small pools.
        # Keep at most 10% of total as reserve (but not higher than defaults).
        # This avoids refusing small, reasonable allocations on modest clusters.
        self.pool.min_available_cpu_cores = min(
            self.pool.min_available_cpu_cores,
            max(0.1 * self.pool.total_cpu_cores, 0.0),
        )
        self.pool.min_available_memory_mb = min(
            self.pool.min_available_memory_mb,
            max(int(0.1 * self.pool.total_memory_mb), 0),
        )

        # Track allocations
        self._allocations: Dict[str, ResourceAllocation] = {}
        self._allocation_lock = asyncio.Lock()

        # Default allocations by language
        self.default_allocations = {
            "python": ResourceAllocation(cpu_cores=0.5, memory_mb=512),
            "javascript": ResourceAllocation(cpu_cores=0.5, memory_mb=512),
            "go": ResourceAllocation(cpu_cores=0.25, memory_mb=256),
            "rust": ResourceAllocation(cpu_cores=0.5, memory_mb=512),
            "java": ResourceAllocation(cpu_cores=1.0, memory_mb=1024),
            "cpp": ResourceAllocation(cpu_cores=0.5, memory_mb=512),
            "r": ResourceAllocation(cpu_cores=1.0, memory_mb=2048),
        }

        # Update initial metrics
        self._update_metrics()

    async def request_allocation(
        self,
        execution_id: str,
        language: str,
        requested_cpu: float | None = None,
        requested_memory_mb: int | None = None,
        requested_gpu: int = 0,
    ) -> ResourceAllocation | None:
        """
        Request resource allocation for execution

        Returns:
            ResourceAllocation if successful, None if resources unavailable
        """
        async with self._allocation_lock:
            # Check if already allocated
            if execution_id in self._allocations:
                self.logger.warning(f"Execution {execution_id} already has allocation")
                return self._allocations[execution_id]

            # Determine requested resources
            if requested_cpu is None or requested_memory_mb is None:
                # Use defaults based on language
                default = self.default_allocations.get(language, ResourceAllocation(cpu_cores=0.5, memory_mb=512))
                requested_cpu = requested_cpu or default.cpu_cores
                requested_memory_mb = requested_memory_mb or default.memory_mb

            # Apply limits
            requested_cpu = min(requested_cpu, self.pool.max_cpu_per_execution)
            requested_memory_mb = min(requested_memory_mb, self.pool.max_memory_per_execution_mb)
            requested_gpu = min(requested_gpu, self.pool.max_gpu_per_execution)

            # Check availability (considering minimum reserves)
            cpu_after = self.pool.available_cpu_cores - requested_cpu
            memory_after = self.pool.available_memory_mb - requested_memory_mb
            gpu_after = self.pool.available_gpu_count - requested_gpu

            if (
                cpu_after < self.pool.min_available_cpu_cores
                or memory_after < self.pool.min_available_memory_mb
                or gpu_after < 0
            ):
                self.logger.warning(
                    f"Insufficient resources for execution {execution_id}. "
                    f"Requested: {requested_cpu} CPU, {requested_memory_mb}MB RAM, "
                    f"{requested_gpu} GPU. Available: {self.pool.available_cpu_cores} CPU, "
                    f"{self.pool.available_memory_mb}MB RAM, {self.pool.available_gpu_count} GPU"
                )
                return None

            # Create allocation
            allocation = ResourceAllocation(
                cpu_cores=requested_cpu, memory_mb=requested_memory_mb, gpu_count=requested_gpu
            )

            # Update pool
            self.pool.available_cpu_cores = cpu_after
            self.pool.available_memory_mb = memory_after
            self.pool.available_gpu_count = gpu_after

            # Track allocation
            self._allocations[execution_id] = allocation

            # Update metrics
            self._update_metrics()

            self.logger.info(
                f"Allocated resources for execution {execution_id}: "
                f"{allocation.cpu_cores} CPU, {allocation.memory_mb}MB RAM, "
                f"{allocation.gpu_count} GPU"
            )

            return allocation

    async def release_allocation(self, execution_id: str) -> bool:
        """Release resource allocation"""
        async with self._allocation_lock:
            if execution_id not in self._allocations:
                self.logger.warning(f"No allocation found for execution {execution_id}")
                return False

            allocation = self._allocations[execution_id]

            # Return resources to pool
            self.pool.available_cpu_cores += allocation.cpu_cores
            self.pool.available_memory_mb += allocation.memory_mb
            self.pool.available_gpu_count += allocation.gpu_count

            # Remove allocation
            del self._allocations[execution_id]

            # Update metrics
            self._update_metrics()

            self.logger.info(
                f"Released resources for execution {execution_id}: "
                f"{allocation.cpu_cores} CPU, {allocation.memory_mb}MB RAM, "
                f"{allocation.gpu_count} GPU"
            )

            return True

    async def get_allocation(self, execution_id: str) -> ResourceAllocation | None:
        """Get current allocation for execution"""
        async with self._allocation_lock:
            return self._allocations.get(execution_id)

    async def can_allocate(self, cpu_cores: float, memory_mb: int, gpu_count: int = 0) -> bool:
        """Check if resources can be allocated"""
        async with self._allocation_lock:
            cpu_after = self.pool.available_cpu_cores - cpu_cores
            memory_after = self.pool.available_memory_mb - memory_mb
            gpu_after = self.pool.available_gpu_count - gpu_count

            return (
                cpu_after >= self.pool.min_available_cpu_cores
                and memory_after >= self.pool.min_available_memory_mb
                and gpu_after >= 0
            )

    async def get_resource_stats(self) -> ResourceStats:
        """Get resource statistics"""
        async with self._allocation_lock:
            allocated_cpu = self.pool.total_cpu_cores - self.pool.available_cpu_cores
            allocated_memory = self.pool.total_memory_mb - self.pool.available_memory_mb
            allocated_gpu = self.pool.total_gpu_count - self.pool.available_gpu_count

            gpu_percent = (allocated_gpu / self.pool.total_gpu_count * 100) if self.pool.total_gpu_count > 0 else 0

            return ResourceStats(
                total=ResourceGroup(
                    cpu_cores=self.pool.total_cpu_cores,
                    memory_mb=self.pool.total_memory_mb,
                    gpu_count=self.pool.total_gpu_count,
                ),
                available=ResourceGroup(
                    cpu_cores=self.pool.available_cpu_cores,
                    memory_mb=self.pool.available_memory_mb,
                    gpu_count=self.pool.available_gpu_count,
                ),
                allocated=ResourceGroup(cpu_cores=allocated_cpu, memory_mb=allocated_memory, gpu_count=allocated_gpu),
                utilization={
                    "cpu_percent": (allocated_cpu / self.pool.total_cpu_cores * 100),
                    "memory_percent": (allocated_memory / self.pool.total_memory_mb * 100),
                    "gpu_percent": gpu_percent,
                },
                allocation_count=len(self._allocations),
                limits={
                    "max_cpu_per_execution": self.pool.max_cpu_per_execution,
                    "max_memory_per_execution_mb": self.pool.max_memory_per_execution_mb,
                    "max_gpu_per_execution": self.pool.max_gpu_per_execution,
                },
            )

    async def get_allocations_by_resource_usage(self) -> List[ResourceAllocationInfo]:
        """Get allocations sorted by resource usage"""
        async with self._allocation_lock:
            allocations = []
            for exec_id, allocation in self._allocations.items():
                allocations.append(
                    ResourceAllocationInfo(
                        execution_id=str(exec_id),
                        cpu_cores=allocation.cpu_cores,
                        memory_mb=allocation.memory_mb,
                        gpu_count=allocation.gpu_count,
                        cpu_percentage=(allocation.cpu_cores / self.pool.total_cpu_cores * 100),
                        memory_percentage=(allocation.memory_mb / self.pool.total_memory_mb * 100),
                    )
                )

            # Sort by total resource usage
            allocations.sort(key=lambda x: x.cpu_percentage + x.memory_percentage, reverse=True)

            return allocations

    def _update_metrics(self) -> None:
        """Update metrics"""
        cpu_usage = self.pool.total_cpu_cores - self.pool.available_cpu_cores
        cpu_percent = cpu_usage / self.pool.total_cpu_cores * 100
        self.metrics.update_resource_usage("cpu", cpu_percent)

        memory_usage = self.pool.total_memory_mb - self.pool.available_memory_mb
        memory_percent = memory_usage / self.pool.total_memory_mb * 100
        self.metrics.update_resource_usage("memory", memory_percent)

        gpu_usage = self.pool.total_gpu_count - self.pool.available_gpu_count
        gpu_percent = gpu_usage / max(1, self.pool.total_gpu_count) * 100
        self.metrics.update_resource_usage("gpu", gpu_percent)

        self.metrics.update_coordinator_active_executions(len(self._allocations))
