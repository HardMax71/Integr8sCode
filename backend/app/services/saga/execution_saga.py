from typing import Any
from uuid import uuid4

import structlog

from app.db import ResourceAllocationRepository
from app.domain.events import CreatePodCommandEvent, DeletePodCommandEvent, EventMetadata, ExecutionRequestedEvent
from app.domain.saga import DomainResourceAllocationCreate
from app.events import UnifiedProducer

from .saga_step import CompensationStep, SagaContext, SagaStep


class ValidateExecutionStep(SagaStep[ExecutionRequestedEvent]):
    """Validate execution request."""

    def __init__(self, logger: structlog.stdlib.BoundLogger) -> None:
        super().__init__("validate_execution")
        self.logger = logger

    async def execute(self, context: SagaContext, event: ExecutionRequestedEvent) -> bool:
        self.logger.info("Validating execution", execution_id=event.execution_id)

        context.set("execution_id", event.execution_id)
        context.set("language", event.language)
        context.set("language_version", event.language_version)
        context.set("script", event.script)
        context.set("timeout_seconds", event.timeout_seconds)

        if len(event.script) > 1024 * 1024:
            raise ValueError("Script size exceeds limit")

        if event.timeout_seconds is not None and event.timeout_seconds > 300:
            raise ValueError("Timeout exceeds maximum allowed")

        return True

    def get_compensation(self) -> CompensationStep | None:
        return None


class AllocateResourcesStep(SagaStep[ExecutionRequestedEvent]):
    """Allocate resources for execution."""

    def __init__(self, alloc_repo: ResourceAllocationRepository, logger: structlog.stdlib.BoundLogger) -> None:
        super().__init__("allocate_resources")
        self.alloc_repo = alloc_repo
        self.logger = logger

    async def execute(self, context: SagaContext, event: ExecutionRequestedEvent) -> bool:
        execution_id = context.get("execution_id")
        self.logger.info("Allocating resources for execution", execution_id=execution_id)

        active_count = await self.alloc_repo.count_active(event.language)
        if active_count >= 100:
            raise ValueError("Resource limit exceeded")

        allocation = await self.alloc_repo.create_allocation(
            DomainResourceAllocationCreate(
                execution_id=execution_id,
                language=event.language,
                cpu_request=event.cpu_request,
                memory_request=event.memory_request,
                cpu_limit=event.cpu_limit,
                memory_limit=event.memory_limit,
            )
        )

        context.set("allocation_id", allocation.allocation_id)
        context.set("resources_allocated", True)

        return True

    def get_compensation(self) -> CompensationStep | None:
        return ReleaseResourcesCompensation(alloc_repo=self.alloc_repo, logger=self.logger)


class CreatePodStep(SagaStep[ExecutionRequestedEvent]):
    """Create Kubernetes pod."""

    def __init__(self, producer: UnifiedProducer, publish_commands: bool, logger: structlog.stdlib.BoundLogger) -> None:
        super().__init__("create_pod")
        self.producer = producer
        self.publish_commands = publish_commands
        self.logger = logger

    async def execute(self, context: SagaContext, event: ExecutionRequestedEvent) -> bool:
        execution_id = context.get("execution_id")

        if not self.publish_commands:
            self.logger.info(
                "Skipping CreatePodCommandEvent publish",
                execution_id=execution_id,
                reason="publish_commands disabled",
            )
            context.set("pod_creation_triggered", False)
            return True

        self.logger.info("Publishing CreatePodCommandEvent", execution_id=execution_id)

        create_pod_cmd = CreatePodCommandEvent(
            saga_id=context.saga_id,
            execution_id=execution_id,
            script=event.script,
            language=event.language,
            language_version=event.language_version,
            runtime_image=event.runtime_image,
            runtime_command=event.runtime_command,
            runtime_filename=event.runtime_filename,
            timeout_seconds=event.timeout_seconds,
            cpu_limit=event.cpu_limit,
            memory_limit=event.memory_limit,
            cpu_request=event.cpu_request,
            memory_request=event.memory_request,
            priority=event.priority,
            metadata=EventMetadata(
                service_name="saga-orchestrator",
                service_version="1.0.0",
                user_id=event.metadata.user_id,
            ),
        )

        await self.producer.produce(event_to_produce=create_pod_cmd, key=execution_id)

        context.set("pod_creation_triggered", True)
        self.logger.info("CreatePodCommandEvent published", execution_id=execution_id)

        return True

    def get_compensation(self) -> CompensationStep | None:
        return DeletePodCompensation(producer=self.producer, logger=self.logger)


class ReleaseResourcesCompensation(CompensationStep):
    """Release allocated resources."""

    def __init__(self, alloc_repo: ResourceAllocationRepository, logger: structlog.stdlib.BoundLogger) -> None:
        super().__init__("release_resources")
        self.alloc_repo = alloc_repo
        self.logger = logger

    async def compensate(self, context: SagaContext) -> bool:
        allocation_id = context.get("allocation_id")
        if not allocation_id:
            return True

        self.logger.info("Releasing resources", allocation_id=allocation_id)
        await self.alloc_repo.release_allocation(allocation_id)

        return True


class DeletePodCompensation(CompensationStep):
    """Delete created pod."""

    def __init__(self, producer: UnifiedProducer, logger: structlog.stdlib.BoundLogger) -> None:
        super().__init__("delete_pod")
        self.producer = producer
        self.logger = logger

    async def compensate(self, context: SagaContext) -> bool:
        execution_id = context.get("execution_id")
        if not execution_id or not context.get("pod_creation_triggered"):
            return True

        self.logger.info("Publishing DeletePodCommandEvent", execution_id=execution_id)

        delete_pod_cmd = DeletePodCommandEvent(
            saga_id=context.saga_id,
            execution_id=execution_id,
            reason="Saga compensation due to failure",
            metadata=EventMetadata(
                service_name="saga-orchestrator",
                service_version="1.0.0",
                user_id=context.get("user_id") or str(uuid4()),
            ),
        )

        await self.producer.produce(event_to_produce=delete_pod_cmd, key=execution_id)

        self.logger.info("DeletePodCommandEvent published", execution_id=execution_id)
        return True


class ExecutionSaga:
    """Saga for managing execution lifecycle."""

    @classmethod
    def get_name(cls) -> str:
        return "execution_saga"

    def bind_dependencies(
        self,
        producer: UnifiedProducer,
        alloc_repo: ResourceAllocationRepository,
        publish_commands: bool,
        logger: structlog.stdlib.BoundLogger,
    ) -> None:
        self._producer = producer
        self._alloc_repo = alloc_repo
        self._publish_commands = publish_commands
        self._logger = logger

    def get_steps(self) -> list[SagaStep[Any]]:
        return [
            ValidateExecutionStep(logger=self._logger),
            AllocateResourcesStep(alloc_repo=self._alloc_repo, logger=self._logger),
            CreatePodStep(producer=self._producer, publish_commands=self._publish_commands, logger=self._logger),
        ]
