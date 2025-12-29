from datetime import datetime, timezone

from app.db.docs import ExecutionDocument
from app.domain.enums.execution import ExecutionStatus


class SSEExecutionStatus:
    def __init__(self, execution_id: str, status: ExecutionStatus, timestamp: str):
        self.execution_id = execution_id
        self.status = status
        self.timestamp = timestamp


class SSERepository:

    async def get_execution_status(self, execution_id: str) -> SSEExecutionStatus | None:
        doc = await ExecutionDocument.find_one({"execution_id": execution_id})
        if not doc:
            return None
        return SSEExecutionStatus(
            execution_id=execution_id,
            status=doc.status,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    async def get_execution(self, execution_id: str) -> ExecutionDocument | None:
        return await ExecutionDocument.find_one({"execution_id": execution_id})
