from datetime import datetime
from app.core.execution import ExecutionEngine, ExecutionStatus
from app.core.exceptions import IntegrationException
from app.core.metrics import (
    SCRIPT_EXECUTIONS,
    EXECUTION_DURATION,
    ACTIVE_EXECUTIONS,
    ERROR_COUNTER,
)
from app.db.repositories.execution_repository import ExecutionRepository
from app.models.execution import ExecutionCreate, ExecutionInDB, ExecutionUpdate
from time import time


class ExecutionOrchestrator:
    def __init__(
        self,
        repository: ExecutionRepository,
        engine: ExecutionEngine,
    ):
        self.repository = repository
        self.engine = engine

    async def start_execution(self, script: str, runtime_version: str) -> ExecutionInDB:
        ACTIVE_EXECUTIONS.inc()
        start_time = time()

        try:
            # Create execution record
            execution = ExecutionCreate(
                script=script,
                python_version=runtime_version,
                status=ExecutionStatus.QUEUED,
            )
            execution_in_db = ExecutionInDB(**execution.dict())
            await self.repository.create_execution(execution_in_db)

            try:
                # Start execution
                await self.engine.start_execution(
                    execution_id=execution_in_db.id,
                    script=script,
                    runtime_version=runtime_version,
                )

                # Update status to running
                await self.repository.update_execution(
                    execution_in_db.id,
                    ExecutionUpdate(status=ExecutionStatus.RUNNING).dict(),
                )

                SCRIPT_EXECUTIONS.labels(
                    status="success", python_version=runtime_version
                ).inc()

            except Exception as e:
                error_message = f"Failed to start execution: {str(e)}"
                await self.repository.update_execution(
                    execution_in_db.id,
                    ExecutionUpdate(
                        status=ExecutionStatus.FAILED, errors=error_message
                    ).dict(),
                )

                SCRIPT_EXECUTIONS.labels(
                    status="error", python_version=runtime_version
                ).inc()
                ERROR_COUNTER.labels(error_type=type(e).__name__).inc()

                raise IntegrationException(status_code=500, detail=error_message)

            return await self.repository.get_execution(execution_in_db.id)

        finally:
            EXECUTION_DURATION.labels(python_version=runtime_version).observe(
                time() - start_time
            )
            ACTIVE_EXECUTIONS.dec()

    async def get_execution_result(self, execution_id: str) -> ExecutionInDB:
        execution = await self.repository.get_execution(execution_id)
        if not execution:
            ERROR_COUNTER.labels(error_type="ExecutionNotFound").inc()
            raise IntegrationException(status_code=404, detail="Execution not found")

        if execution.status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED]:
            return execution

        try:
            output, error = await self.engine.get_execution_output(execution_id)

            if error:
                update_data = ExecutionUpdate(
                    status=ExecutionStatus.FAILED, errors=error
                ).dict()
                SCRIPT_EXECUTIONS.labels(
                    status="error", python_version=execution.python_version
                ).inc()
                ERROR_COUNTER.labels(error_type="ExecutionError").inc()
            else:
                update_data = ExecutionUpdate(
                    status=ExecutionStatus.COMPLETED, output=output
                ).dict()
                SCRIPT_EXECUTIONS.labels(
                    status="success", python_version=execution.python_version
                ).inc()

            await self.repository.update_execution(execution_id, update_data)
        except Exception as e:
            ERROR_COUNTER.labels(error_type=type(e).__name__).inc()
            update_data = ExecutionUpdate(
                status=ExecutionStatus.FAILED, errors=str(e)
            ).dict()
            await self.repository.update_execution(execution_id, update_data)

        return await self.repository.get_execution(execution_id)
