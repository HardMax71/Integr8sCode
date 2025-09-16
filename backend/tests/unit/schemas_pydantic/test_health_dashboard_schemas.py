from datetime import datetime, timezone

from app.schemas_pydantic.health_dashboard import (
    CategoryHealthResponse,
    CategoryHealthStatistics,
    CategoryServices,
    DependencyEdge,
    DependencyGraph,
    DependencyNode,
    DetailedHealthStatus,
    HealthAlert,
    HealthCheckConfig,
    HealthCheckState,
    HealthDashboardResponse,
    HealthMetricsSummary,
    HealthStatistics,
    HealthTrend,
    ServiceHealth,
    ServiceHealthDetails,
    ServiceHistoryDataPoint,
    ServiceHistoryResponse,
    ServiceHistorySummary,
    ServiceRealtimeStatus,
    ServiceDependenciesResponse,
)
from app.domain.enums.health import AlertSeverity


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_alert_and_metrics_and_trend_models():
    alert = HealthAlert(
        id="a1", severity=AlertSeverity.CRITICAL, service="backend", status="unhealthy", message="down",
        timestamp=_now(), duration_ms=12.3
    )
    assert alert.severity is AlertSeverity.CRITICAL

    metrics = HealthMetricsSummary(
        total_checks=10, healthy_checks=7, failed_checks=3, avg_check_duration_ms=5.5, total_failures_24h=3, uptime_percentage_24h=99.1
    )
    assert metrics.total_checks == 10

    trend = HealthTrend(timestamp=_now(), status="ok", healthy_count=10, unhealthy_count=0, degraded_count=0)
    assert trend.healthy_count == 10


def test_service_health_and_dashboard_models():
    svc = ServiceHealth(name="backend", status="healthy", uptime_percentage=99.9, last_check=_now(), message="ok", critical=False)
    dash = HealthDashboardResponse(
        overall_status="healthy", last_updated=_now(), services=[svc], statistics={"total": 1}, alerts=[], trends=[]
    )
    assert dash.overall_status == "healthy"


def test_category_services_and_detailed_status():
    cat = CategoryServices(status="healthy", message="ok", duration_ms=1.0, details={"k": "v"})
    stats = HealthStatistics(total_checks=10, healthy=9, degraded=1, unhealthy=0, unknown=0)
    detailed = DetailedHealthStatus(
        timestamp=_now().isoformat(), overall_status="healthy", categories={"core": {"db": cat}}, statistics=stats
    )
    assert detailed.categories["core"]["db"].status == "healthy"


def test_dependency_graph_and_service_dependencies():
    nodes = [DependencyNode(id="svcA", label="Service A", status="healthy", critical=False, message="ok")]
    edges = [DependencyEdge(**{"from": "svcA", "to": "svcB", "critical": True})]
    graph = DependencyGraph(nodes=nodes, edges=edges)
    assert graph.edges[0].from_service == "svcA" and graph.edges[0].to_service == "svcB"

    from app.schemas_pydantic.health_dashboard import ServiceImpactAnalysis
    impact = {"svcA": ServiceImpactAnalysis(status="ok", affected_services=[], is_critical=False)}
    dep = ServiceDependenciesResponse(
        dependency_graph=graph,
        impact_analysis=impact,
        total_services=1,
        healthy_services=1,
        critical_services_down=0,
    )
    assert dep.total_services == 1


def test_service_health_details_and_history():
    cfg = HealthCheckConfig(type="http", critical=True, interval_seconds=10.0, timeout_seconds=2.0, failure_threshold=3)
    state = HealthCheckState(consecutive_failures=0, consecutive_successes=5)
    details = ServiceHealthDetails(
        name="backend", status="healthy", message="ok", duration_ms=1.2, timestamp=_now(), check_config=cfg, state=state
    )
    assert details.state.consecutive_successes == 5

    dp = ServiceHistoryDataPoint(timestamp=_now(), status="ok", duration_ms=1.0, healthy=True)
    summary = ServiceHistorySummary(uptime_percentage=99.9, total_checks=10, healthy_checks=9, failure_count=1)
    hist = ServiceHistoryResponse(service_name="backend", time_range_hours=24, data_points=[dp], summary=summary)
    assert hist.time_range_hours == 24


def test_realtime_status_model():
    rt = ServiceRealtimeStatus(status="ok", message="fine", duration_ms=2.0, last_check=_now(), details={})
    assert rt.status == "ok"
