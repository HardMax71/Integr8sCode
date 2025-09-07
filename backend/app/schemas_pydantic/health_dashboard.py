from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums.health import AlertSeverity


class HealthAlert(BaseModel):
    """Health alert information."""
    id: str = Field(..., description="Unique alert identifier")
    severity: AlertSeverity = Field(..., description="Alert severity level")
    service: str = Field(..., description="Service name that triggered the alert")
    status: str = Field(..., description="Current health status")
    message: str = Field(..., description="Alert message")
    timestamp: datetime = Field(..., description="Alert timestamp")
    duration_ms: float = Field(..., description="Check duration in milliseconds")
    error: str | None = Field(None, description="Error details if any")


class HealthMetricsSummary(BaseModel):
    """Summary of health metrics for dashboard display"""
    total_checks: int
    healthy_checks: int
    failed_checks: int
    avg_check_duration_ms: float
    total_failures_24h: int
    uptime_percentage_24h: float


class ServiceMetrics(BaseModel):
    """Detailed metrics for a specific service"""
    service_name: str
    check_count_24h: int
    failure_count_24h: int
    avg_duration_ms: float
    p95_duration_ms: float
    p99_duration_ms: float
    consecutive_failures: int
    last_failure_time: datetime | None = Field(None, description="Last failure timestamp")
    failure_reasons: dict[str, int]


class HealthTrend(BaseModel):
    """Health trend data point"""
    timestamp: datetime = Field(..., description="Trend data timestamp")
    status: str
    healthy_count: int
    unhealthy_count: int
    degraded_count: int


class ServiceHealth(BaseModel):
    """Service health information"""
    name: str
    status: str
    uptime_percentage: float
    last_check: datetime = Field(..., description="Last health check timestamp")
    message: str
    critical: bool


class HealthDashboardResponse(BaseModel):
    """Complete health dashboard response"""
    overall_status: str
    last_updated: datetime = Field(..., description="Dashboard last update timestamp")
    services: list[ServiceHealth]
    statistics: dict[str, int]
    alerts: list[HealthAlert]
    trends: list[HealthTrend]


class SimpleHealthStatus(BaseModel):
    """Simple health status response for public endpoint."""
    status: str = Field(..., description="Health status: 'healthy' or 'unhealthy'")


class HealthStatistics(BaseModel):
    """Health check statistics."""
    total_checks: int
    healthy: int
    degraded: int
    unhealthy: int
    unknown: int


class CategoryServices(BaseModel):
    """Services within a health category."""
    status: str
    message: str
    duration_ms: float
    details: dict[str, object] = Field(default_factory=dict)


class DetailedHealthStatus(BaseModel):
    """Detailed health status with all categories and statistics."""
    timestamp: str = Field(..., description="ISO timestamp of health check")
    overall_status: str = Field(..., description="Overall system health status")
    categories: dict[str, dict[str, CategoryServices]] = Field(
        default_factory=dict, description="Health checks organized by category"
    )
    statistics: HealthStatistics


class HealthCheckConfig(BaseModel):
    """Health check configuration details."""
    type: str | None = None
    critical: bool | None = None
    interval_seconds: float | None = None
    timeout_seconds: float | None = None
    failure_threshold: int | None = None


class HealthCheckState(BaseModel):
    """Current state of health check."""
    consecutive_failures: int
    consecutive_successes: int


class ServiceHealthDetails(BaseModel):
    """Detailed health information for a specific service."""
    name: str
    status: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)
    duration_ms: float
    timestamp: datetime
    error: str | None = None
    check_config: HealthCheckConfig
    state: HealthCheckState


class CategoryHealthStatistics(BaseModel):
    """Statistics for a health category."""
    total: int
    healthy: int
    degraded: int
    unhealthy: int


class CategoryHealthResponse(BaseModel):
    """Health information for a specific category."""
    category: str
    status: str
    services: dict[str, CategoryServices] = Field(default_factory=dict)
    statistics: CategoryHealthStatistics


class DependencyNode(BaseModel):
    """Service dependency graph node."""
    id: str
    label: str
    status: str
    critical: bool
    message: str


class DependencyEdge(BaseModel):
    """Service dependency graph edge."""
    from_service: str = Field(..., alias="from")
    to_service: str = Field(..., alias="to")
    critical: bool

    class Config:
        populate_by_name = True


class DependencyGraph(BaseModel):
    """Service dependency graph structure."""
    nodes: list[DependencyNode]
    edges: list[DependencyEdge]


class ServiceImpactAnalysis(BaseModel):
    """Impact analysis for an unhealthy service."""
    status: str
    affected_services: list[str]
    is_critical: bool


class ServiceDependenciesResponse(BaseModel):
    """Service dependencies and impact analysis."""
    dependency_graph: DependencyGraph
    impact_analysis: dict[str, ServiceImpactAnalysis]
    total_services: int
    healthy_services: int
    critical_services_down: int


class HealthCheckTriggerResponse(BaseModel):
    """Response from manually triggered health check."""
    service: str
    status: str
    message: str
    duration_ms: float
    timestamp: datetime
    details: dict[str, object] = Field(default_factory=dict)
    error: str | None = None
    is_critical: bool


class ServiceHistoryDataPoint(BaseModel):
    """Single data point in service history."""
    timestamp: datetime
    status: str
    duration_ms: float
    healthy: bool


class ServiceHistorySummary(BaseModel):
    """Summary statistics for service history."""
    uptime_percentage: float
    total_checks: int
    healthy_checks: int
    failure_count: int


class ServiceHistoryResponse(BaseModel):
    """Historical health data for a service."""
    service_name: str
    time_range_hours: int
    data_points: list[ServiceHistoryDataPoint]
    summary: ServiceHistorySummary


class SystemMetrics(BaseModel):
    """System-level metrics for real-time status."""
    mongodb_connections: int
    mongodb_ops_per_sec: int
    kafka_total_lag: int
    active_health_checks: int
    failing_checks: int


class ServiceRealtimeStatus(BaseModel):
    """Real-time status for a single service."""
    status: str
    message: str
    duration_ms: float
    last_check: datetime
    details: dict[str, object] = Field(default_factory=dict)


class LastIncident(BaseModel):
    """Information about the last system incident."""
    time: datetime | None = None
    service: str | None = None
    duration_minutes: int | None = None


class RealtimeStatusResponse(BaseModel):
    """Real-time health status with live metrics."""
    timestamp: datetime
    overall_status: str
    services: dict[str, ServiceRealtimeStatus]
    system_metrics: SystemMetrics
    last_incident: LastIncident
