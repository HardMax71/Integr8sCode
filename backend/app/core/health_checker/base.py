"""
Base health check classes and implementations.

This module provides abstract base classes and concrete implementations
for health checking functionality using modern Python patterns.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, TypeAlias, TypeVar

from app.core.health_checker.models import (
    HealthCheckConfig,
    HealthCheckResult,
    HealthCheckType,
    HealthStatus,
)
from app.core.logging import logger
from app.core.metrics import (
    HEALTH_CHECK_DURATION,
    HEALTH_CHECK_FAILURES,
    HEALTH_CHECK_STATUS,
)
from app.core.tracing import SpanKind, trace_span

# Type aliases
CheckDetails: TypeAlias = dict[str, Any]
ErrorMessage: TypeAlias = str

# Type variable for generic health check
T = TypeVar('T', bound='HealthCheck')


class HealthCheckError(Exception):
    """Base exception for health check errors."""

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class HealthCheck(ABC):
    """
    Abstract base class for health checks.
    
    This class provides the foundation for implementing health checks
    with retry logic, caching, and metrics collection.
    """

    def __init__(
            self,
            name: str,
            check_type: HealthCheckType = HealthCheckType.READINESS,
            config: HealthCheckConfig | None = None,
            critical: bool = True
    ):
        """
        Initialize health check.
        
        Args:
            name: Unique name of the health check.
            check_type: Type of health check (startup, liveness, readiness).
            config: Configuration for the health check.
            critical: Whether this check is critical for overall health.
        """
        self.name = name
        self.check_type = check_type
        self.config = config or HealthCheckConfig()
        self.critical = critical

        # State tracking
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._last_result: HealthCheckResult | None = None
        self._last_check_time: float | None = None
        self._total_checks: int = 0
        self._total_failures: int = 0

        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    @abstractmethod
    async def check(self) -> HealthCheckResult:
        """
        Perform the actual health check.
        
        This method must be implemented by subclasses to perform
        the specific health check logic.
        
        Returns:
            HealthCheckResult with status and details.
            
        Raises:
            Exception: Any exception during health check execution.
        """
        pass

    async def execute(self) -> HealthCheckResult:
        """
        Execute the health check with retries, caching, and metrics.
        
        This method wraps the check() implementation with additional
        functionality like retries, timeout handling, and metrics.
        
        Returns:
            HealthCheckResult with complete execution details.
        """
        # Check cache first
        cached_result = await self._get_cached_result()
        if cached_result:
            logger.debug(f"Using cached result for health check: {self.name}")
            return cached_result

        start_time = time.monotonic()
        result: HealthCheckResult | None = None
        last_error: Exception | None = None

        # Execute with retries
        for attempt in range(self.config.retry_count + 1):
            try:
                result = await self._execute_single_check(attempt)
                if result.is_healthy:
                    break  # Success, no need to retry

                # For non-healthy results, retry if not last attempt
                if attempt < self.config.retry_count:
                    logger.warning(
                        f"Health check {self.name} returned {result.status}, "
                        f"retrying ({attempt + 1}/{self.config.retry_count})"
                    )
                    await asyncio.sleep(self.config.retry_delay_seconds)

            except Exception as e:
                last_error = e
                logger.error(
                    f"Health check {self.name} failed on attempt {attempt + 1}: {e}",
                    exc_info=True
                )

                if attempt < self.config.retry_count:
                    await asyncio.sleep(self.config.retry_delay_seconds)
                else:
                    # Final attempt failed, create error result
                    result = self._create_error_result(e)

        # Ensure we have a result
        if result is None:
            result = self._create_error_result(
                last_error or Exception("Unknown error occurred")
            )

        # Calculate total duration
        duration_ms = (time.monotonic() - start_time) * 1000
        result.duration_ms = duration_ms

        # Update state and metrics
        await self._update_state(result)
        self._update_metrics(result)

        return result

    async def _execute_single_check(self, attempt: int) -> HealthCheckResult:
        """
        Execute a single health check attempt with timeout.
        
        Args:
            attempt: Current attempt number (0-based).
            
        Returns:
            HealthCheckResult from the check.
            
        Raises:
            asyncio.TimeoutError: If check exceeds timeout.
            Exception: Any error from the check implementation.
        """
        with trace_span(
                name=f"health_check.{self.name}",
                kind=SpanKind.INTERNAL,
                attributes={
                    "health_check.name": self.name,
                    "health_check.type": self.check_type.value,
                    "health_check.attempt": attempt + 1,
                    "health_check.critical": self.critical,
                }
        ) as span:
            try:
                result = await asyncio.wait_for(
                    self.check(),
                    timeout=self.config.timeout_seconds
                )

                # Validate result
                if not isinstance(result, HealthCheckResult):
                    raise HealthCheckError(
                        f"Health check {self.name} returned invalid type: "
                        f"{type(result).__name__}"
                    )

                # Ensure name is set
                result.name = self.name

                span.set_attribute("health_check.status", result.status.value)
                span.set_attribute("health_check.healthy", result.is_healthy)

                return result

            except asyncio.TimeoutError:
                span.set_attribute("health_check.timeout", True)
                span.set_attribute("error", True)

                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Health check timed out after {self.config.timeout_seconds}s",
                    error="TimeoutError",
                    details={"timeout_seconds": self.config.timeout_seconds}
                )

    async def _get_cached_result(self) -> HealthCheckResult | None:
        """
        Get cached result if still valid.
        
        Returns:
            Cached HealthCheckResult or None if cache expired/invalid.
        """
        async with self._lock:
            if not self._last_result or not self._last_check_time:
                return None

            age = time.monotonic() - self._last_check_time
            if age < self.config.cache_duration_seconds:
                # Return a copy to prevent modification
                return HealthCheckResult(
                    name=self._last_result.name,
                    status=self._last_result.status,
                    message=self._last_result.message,
                    details={**self._last_result.details, "cached": True},
                    duration_ms=self._last_result.duration_ms,
                    timestamp=self._last_result.timestamp,
                    error=self._last_result.error
                )

            return None

    async def _update_state(self, result: HealthCheckResult) -> None:
        """
        Update internal state based on check result.
        
        Args:
            result: The health check result.
        """
        async with self._lock:
            self._total_checks += 1

            if result.is_healthy:
                self._consecutive_failures = 0
                self._consecutive_successes += 1
            else:
                self._consecutive_failures += 1
                self._consecutive_successes = 0
                self._total_failures += 1

            self._last_result = result
            self._last_check_time = time.monotonic()

    def _update_metrics(self, result: HealthCheckResult) -> None:
        """
        Update health check metrics.
        
        Args:
            result: The health check result.
        """
        # Update status metric (1 for healthy, 0 for unhealthy/degraded)
        status_value = 1.0 if result.is_healthy else 0.0
        HEALTH_CHECK_STATUS.labels(
            service=self.check_type.value,
            check_name=self.name
        ).set(status_value)

        # Record duration
        HEALTH_CHECK_DURATION.labels(
            service=self.check_type.value,
            check_name=self.name
        ).observe(result.duration_ms / 1000.0)

        # Increment failure counter if not healthy
        if not result.is_healthy:
            HEALTH_CHECK_FAILURES.labels(
                service=self.check_type.value,
                check_name=self.name,
                failure_type=result.error or "unknown"
            ).inc()

    def _create_error_result(self, error: Exception) -> HealthCheckResult:
        """
        Create a health check result for an error.
        
        Args:
            error: The exception that occurred.
            
        Returns:
            HealthCheckResult representing the error.
        """
        error_type = type(error).__name__
        error_message = str(error)

        # Extract more details for common errors
        details: CheckDetails = {
            "error_type": error_type,
            "error_message": error_message,
        }

        if hasattr(error, '__cause__') and error.__cause__:
            details["cause"] = str(error.__cause__)

        return HealthCheckResult(
            name=self.name,
            status=HealthStatus.UNHEALTHY,
            message=f"Health check failed: {error_message}",
            error=error_type,
            details=details
        )

    async def get_status(self) -> HealthStatus:
        """
        Get current health status based on consecutive success/failure counts.
        
        Returns:
            Current health status considering thresholds.
        """
        async with self._lock:
            if self._consecutive_failures >= self.config.failure_threshold:
                return HealthStatus.UNHEALTHY
            elif self._consecutive_successes >= self.config.success_threshold:
                return HealthStatus.HEALTHY
            else:
                return HealthStatus.DEGRADED

    async def get_stats(self) -> dict[str, Any]:
        """
        Get statistics about this health check.
        
        Returns:
            Dictionary containing health check statistics.
        """
        async with self._lock:
            return {
                "name": self.name,
                "type": self.check_type.value,
                "critical": self.critical,
                "total_checks": self._total_checks,
                "total_failures": self._total_failures,
                "consecutive_successes": self._consecutive_successes,
                "consecutive_failures": self._consecutive_failures,
                "failure_rate": (
                    self._total_failures / self._total_checks
                    if self._total_checks > 0 else 0.0
                ),
                "last_check_time": (
                    datetime.fromtimestamp(self._last_check_time, tz=timezone.utc).isoformat()
                    if self._last_check_time else None
                ),
                "last_status": self._last_result.status.value if self._last_result else None,
            }

    async def reset_stats(self) -> None:
        """Reset all statistics for this health check."""
        async with self._lock:
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            self._total_checks = 0
            self._total_failures = 0
            self._last_result = None
            self._last_check_time = None


class CompositeHealthCheck(HealthCheck):
    """
    Health check that combines multiple other health checks.
    
    This class allows composing multiple health checks into a single check,
    with configurable logic for determining overall health.
    """

    def __init__(
            self,
            name: str,
            checks: Sequence[HealthCheck],
            check_type: HealthCheckType = HealthCheckType.READINESS,
            config: HealthCheckConfig | None = None,
            require_all: bool = True,
            parallel: bool = True
    ):
        """
        Initialize composite health check.
        
        Args:
            name: Name of the composite check.
            checks: Sequence of health checks to combine.
            check_type: Type of health check.
            config: Health check configuration.
            require_all: If True, all checks must be healthy for composite to be healthy.
            parallel: If True, execute checks in parallel; otherwise sequential.
        """
        super().__init__(name, check_type, config, critical=True)
        self.checks = list(checks)
        self.require_all = require_all
        self.parallel = parallel

        # Validate checks
        if not self.checks:
            raise ValueError("CompositeHealthCheck requires at least one check")

    async def check(self) -> HealthCheckResult:
        """
        Execute all sub-checks and combine results.
        
        Returns:
            Combined health check result with details from all checks.
        """
        if self.parallel:
            results = await self._execute_parallel()
        else:
            results = await self._execute_sequential()

        return self._combine_results(results)

    async def _execute_parallel(self) -> list[tuple[HealthCheck, HealthCheckResult | BaseException]]:
        """
        Execute all checks in parallel.
        
        Returns:
            List of (check, result) tuples.
        """
        tasks = [check.execute() for check in self.checks]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[tuple[HealthCheck, HealthCheckResult | BaseException]] = []
        for check, result in zip(self.checks, raw_results, strict=False):
            results.append((check, result))

        return results

    async def _execute_sequential(self) -> list[tuple[HealthCheck, HealthCheckResult | BaseException]]:
        """
        Execute all checks sequentially.
        
        Returns:
            List of (check, result) tuples.
        """
        results: list[tuple[HealthCheck, HealthCheckResult | BaseException]] = []

        for check in self.checks:
            try:
                result = await check.execute()
                results.append((check, result))
            except Exception as e:
                results.append((check, e))

        return results

    def _combine_results(
            self,
            results: list[tuple[HealthCheck, HealthCheckResult | BaseException]]
    ) -> HealthCheckResult:
        """
        Combine individual results into a composite result.
        
        Args:
            results: List of (check, result) tuples.
            
        Returns:
            Combined HealthCheckResult.
        """
        # Counters and collectors
        total = len(results)
        healthy_count = 0
        degraded_count = 0
        unhealthy_count = 0
        critical_unhealthy = False

        details: CheckDetails = {}
        errors: list[str] = []
        total_duration = 0.0

        # Process each result
        for check, result in results:
            if isinstance(result, BaseException):
                # Handle exception case
                details[check.name] = {
                    "status": HealthStatus.UNHEALTHY.value,
                    "error": type(result).__name__,
                    "message": str(result),
                    "critical": check.critical
                }
                unhealthy_count += 1
                if check.critical:
                    critical_unhealthy = True
                errors.append(f"{check.name}: {result}")

            else:
                # Process normal result
                details[check.name] = {
                    "status": result.status.value,
                    "message": result.message,
                    "duration_ms": result.duration_ms,
                    "critical": check.critical
                }

                if result.error:
                    details[check.name]["error"] = result.error

                total_duration += result.duration_ms

                # Count by status
                match result.status:
                    case HealthStatus.HEALTHY:
                        healthy_count += 1
                    case HealthStatus.DEGRADED:
                        degraded_count += 1
                    case HealthStatus.UNHEALTHY:
                        unhealthy_count += 1
                        if check.critical:
                            critical_unhealthy = True
                        if result.error:
                            errors.append(f"{check.name}: {result.error}")

        # Determine overall status
        if self.require_all:
            # All checks must be healthy
            if critical_unhealthy or unhealthy_count > 0:
                status = HealthStatus.UNHEALTHY
            elif degraded_count > 0:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.HEALTHY
        else:
            # At least one check must be healthy
            if healthy_count == 0:
                status = HealthStatus.UNHEALTHY
            elif healthy_count < total:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.HEALTHY

        # Build message
        message_parts = [f"{healthy_count}/{total} checks healthy"]

        if degraded_count > 0:
            message_parts.append(f"{degraded_count} degraded")

        if unhealthy_count > 0:
            message_parts.append(f"{unhealthy_count} unhealthy")

        message = ", ".join(message_parts)

        if errors:
            message += f". Errors: {'; '.join(errors[:3])}"  # Limit to 3 errors
            if len(errors) > 3:
                message += f" (and {len(errors) - 3} more)"

        # Add summary to details
        details["_summary"] = {
            "total": total,
            "healthy": healthy_count,
            "degraded": degraded_count,
            "unhealthy": unhealthy_count,
            "require_all": self.require_all,
            "has_critical_failure": critical_unhealthy
        }

        return HealthCheckResult(
            name=self.name,
            status=status,
            message=message,
            details=details,
            duration_ms=total_duration,
            error="CompositeCheckFailure" if status == HealthStatus.UNHEALTHY else None
        )

    async def get_check_status(self, check_name: str) -> HealthStatus | None:
        """
        Get the status of a specific sub-check.
        
        Args:
            check_name: Name of the check to query.
            
        Returns:
            Health status of the check or None if not found.
        """
        for check in self.checks:
            if check.name == check_name:
                return await check.get_status()
        return None

    def add_check(self, check: HealthCheck) -> None:
        """
        Add a new health check to the composite.
        
        Args:
            check: Health check to add.
        """
        if check in self.checks:
            raise ValueError(f"Check {check.name} already exists in composite")
        self.checks.append(check)

    def remove_check(self, check_name: str) -> bool:
        """
        Remove a health check from the composite.
        
        Args:
            check_name: Name of the check to remove.
            
        Returns:
            True if removed, False if not found.
        """
        for i, check in enumerate(self.checks):
            if check.name == check_name:
                self.checks.pop(i)
                return True
        return False
