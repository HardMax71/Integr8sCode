"""Health dashboard schemas"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class HealthMetrics(BaseModel):
    """Real-time health metrics"""
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
    last_failure_time: Optional[datetime]
    failure_reasons: Dict[str, int]


class HealthTrend(BaseModel):
    """Health trend data point"""
    timestamp: datetime
    status: str
    healthy_count: int
    unhealthy_count: int
    degraded_count: int


class ServiceHealth(BaseModel):
    """Service health information"""
    name: str
    status: str
    uptime_percentage: float
    last_check: datetime
    message: str
    critical: bool


class HealthDashboardResponse(BaseModel):
    """Complete health dashboard response"""
    overall_status: str
    last_updated: datetime
    services: List[ServiceHealth]
    statistics: Dict[str, int]
    alerts: List[Dict[str, Any]]
    trends: List[HealthTrend]
