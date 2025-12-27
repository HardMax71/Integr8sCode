import logging
from typing import Any, Optional

from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.domain.enums.events import EventType
from app.events.core import UnifiedProducer
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import AvroEventMetadata as EventMetadata
from app.infrastructure.kafka.events.saga import CreatePodCommandEvent, DeletePodCommandEvent

from .base_saga import BaseSaga
from .saga_step import CompensationStep, SagaContext, SagaStep

logger = logging.getLogger(__name__)


class ValidateExecutionStep(SagaStep[ExecutionRequestedEvent]):
    """Validate execution request"""

    def __init__(self) -> None:
        super().__init__("validate_execution")

    async def execute(self, context: SagaContext, event: ExecutionRequestedEvent) -> bool:
        """Validate execution parameters"""
        try:
            logger.info(f"Validating execution {event.execution_id}")

            # Store execution details in context
            context.set("execution_id", event.execution_id)
            context.set("language", event.language)
            context.set("language_version", event.language_version)
            context.set("script", event.script)
            context.set("timeout_seconds", event.timeout_seconds)

            # Validate script size
            if len(event.script) > 1024 * 1024:  # 1MB limit
                raise ValueError("Script size exceeds limit")

            # Validate timeout
            if event.timeout_seconds is not None and event.timeout_seconds > 300:  # 5 minutes max
                raise ValueError("Timeout exceeds maximum allowed")

            # Additional validations can be added here

            return True

        except Exception as e:
            logger.error(f"Validation failed: {e}")
            context.set_error(e)
            return False

    def get_compensation(self) -> CompensationStep | None:
        """No compensation needed for validation"""
        return None


class AllocateResourcesStep(SagaStep[ExecutionRequestedEvent]):
    """Allocate resources for execution"""

    def __init__(self, alloc_repo: Optional[ResourceAllocationRepository] = None) -> None:
        super().__init__("allocate_resources")
        self.alloc_repo: ResourceAllocationRepository | None = alloc_repo

    async def execute(self, context: SagaContext, event: ExecutionRequestedEvent) -> bool:
        """Allocate computational resources"""
        try:
            if self.alloc_repo is None:
                raise RuntimeError("ResourceAllocationRepository dependency not injected")

            execution_id = context.get("execution_id")
            logger.info(f"Allocating resources for execution {execution_id}")

            # Check resource availability
            # Count current allocations
            active_count = await self.alloc_repo.count_active(event.language)

            # Simple resource limit check (e.g., max 100 concurrent per language)
            if active_count >= 100:
                raise ValueError("Resource limit exceeded")

            # Create allocation record via repository
            ok = await self.alloc_repo.create_allocation(
                execution_id,
                execution_id=execution_id,
                language=event.language,
                cpu_request=event.cpu_request,
                memory_request=event.memory_request,
                cpu_limit=event.cpu_limit,
                memory_limit=event.memory_limit,
            )
            if not ok:
                raise RuntimeError("Failed to persist resource allocation")

            context.set("allocation_id", execution_id)
            context.set("resources_allocated", True)

            return True

        except Exception as e:
            logger.error(f"Resource allocation failed: {e}")
            context.set_error(e)
            return False

    def get_compensation(self) -> CompensationStep | None:
        """Return compensation to release resources"""
        return ReleaseResourcesCompensation(alloc_repo=self.alloc_repo)


class QueueExecutionStep(SagaStep[ExecutionRequestedEvent]):
    """Queue execution for processing"""

    def __init__(self) -> None:
        super().__init__("queue_execution")

    async def execute(self, context: SagaContext, event: ExecutionRequestedEvent) -> bool:
        """Queue execution"""
        try:
            execution_id = context.get("execution_id")
            logger.info(f"Queueing execution {execution_id}")

            # Since we removed execution.queued, we'll mark the context directly
            # The execution is already requested, so we just track that it's ready
            context.set("queued", True)
            logger.info(f"Execution {execution_id} ready for processing")

            return True

        except Exception as e:
            logger.error(f"Queue execution failed: {e}")
            context.set_error(e)
            return False

    def get_compensation(self) -> CompensationStep | None:
        """Return compensation to remove from queue"""
        return RemoveFromQueueCompensation()


class CreatePodStep(SagaStep[ExecutionRequestedEvent]):
    """Create Kubernetes pod"""

    def __init__(self, producer: Optional[UnifiedProducer] = None, publish_commands: Optional[bool] = None) -> None:
        super().__init__("create_pod")
        self.producer: UnifiedProducer | None = producer
        self.publish_commands: Optional[bool] = publish_commands

    async def execute(self, context: SagaContext, event: ExecutionRequestedEvent) -> bool:
        """Trigger pod creation by publishing CreatePodCommandEvent"""
        try:
            execution_id = context.get("execution_id")
            saga_id = context.saga_id
            logger.info(f"Publishing CreatePodCommandEvent for execution {execution_id}")

            # Allow deployments where coordinator publishes commands to avoid duplicates
            publish_commands: bool = bool(self.publish_commands)
            if not publish_commands:
                logger.info(
                    f"Skipping CreatePodCommandEvent publish for execution {execution_id} "
                    f"because publish_commands flag is disabled"
                )
                context.set("pod_creation_triggered", False)
                return True

            # Create the command event for K8sWorker
            create_pod_cmd = CreatePodCommandEvent(
                saga_id=saga_id,
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
                    user_id=event.metadata.user_id if event.metadata else "system",
                ),
            )

            # Publish command to saga_commands topic
            if not self.producer:
                raise RuntimeError("Producer dependency not injected")
            await self.producer.produce(event_to_produce=create_pod_cmd, key=execution_id)

            context.set("pod_creation_triggered", True)
            logger.info(f"CreatePodCommandEvent published for execution {execution_id}")

            return True

        except Exception as e:
            logger.error(f"Pod creation trigger failed: {e}")
            context.set_error(e)
            return False

    def get_compensation(self) -> CompensationStep | None:
        """Return compensation to delete pod"""
        return DeletePodCompensation(producer=self.producer)


