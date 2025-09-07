from app.core.metrics.base import BaseMetrics


class HealthMetrics(BaseMetrics):
    """Metrics for health checks."""
    
    def _create_instruments(self) -> None:
        # Core health check metrics - simple histogram to track latest value
        self.health_check_status = self._meter.create_histogram(
            name="health.check.status",
            description="Health check status (1=healthy, 0=unhealthy)",
            unit="1"
        )
        
        self.health_check_duration = self._meter.create_histogram(
            name="health.check.duration",
            description="Time taken to perform health check in seconds",
            unit="s"
        )
        
        self.health_check_failures = self._meter.create_counter(
            name="health.check.failures.total",
            description="Total number of health check failures",
            unit="1"
        )
        
        # Service health metrics
        self.service_health_status = self._meter.create_histogram(
            name="service.health.status",
            description="Service health status by service name",
            unit="1"
        )
        
        self.service_health_score = self._meter.create_histogram(
            name="service.health.score",
            description="Overall health score for a service (0-100)",
            unit="%"
        )
        
        # Liveness and readiness specific metrics
        self.liveness_check_status = self._meter.create_histogram(
            name="liveness.check.status",
            description="Liveness check status (1=alive, 0=dead)",
            unit="1"
        )
        
        self.readiness_check_status = self._meter.create_histogram(
            name="readiness.check.status",
            description="Readiness check status (1=ready, 0=not ready)",
            unit="1"
        )
        
        # Dependency health metrics
        self.dependency_health_status = self._meter.create_histogram(
            name="dependency.health.status",
            description="Health status of external dependencies",
            unit="1"
        )
        
        self.dependency_response_time = self._meter.create_histogram(
            name="dependency.response.time",
            description="Response time for dependency health checks",
            unit="s"
        )
        
        # Health check execution metrics
        self.health_checks_executed = self._meter.create_counter(
            name="health.checks.executed.total",
            description="Total number of health checks executed",
            unit="1"
        )
        
        self.health_check_timeouts = self._meter.create_counter(
            name="health.check.timeouts.total",
            description="Total number of health check timeouts",
            unit="1"
        )
        
        # Component health metrics
        self.component_health_status = self._meter.create_histogram(
            name="component.health.status",
            description="Health status of system components",
            unit="1"
        )
    
    def record_health_check_duration(self, duration_seconds: float, check_type: str, check_name: str) -> None:
        self.health_check_duration.record(
            duration_seconds,
            attributes={
                "check_type": check_type,
                "check_name": check_name
            }
        )
        
        # Also increment execution counter
        self.health_checks_executed.add(
            1,
            attributes={
                "check_type": check_type,
                "check_name": check_name
            }
        )
    
    def record_health_check_failure(self, check_type: str, check_name: str, failure_type: str) -> None:
        self.health_check_failures.add(
            1,
            attributes={
                "check_type": check_type,
                "check_name": check_name,
                "failure_type": failure_type
            }
        )
    
    def update_health_check_status(self, status_value: int, check_type: str, check_name: str) -> None:
        # Just record the current status value
        self.health_check_status.record(
            status_value,
            attributes={"check_type": check_type, "check_name": check_name}
        )
    
    def record_health_status(self, service_name: str, status: str) -> None:
        # Map status to numeric value
        status_value = 1 if status.lower() in ["healthy", "ok", "up"] else 0
        # Record the current status
        self.service_health_status.record(
            status_value,
            attributes={"service": service_name}
        )
    
    def record_service_health_score(self, service_name: str, score: float) -> None:
        self.service_health_score.record(
            score,
            attributes={"service": service_name}
        )
    
    def update_liveness_status(self, is_alive: bool, component: str = "default") -> None:
        status_value = 1 if is_alive else 0
        self.liveness_check_status.record(
            status_value,
            attributes={"component": component}
        )
    
    def update_readiness_status(self, is_ready: bool, component: str = "default") -> None:
        status_value = 1 if is_ready else 0
        self.readiness_check_status.record(
            status_value,
            attributes={"component": component}
        )
    
    def record_dependency_health(self, dependency_name: str, is_healthy: bool, response_time: float) -> None:
        # Update health status
        status_value = 1 if is_healthy else 0
        self.dependency_health_status.record(
            status_value,
            attributes={"dependency": dependency_name}
        )
        
        # Record response time
        self.dependency_response_time.record(
            response_time,
            attributes={"dependency": dependency_name}
        )
    
    def record_health_check_timeout(self, check_type: str, check_name: str) -> None:
        self.health_check_timeouts.add(
            1,
            attributes={
                "check_type": check_type,
                "check_name": check_name
            }
        )
    
    def update_component_health(self, component_name: str, is_healthy: bool) -> None:
        status_value = 1 if is_healthy else 0
        self.component_health_status.record(
            status_value,
            attributes={"component": component_name}
        )
