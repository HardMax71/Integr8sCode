from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import require_admin
from app.core.health_checker import HealthStatus, get_health_check_manager
from app.db.repositories.health_dashboard_repository import (
    HealthDashboardRepository,
    get_health_dashboard_repository,
)
from app.schemas_pydantic.health_dashboard import (
    HealthDashboardResponse,
    HealthMetrics,
    ServiceMetrics,
)
from app.services.health_service import get_health_summary

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/")
async def get_simple_health_status() -> dict[str, str]:
    """
    Get simple health status - public endpoint.
    Returns only 'healthy' or 'unhealthy' status.
    """
    try:
        # Get health check manager
        manager = get_health_check_manager()

        # Get overall status from the manager
        overall_status = manager.get_overall_status()

        # Convert to simple healthy/unhealthy
        if overall_status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]:
            return {"status": "healthy"}
        else:
            return {"status": "unhealthy"}
    except Exception:
        # If we can't determine health, assume unhealthy
        return {"status": "unhealthy"}




@router.get("/dashboard", response_model=HealthDashboardResponse)
async def get_health_dashboard(
        repository: HealthDashboardRepository = Depends(get_health_dashboard_repository),
        current_user: dict = Depends(require_admin)
) -> HealthDashboardResponse:
    """Get complete health dashboard data - admin only"""
    return await repository.get_health_dashboard_data()


@router.get("/detailed")
async def get_detailed_health_status(
        current_user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """
    Get detailed health status of all components - admin only.
    Returns comprehensive health information including all services.
    """
    return await get_health_summary()


@router.get("/dashboard/services/{service_name}")
async def get_service_health_details(
        service_name: str,
        repository: HealthDashboardRepository = Depends(get_health_dashboard_repository),
        current_user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """Get detailed health information for a specific service"""
    return await repository.get_service_health_details(service_name)


@router.get("/dashboard/categories/{category}")
async def get_category_health(
        category: str,
        repository: HealthDashboardRepository = Depends(get_health_dashboard_repository),
        current_user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """Get health information for a specific category"""
    return await repository.get_category_health(category)


@router.get("/dashboard/alerts")
async def get_health_alerts(
        severity: Optional[str] = Query(None, description="Filter by severity: critical, warning, info"),
        limit: int = Query(50, ge=1, le=200),
        repository: HealthDashboardRepository = Depends(get_health_dashboard_repository),
        current_user: dict = Depends(require_admin)
) -> List[Dict[str, Any]]:
    """Get current health alerts"""
    return await repository.get_health_alerts(severity, limit)


@router.get("/dashboard/dependencies")
async def get_service_dependencies(
        repository: HealthDashboardRepository = Depends(get_health_dashboard_repository),
        current_user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """Get service dependency graph for health visualization"""
    return await repository.get_service_dependencies()


@router.post("/dashboard/services/{service_name}/check")
async def trigger_health_check(
        service_name: str,
        repository: HealthDashboardRepository = Depends(get_health_dashboard_repository),
        current_user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """Manually trigger a health check for a service"""
    return await repository.trigger_health_check(service_name)


@router.get("/dashboard/metrics", response_model=HealthMetrics)
async def get_health_metrics(
        repository: HealthDashboardRepository = Depends(get_health_dashboard_repository),
        current_user: dict = Depends(require_admin)
) -> HealthMetrics:
    """Get aggregated health metrics from Prometheus"""
    return await repository.get_health_metrics()


@router.get("/dashboard/metrics/{service_name}", response_model=ServiceMetrics)
async def get_service_metrics(
        service_name: str,
        repository: HealthDashboardRepository = Depends(get_health_dashboard_repository),
        current_user: dict = Depends(require_admin)
) -> ServiceMetrics:
    """Get detailed metrics for a specific service"""
    return await repository.get_service_metrics(service_name)


@router.get("/dashboard/history/{service_name}")
async def get_service_history(
        service_name: str,
        hours: int = Query(24, ge=1, le=168),
        repository: HealthDashboardRepository = Depends(get_health_dashboard_repository),
        current_user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """Get historical health data for a service"""
    return await repository.get_service_history(service_name, hours)


@router.get("/dashboard/realtime")
async def get_realtime_status(
        repository: HealthDashboardRepository = Depends(get_health_dashboard_repository),
        current_user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """Get real-time health status with live updates"""
    return await repository.get_realtime_status()
