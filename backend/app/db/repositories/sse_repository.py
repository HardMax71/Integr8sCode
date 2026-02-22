from datetime import datetime, timezone

from app.db.docs import ExecutionDocument
from app.domain.events import ResourceUsageDomain
from app.domain.execution.models import ExecutionResultDomain
from app.domain.sse import SSEExecutionStatusDomain

_result_fields = set(ExecutionResultDomain.__dataclass_fields__)


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

    async def get_execution_result(self, execution_id: str) -> ExecutionResultDomain | None:
        doc = await ExecutionDocument.find_one(ExecutionDocument.execution_id == execution_id)
        if not doc:
            return None
        data = doc.model_dump(include=_result_fields)
        if data.get("resource_usage"):
            data["resource_usage"] = ResourceUsageDomain(**data["resource_usage"])
        return ExecutionResultDomain(**data)
