from __future__ import annotations

from typing import Optional

from app.domain.enums.common import ErrorType
from app.domain.enums.storage import ExecutionErrorType
from app.domain.execution import DomainExecution, ResourceUsageDomain
from app.schemas_pydantic.execution import ExecutionResponse, ExecutionResult
from app.schemas_pydantic.execution import ResourceUsage as ResourceUsageSchema


class ExecutionApiMapper:
    @staticmethod
    def to_response(e: DomainExecution) -> ExecutionResponse:
        return ExecutionResponse(
            execution_id=e.execution_id,
            status=e.status,
        )

    @staticmethod
    def to_result(e: DomainExecution) -> ExecutionResult:
        ru = None
        if isinstance(e.resource_usage, ResourceUsageDomain):
            ru = ResourceUsageSchema(**e.resource_usage.to_dict())
        # Map domain ExecutionErrorType -> public ErrorType
        def _map_error(t: Optional[ExecutionErrorType]) -> Optional[ErrorType]:
            if t is None:
                return None
            if t == ExecutionErrorType.SCRIPT_ERROR:
                return ErrorType.SCRIPT_ERROR
            # TIMEOUT, RESOURCE_LIMIT, SYSTEM_ERROR, PERMISSION_DENIED -> SYSTEM_ERROR class
            return ErrorType.SYSTEM_ERROR
        return ExecutionResult(
            execution_id=e.execution_id,
            status=e.status,
            stdout=e.stdout,
            stderr=e.stderr,
            lang=e.lang,
            lang_version=e.lang_version,
            resource_usage=ru,
            exit_code=e.exit_code,
            error_type=_map_error(e.error_type),
        )
