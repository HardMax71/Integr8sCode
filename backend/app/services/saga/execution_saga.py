import logging
from datetime import UTC, datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.events.core.producer import UnifiedProducer
from app.schemas_avro.event_schemas import (
    EventType,
    ExecutionRequestedEvent,
    get_topic_for_event,
)
from app.services.saga.saga_orchestrator import BaseSaga
from app.services.saga.saga_step import CompensationStep, SagaContext, SagaStep

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

    def get_compensation(self) -> Optional[CompensationStep]:
        """No compensation needed for validation"""
        return None


class AllocateResourcesStep(SagaStep[ExecutionRequestedEvent]):
    """Allocate resources for execution"""

    def __init__(self) -> None:
        super().__init__("allocate_resources")
        self.producer: Optional[UnifiedProducer] = None
        self.db: Optional[AsyncIOMotorDatabase] = None

    async def execute(self, context: SagaContext, event: ExecutionRequestedEvent) -> bool:
        """Allocate computational resources"""
        try:
            if not self.producer:
                # Get producer from context (set by orchestrator)
                self.producer = context.get("_producer")
                if self.producer is None:
                    raise RuntimeError("Producer not available in saga context")
            if self.db is None:
                # Get database from context (set by orchestrator)
                self.db = context.get("_db")
                if self.db is None:
                    raise RuntimeError("Database not available in saga context")

            execution_id = context.get("execution_id")
            logger.info(f"Allocating resources for execution {execution_id}")

            # Check resource availability
            allocations_collection = self.db.resource_allocations

            # Count current allocations
            active_count = await allocations_collection.count_documents({
                "status": "active",
                "language": event.language
            })

            # Simple resource limit check (e.g., max 100 concurrent per language)
            if active_count >= 100:
                raise ValueError("Resource limit exceeded")

            # Create allocation record
            allocation = {
                "_id": execution_id,
                "execution_id": execution_id,
                "language": event.language,
                "cpu_request": event.cpu_request,
                "memory_request": event.memory_request,
                "cpu_limit": event.cpu_limit,
                "memory_limit": event.memory_limit,
                "status": "active",
                "allocated_at": datetime.now(UTC),
            }

            await allocations_collection.insert_one(allocation)

            context.set("allocation_id", execution_id)
            context.set("resources_allocated", True)

            return True

        except Exception as e:
            logger.error(f"Resource allocation failed: {e}")
            context.set_error(e)
            return False

    def get_compensation(self) -> Optional[CompensationStep]:
        """Return compensation to release resources"""
        return ReleaseResourcesCompensation()


class QueueExecutionStep(SagaStep[ExecutionRequestedEvent]):
    """Queue execution for processing"""

    def __init__(self) -> None:
        super().__init__("queue_execution")
        self.producer: Optional[UnifiedProducer] = None

    async def execute(self, context: SagaContext, event: ExecutionRequestedEvent) -> bool:
        """Queue execution"""
        try:
            if not self.producer:
                # Get producer from context (set by orchestrator)
                self.producer = context.get("_producer")
                if self.producer is None:
                    raise RuntimeError("Producer not available in saga context")

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

    def get_compensation(self) -> Optional[CompensationStep]:
        """Return compensation to remove from queue"""
        return RemoveFromQueueCompensation()


class CreatePodStep(SagaStep[ExecutionRequestedEvent]):
    """Create Kubernetes pod"""

    def __init__(self) -> None:
        super().__init__("create_pod")
        self.producer: Optional[UnifiedProducer] = None

    async def execute(self, context: SagaContext, event: ExecutionRequestedEvent) -> bool:
        """Trigger pod creation"""
        try:
            if not self.producer:
                # Get producer from context (set by orchestrator)
                self.producer = context.get("_producer")
                if self.producer is None:
                    raise RuntimeError("Producer not available in saga context")

            execution_id = context.get("execution_id")
            logger.info(f"Triggering pod creation for execution {execution_id}")

            # The actual pod creation is handled by KubernetesWorker
            # This step just ensures the event flow continues

            context.set("pod_creation_triggered", True)

            return True

        except Exception as e:
            logger.error(f"Pod creation trigger failed: {e}")
            context.set_error(e)
            return False

    def get_compensation(self) -> Optional[CompensationStep]:
        """Return compensation to delete pod"""
        return DeletePodCompensation()


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

    def get_compensation(self) -> Optional[CompensationStep]:
        """No compensation needed for monitoring"""
        return None


