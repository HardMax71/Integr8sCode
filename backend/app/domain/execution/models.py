from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.storage import ExecutionErrorType


@dataclass
class DomainExecution:
    execution_id: str = field(default_factory=lambda: str(uuid4()))
    script: str = ""
    status: ExecutionStatus = ExecutionStatus.QUEUED
    output: Optional[str] = None
    errors: Optional[str] = None
    lang: str = "python"
    lang_version: str = "3.11"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resource_usage: Optional[ResourceUsageDomain] = None
    user_id: Optional[str] = None
    exit_code: Optional[int] = None
    error_type: Optional[ExecutionErrorType] = None


@dataclass
class ExecutionResultDomain:
    execution_id: str
    status: ExecutionStatus
    exit_code: int
    stdout: str
    stderr: str
    resource_usage: ResourceUsageDomain
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
    error_type: Optional[ExecutionErrorType] = None


@dataclass
class ResourceUsageDomain:
    execution_time_wall_seconds: float
    cpu_time_jiffies: int
    clk_tck_hertz: int
    peak_memory_kb: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_time_wall_seconds": float(self.execution_time_wall_seconds),
            "cpu_time_jiffies": int(self.cpu_time_jiffies),
            "clk_tck_hertz": int(self.clk_tck_hertz),
            "peak_memory_kb": int(self.peak_memory_kb),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ResourceUsageDomain":
        return ResourceUsageDomain(
            execution_time_wall_seconds=float(data.get("execution_time_wall_seconds", 0.0)),
            cpu_time_jiffies=int(data.get("cpu_time_jiffies", 0)),
            clk_tck_hertz=int(data.get("clk_tck_hertz", 0)),
            peak_memory_kb=int(data.get("peak_memory_kb", 0)),
        )
