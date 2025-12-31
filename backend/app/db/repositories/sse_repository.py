from datetime import datetime, timezone

from app.db.docs import ExecutionDocument
from app.domain.execution import DomainExecution
from app.domain.sse import SSEExecutionStatusDomain


class SSERepository:
    async def get_execution_status(self, execution_id: str) -> SSEExecutionStatusDomain | None:
        doc = await ExecutionDocument.find_one({"execution_id": execution_id})
        if not doc:
            return None
        return SSEExecutionStatusDomain(
            execution_id=execution_id,
            status=doc.status,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    async def get_execution(self, execution_id: str) -> DomainExecution | None:
        doc = await ExecutionDocument.find_one({"execution_id": execution_id})
        if not doc:
            return None
        return DomainExecution(**doc.model_dump(exclude={"id", "revision_id"}))