class MonitorExecutionStep(SagaStep[ExecutionRequestedEvent]):
    """Monitor execution progress"""

    def __init__(self) -> None:
        super().__init__("monitor_execution")

    async def execute(self, context: SagaContext, event: ExecutionRequestedEvent) -> bool:
        """Set up execution monitoring"""
        try:
            execution_id = context.get("execution_id")
            logger.info(f"Setting up monitoring for execution {execution_id}")

            # Monitoring is handled by PodMonitor service
            # This step ensures the saga waits for completion

            context.set("monitoring_active", True)

            return True

        except Exception as e:
            logger.error(f"Monitor setup failed: {e}")
            context.set_error(e)
            return False

    def get_compensation(self) -> CompensationStep | None:
        """No compensation needed for monitoring"""
        return None


# Compensation Steps


class ReleaseResourcesCompensation(CompensationStep):
    """Release allocated resources"""

    def __init__(self, alloc_repo: Optional[ResourceAllocationRepository] = None) -> None:
        super().__init__("release_resources")
        self.alloc_repo: ResourceAllocationRepository | None = alloc_repo

    async def compensate(self, context: SagaContext) -> bool:
        """Release allocated resources"""
        try:
            if self.alloc_repo is None:
                raise RuntimeError("ResourceAllocationRepository dependency not injected")

            allocation_id = context.get("allocation_id")
            if not allocation_id:
                return True

            logger.info(f"Releasing resources for allocation {allocation_id}")

            await self.alloc_repo.release_allocation(allocation_id)

            return True

        except Exception as e:
            logger.error(f"Failed to release resources: {e}")
            return False


class RemoveFromQueueCompensation(CompensationStep):
    """Remove execution from queue"""

    def __init__(self, producer: Optional[UnifiedProducer] = None) -> None:
        super().__init__("remove_from_queue")
        self.producer: UnifiedProducer | None = producer

    async def compensate(self, context: SagaContext) -> bool:
        """Remove from execution queue"""
        try:
            execution_id = context.get("execution_id")
            if not execution_id or not context.get("queued"):
                return True

            logger.info(f"Removing execution {execution_id} from queue")

            # In a real implementation, this would remove from the actual queue
            # For now, we'll publish a cancellation event

            return True

        except Exception as e:
            logger.error(f"Failed to remove from queue: {e}")
            return False


class DeletePodCompensation(CompensationStep):
    """Delete created pod"""

    def __init__(self, producer: Optional[UnifiedProducer] = None) -> None:
        super().__init__("delete_pod")
        self.producer: UnifiedProducer | None = producer

    async def compensate(self, context: SagaContext) -> bool:
        """Delete Kubernetes pod"""
        try:
            execution_id = context.get("execution_id")
            if not execution_id or not context.get("pod_creation_triggered"):
                return True

            saga_id = context.saga_id
            logger.info(f"Publishing DeletePodCommandEvent for execution {execution_id}")

            if not self.producer:
                raise RuntimeError("Producer dependency not injected")

            # Publish DeletePodCommandEvent for K8sWorker
            delete_pod_cmd = DeletePodCommandEvent(
                saga_id=saga_id,
                execution_id=execution_id,
                reason="Saga compensation due to failure",
                metadata=EventMetadata(
                    service_name="saga-orchestrator", service_version="1.0.0", user_id=context.get("user_id", "system")
                ),
            )

            await self.producer.produce(event_to_produce=delete_pod_cmd, key=execution_id)

            logger.info(f"DeletePodCommandEvent published for {execution_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to trigger pod deletion: {e}")
            return False


class ExecutionSaga(BaseSaga):
    """Saga for managing execution lifecycle"""

    @classmethod
    def get_name(cls) -> str:
        """Get saga name"""
        return "execution_saga"

    @classmethod
    def get_trigger_events(cls) -> list[EventType]:
        """Get events that trigger this saga"""
        return [EventType.EXECUTION_REQUESTED]

    def get_steps(self) -> list[SagaStep[Any]]:
        """Get saga steps in order"""
        alloc_repo = getattr(self, "_alloc_repo", None)
        producer = getattr(self, "_producer", None)
        publish_commands = bool(getattr(self, "_publish_commands", False))
        return [
            ValidateExecutionStep(),
            AllocateResourcesStep(alloc_repo=alloc_repo),
            QueueExecutionStep(),
            CreatePodStep(producer=producer, publish_commands=publish_commands),
            MonitorExecutionStep(),
        ]

    def bind_dependencies(self, **kwargs: object) -> None:
        producer = kwargs.get("producer")
        alloc_repo = kwargs.get("alloc_repo")
        publish_commands = kwargs.get("publish_commands")
        if isinstance(producer, UnifiedProducer):
            self._producer = producer
        if isinstance(alloc_repo, ResourceAllocationRepository):
            self._alloc_repo = alloc_repo
        if isinstance(publish_commands, bool):
            self._publish_commands = publish_commands
