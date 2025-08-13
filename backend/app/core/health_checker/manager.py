"""Health check manager for orchestrating health checks."""
import asyncio
from typing import Callable, Dict, List, Optional

from app.core.health_checker.base import HealthCheck
from app.core.health_checker.models import HealthCheckResult, HealthCheckType, HealthStatus
from app.core.logging import logger


class HealthCheckManager:
    """Manages and orchestrates multiple health checks."""

    _instance: Optional['HealthCheckManager'] = None
    _lock = asyncio.Lock()

    def __new__(cls) -> 'HealthCheckManager':
        """Ensure singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # type: ignore[attr-defined]
        return cls._instance

    def __init__(self) -> None:
        """Initialize the health check manager."""
        if not getattr(self, '_initialized', False):
            self._checks: Dict[str, HealthCheck] = {}
            self._check_tasks: Dict[str, asyncio.Task] = {}
            self._running = False
            self._callbacks: List[Callable[[str, HealthCheckResult], None]] = []
            self._initialized = True  # type: ignore[attr-defined]

    @classmethod
    async def create(cls) -> 'HealthCheckManager':
        """Create health check manager instance.
        
        Returns:
            HealthCheckManager instance
        """
        async with cls._lock:
            return cls()

    def register_check(self, check: HealthCheck) -> None:
        """Register a health check.
        
        Args:
            check: Health check to register
        """
        self._checks[check.name] = check
        logger.info(f"Registered health check: {check.name}")

    def unregister_check(self, name: str) -> None:
        """Unregister a health check.
        
        Args:
            name: Name of the health check to unregister
        """
        if name in self._checks:
            del self._checks[name]
            if name in self._check_tasks:
                self._check_tasks[name].cancel()
                del self._check_tasks[name]
            logger.info(f"Unregistered health check: {name}")

    def add_callback(self, callback: Callable[[str, HealthCheckResult], None]) -> None:
        """Add a callback to be called after each health check.
        
        Args:
            callback: Function to call with check name and result
        """
        self._callbacks.append(callback)

    async def start(self) -> None:
        """Start the health check manager."""
        if self._running:
            return

        self._running = True

        for name, check in self._checks.items():
            if check.check_type == HealthCheckType.STARTUP:
                await asyncio.sleep(check.config.startup_delay_seconds)

            task = asyncio.create_task(self._run_check_loop(name, check))
            self._check_tasks[name] = task

        logger.info(f"Started health check manager with {len(self._checks)} checks")

    async def stop(self) -> None:
        """Stop the health check manager."""
        self._running = False

        for task in self._check_tasks.values():
            task.cancel()

        if self._check_tasks:
            await asyncio.gather(*self._check_tasks.values(), return_exceptions=True)

        self._check_tasks.clear()
        logger.info("Stopped health check manager")

    async def _run_check_loop(self, name: str, check: HealthCheck) -> None:
        """Run periodic health check loop.
        
        Args:
            name: Name of the health check
            check: Health check instance
        """
        while self._running:
            try:
                result = await check.execute()

                for callback in self._callbacks:
                    try:
                        callback(name, result)
                    except Exception as e:
                        logger.error(f"Health check callback error: {e}")

                # Log status changes
                if check._last_result and check._last_result.status != result.status:
                    logger.info(
                        f"Health check '{name}' status changed: "
                        f"{check._last_result.status} -> {result.status}"
                    )

                await asyncio.sleep(check.config.interval_seconds)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop for '{name}': {e}")
                await asyncio.sleep(check.config.interval_seconds)

    async def run_all_checks(self) -> Dict[str, HealthCheckResult]:
        """Run all registered health checks immediately.
        
        Returns:
            Dictionary mapping check names to results
        """
        results = {}

        tasks = {
            name: check.execute()
            for name, check in self._checks.items()
        }

        completed = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for (name, _), result in zip(tasks.items(), completed, strict=False):
            if isinstance(result, BaseException):
                results[name] = HealthCheckResult(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check failed with exception: {str(result)}",
                    error=type(result).__name__
                )
            else:
                # result is HealthCheckResult
                results[name] = result

        return results

    async def get_check_result(self, name: str) -> Optional[HealthCheckResult]:
        """Get result for a specific health check.
        
        Args:
            name: Name of the health check
            
        Returns:
            Health check result or None if not found
        """
        check = self._checks.get(name)
        if not check:
            return None

        return await check.execute()

    def get_overall_status(self, check_type: Optional[HealthCheckType] = None) -> HealthStatus:
        """Get overall health status.
        
        Args:
            check_type: Optional filter by check type
            
        Returns:
            Overall health status
        """
        checks: list[HealthCheck] = list(self._checks.values())

        if check_type:
            checks = [c for c in checks if c.check_type == check_type]

        if not checks:
            return HealthStatus.UNKNOWN

        # Check critical checks first
        critical_checks = [c for c in checks if c.critical]
        for check in critical_checks:
            if check.get_status() == HealthStatus.UNHEALTHY:
                return HealthStatus.UNHEALTHY

        # Check all statuses
        statuses = [check.get_status() for check in checks]

        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        elif any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        else:
            return HealthStatus.DEGRADED

    def get_registered_checks(self) -> List[str]:
        """Get list of registered check names.
        
        Returns:
            List of check names
        """
        return list(self._checks.keys())


def get_health_check_manager() -> HealthCheckManager:
    """Get health check manager instance.
    
    Returns:
        HealthCheckManager singleton instance
    """
    return HealthCheckManager()
