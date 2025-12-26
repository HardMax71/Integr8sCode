from datetime import datetime, timezone
from typing import Any

from app.domain.enums.execution import ExecutionStatus
from app.domain.execution import DomainExecution, ResourceUsageDomain


class SSEMapper:
    """Mapper for SSE-related domain models from MongoDB documents."""

    @staticmethod
    def execution_from_mongo_document(doc: dict[str, Any]) -> DomainExecution:
        resource_usage_data = doc.get("resource_usage")
        return DomainExecution(
            execution_id=str(doc.get("execution_id")),
            script=str(doc.get("script", "")),
            status=ExecutionStatus(str(doc.get("status"))),
            stdout=doc.get("stdout"),
            stderr=doc.get("stderr"),
            lang=str(doc.get("lang", "python")),
            lang_version=str(doc.get("lang_version", "3.11")),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
            updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
            resource_usage=ResourceUsageDomain.from_dict(resource_usage_data) if resource_usage_data else None,
            user_id=doc.get("user_id"),
            exit_code=doc.get("exit_code"),
            error_type=doc.get("error_type"),
        )
