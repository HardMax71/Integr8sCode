from datetime import datetime, timezone
from typing import Any, Dict

from app.domain.enums.execution import ExecutionStatus
from app.domain.execution import DomainExecution, ResourceUsageDomain
from app.domain.sse import SSEEventDomain, SSEExecutionStatusDomain


class SSEMapper:
    """Mapper for SSE-related domain models and MongoDB documents."""

    # Execution status (lightweight)
    @staticmethod
    def to_execution_status(execution_id: str, status: str) -> SSEExecutionStatusDomain:
        return SSEExecutionStatusDomain(
            execution_id=execution_id,
            status=status,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # Execution events
    @staticmethod
    def event_from_mongo_document(doc: Dict[str, Any]) -> SSEEventDomain:
        return SSEEventDomain(
            aggregate_id=str(doc.get("aggregate_id", "")),
            timestamp=doc.get("timestamp"),
        )

    # Executions
    @staticmethod
    def execution_from_mongo_document(doc: Dict[str, Any]) -> DomainExecution:
        sv = doc.get("status")
        return DomainExecution(
            execution_id=str(doc.get("execution_id")),
            script=str(doc.get("script", "")),
            status=ExecutionStatus(str(sv)),
            stdout=doc.get("stdout"),
            stderr=doc.get("stderr"),
            lang=str(doc.get("lang", "python")),
            lang_version=str(doc.get("lang_version", "3.11")),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
            updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
            resource_usage=ResourceUsageDomain.from_dict(doc.get("resource_usage") or {}),
            user_id=doc.get("user_id"),
            exit_code=doc.get("exit_code"),
            error_type=doc.get("error_type"),
        )
