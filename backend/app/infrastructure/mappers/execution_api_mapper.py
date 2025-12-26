from __future__ import annotations

from app.domain.execution import DomainExecution
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
        if e.resource_usage is not None:
            ru = ResourceUsageSchema(**e.resource_usage.to_dict())

        return ExecutionResult(
            execution_id=e.execution_id,
            status=e.status,
            stdout=e.stdout,
            stderr=e.stderr,
            lang=e.lang,
            lang_version=e.lang_version,
            resource_usage=ru,
            exit_code=e.exit_code,
            error_type=e.error_type,
        )
