from enum import Enum
from typing import Protocol, Optional


class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionEngine(Protocol):
    """Interface for execution engines"""

    async def start_execution(
        self, execution_id: str, script: str, runtime_version: str
    ) -> None:
        """Start script execution"""
        pass

    async def get_execution_output(
        self, execution_id: str
    ) -> tuple[str, Optional[str]]:
        """Get execution output and errors"""
        pass