# Compensation Steps

class ReleaseResourcesCompensation(CompensationStep):
    """Release allocated resources"""

    def __init__(self) -> None:
        super().__init__("release_resources")
        self.db: Optional[AsyncIOMotorDatabase] = None

    async def compensate(self, context: SagaContext) -> bool:
        """Release allocated resources"""
        try:
            if self.db is None:
                # Get database from context (set by orchestrator)
                self.db = context.get("_db")
                if self.db is None:
                    raise RuntimeError("Database not available in saga context")

            allocation_id = context.get("allocation_id")
            if not allocation_id:
                return True

            logger.info(f"Releasing resources for allocation {allocation_id}")

            allocations_collection = self.db.resource_allocations

            await allocations_collection.update_one(
                {"_id": allocation_id},
                {
                    "$set": {
                        "status": "released",
                        "released_at": datetime.now(UTC),
                    }
                }
            )

            return True

        except Exception as e:
            logger.error(f"Failed to release resources: {e}")
            return False


class RemoveFromQueueCompensation(CompensationStep):
    """Remove execution from queue"""

    def __init__(self) -> None:
        super().__init__("remove_from_queue")
        self.producer: Optional[UnifiedProducer] = None

    async def compensate(self, context: SagaContext) -> bool:
        """Remove from execution queue"""
        try:
            if not self.producer:
                # Get producer from context (set by orchestrator)
                self.producer = context.get("_producer")
                if self.producer is None:
                    raise RuntimeError("Producer not available in saga context")

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

    def __init__(self) -> None:
        super().__init__("delete_pod")
        self.producer: Optional[UnifiedProducer] = None

    async def compensate(self, context: SagaContext) -> bool:
        """Delete Kubernetes pod"""
        try:
            if not self.producer:
                # Get producer from context (set by orchestrator)
                self.producer = context.get("_producer")
                if self.producer is None:
                    raise RuntimeError("Producer not available in saga context")

            execution_id = context.get("execution_id")
            if not execution_id or not context.get("pod_creation_triggered"):
                return True

            logger.info(f"Triggering pod deletion for execution {execution_id}")

            # Publish execution cancelled event which will trigger pod cleanup
            from app.schemas_avro.event_schemas import (
                EventMetadata,
                EventType,
                ExecutionCancelledEvent,
                get_topic_for_event,
            )
            
            cancellation_event = ExecutionCancelledEvent(
                execution_id=execution_id,
                reason="Saga cancellation or compensation",
                metadata=EventMetadata(
                    service_name="saga-orchestrator",
                    service_version="1.0.0",
                    user_id=context.get("user_id", "system")
                )
            )
            
            topic = get_topic_for_event(EventType.EXECUTION_CANCELLED)
            await self.producer.send_event(
                cancellation_event,
                str(topic),
                key=execution_id
            )
            
            logger.info(f"Published execution cancelled event for {execution_id}")
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
    def get_trigger_events(cls) -> list[str]:
        """Get events that trigger this saga"""
        return [str(get_topic_for_event(EventType.EXECUTION_REQUESTED))]

    def get_steps(self) -> list[SagaStep]:
        """Get saga steps in order"""
        return [
            ValidateExecutionStep(),
            AllocateResourcesStep(),
            QueueExecutionStep(),
            CreatePodStep(),
            MonitorExecutionStep(),
        ]
