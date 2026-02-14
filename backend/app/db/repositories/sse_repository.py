from datetime import datetime, timezone

from app.db.docs import ExecutionDocument
from app.domain.events import ResourceUsageDomain
from app.domain.execution import DomainExecution
from app.domain.sse import SSEExecutionStatusDomain

_exec_fields = set(DomainExecution.__dataclass_fields__)


class SSERepository:
    async def get_execution_status(self, execution_id: str) -> SSEExecutionStatusDomain | None:
        doc = await ExecutionDocument.find_one(ExecutionDocument.execution_id == execution_id)
        if not doc:
            return None
        return SSEExecutionStatusDomain(
            execution_id=execution_id,
            status=doc.status,
            timestamp=datetime.now(timezone.utc),
        )

    async def get_execution(self, execution_id: str) -> DomainExecution | None:
        doc = await ExecutionDocument.find_one(ExecutionDocument.execution_id == execution_id)
        if not doc:
            return None
        data = doc.model_dump(include=_exec_fields)
        if data.get("resource_usage"):
            data["resource_usage"] = ResourceUsageDomain(**data["resource_usage"])
        return DomainExecution(**data)
