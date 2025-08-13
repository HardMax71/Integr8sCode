"""Saga orchestrator for managing distributed transactions"""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Dict, List, Optional, Type
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.db.mongodb import DatabaseManager
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.producer import UnifiedProducer, get_producer
from app.events.store.event_store import EventStore, get_event_store
from app.schemas_avro.event_schemas import BaseEvent
from app.services.idempotency import IdempotentConsumerWrapper
from app.services.saga.saga_step import SagaContext, SagaStep

logger = logging.getLogger(__name__)


class SagaState(StrEnum):
    """Saga execution states"""
    CREATED = "created"
    RUNNING = "running"
    COMPENSATING = "compensating"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class SagaConfig(BaseModel):
    """Saga configuration"""

    name: str
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_delay_seconds: int = Field(default=5, ge=1, le=60)
    enable_compensation: bool = Field(default=True)
    store_events: bool = Field(default=True)


class SagaInstance(BaseModel):
    """Saga instance data"""

    saga_id: str = Field(default_factory=lambda: str(uuid4()))
    saga_name: str
    execution_id: str
    state: SagaState = Field(default=SagaState.CREATED)
    current_step: Optional[str] = None
    completed_steps: List[str] = Field(default_factory=list)
    compensated_steps: List[str] = Field(default_factory=list)
    context_data: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    retry_count: int = Field(default=0)


class SagaOrchestrator:
    """Orchestrates saga execution and compensation"""

    def __init__(self, config: SagaConfig, db_manager: Optional[DatabaseManager] = None):
        self.config = config
        self.db_manager = db_manager
        self._sagas: Dict[str, Type['BaseSaga']] = {}
        self._running_instances: Dict[str, SagaInstance] = {}
        self._consumer: Optional[IdempotentConsumerWrapper] = None
        self._producer: Optional[UnifiedProducer] = None
        self._event_store: Optional[EventStore] = None
        self._db: Optional[AsyncIOMotorDatabase[Any]] = None
        self._running = False
        self._tasks: List[asyncio.Task] = []

    def register_saga(self, saga_class: Type['BaseSaga']) -> None:
        """Register a saga class"""
        self._sagas[saga_class.get_name()] = saga_class
        logger.info(f"Registered saga: {saga_class.get_name()}")

    async def start(self) -> None:
        """Start the saga orchestrator"""
        logger.info(f"Starting saga orchestrator: {self.config.name}")

        # Initialize components
        if not self.db_manager:
            raise RuntimeError("DatabaseManager not provided to SagaOrchestrator")
        self._db = self.db_manager.get_database()
        self._producer = await get_producer()
        if self.config.store_events:
            self._event_store = get_event_store()

        # Create indexes
        await self._create_indexes()

        # Start consumer
        await self._start_consumer()

        # Start timeout checker
        timeout_task = asyncio.create_task(self._check_timeouts())
        self._tasks.append(timeout_task)

        self._running = True
        logger.info("Saga orchestrator started")

    async def stop(self) -> None:
        """Stop the saga orchestrator"""
        logger.info("Stopping saga orchestrator...")

        self._running = False

        # Stop consumer
        if self._consumer:
            await self._consumer.stop()

        # Cancel tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        logger.info("Saga orchestrator stopped")

    async def _create_indexes(self) -> None:
        """Create database indexes"""
        if self._db is None:
            raise RuntimeError("Database not initialized")
        sagas_collection = self._db.sagas

        await sagas_collection.create_index("saga_id", unique=True)
        await sagas_collection.create_index("execution_id")
        await sagas_collection.create_index("state")
        await sagas_collection.create_index("created_at")
        await sagas_collection.create_index([("state", 1), ("created_at", 1)])

    async def _start_consumer(self) -> None:
        """Start Kafka consumer for saga events"""
        # Get all trigger events from registered sagas
        topics = set()
        for saga_class in self._sagas.values():
            topics.update(saga_class.get_trigger_events())

        if not topics:
            logger.warning("No trigger events found in registered sagas")
            return

        consumer_config = ConsumerConfig(
            group_id=f"saga-{self.config.name}",
            topics=list(topics),
            enable_auto_commit=False,
        )

        consumer = UnifiedConsumer(consumer_config)

        # Wrap with idempotency
        self._consumer = IdempotentConsumerWrapper(
            consumer=consumer,
            default_key_strategy="event_based",
            default_ttl_seconds=7200,  # 2 hours
            enable_for_all_handlers=False
        )

        # Subscribe handler with idempotency
        # Use saga-specific idempotency key to prevent duplicate saga execution
        self._consumer.subscribe_idempotent_handler(
            "*",  # Handle all events
            self._handle_event,
            key_strategy="custom",
            custom_key_func=lambda e: f"saga:{e.event_type}:{e.event_id}",
            ttl_seconds=7200,
            cache_result=False
        )

        await self._consumer.consumer.start()

        logger.info(f"Saga consumer started for topics: {topics}")

    async def _handle_event(self, event: BaseEvent) -> None:
        """Handle incoming event"""
        try:
            # Check if event triggers any saga
            for saga_name, saga_class in self._sagas.items():
                if self._should_trigger_saga(saga_class, event):
                    await self._start_saga(saga_name, event)

            # Check if event is part of running saga
            await self._process_saga_event(event)

        except Exception as e:
            logger.error(f"Error handling event {event.event_id}: {e}", exc_info=True)

    def _should_trigger_saga(self, saga_class: Type['BaseSaga'], event: BaseEvent) -> bool:
        """Check if event should trigger saga"""
        trigger_events = saga_class.get_trigger_events()
        return str(event.event_type) in trigger_events

    async def _start_saga(self, saga_name: str, trigger_event: BaseEvent) -> str | None:
        """Start a new saga instance"""
        saga_class = self._sagas.get(saga_name)
        if not saga_class:
            raise ValueError(f"Unknown saga: {saga_name}")

        # Extract execution ID from event
        execution_id = self._extract_execution_id(trigger_event)
        if not execution_id:
            logger.warning(f"Could not extract execution ID from event: {trigger_event}")
            return None

        # Create saga instance
        instance = SagaInstance(
            saga_name=saga_name,
            execution_id=execution_id,
            state=SagaState.RUNNING,
        )

        # Store in database
        await self._save_saga_instance(instance)

        # Store in memory
        self._running_instances[instance.saga_id] = instance

        logger.info(f"Started saga {saga_name} (ID: {instance.saga_id}) for execution {execution_id}")

        # Create saga and context
        saga = saga_class()
        context = SagaContext(instance.saga_id, execution_id)
        # Pass database to context for saga steps
        context.set("_db", self._db)

        # Start processing
        asyncio.create_task(self._execute_saga(saga, instance, context, trigger_event))

        return instance.saga_id

    async def _execute_saga(
            self,
            saga: 'BaseSaga',
            instance: SagaInstance,
            context: SagaContext,
            trigger_event: BaseEvent,
    ) -> None:
        """Execute saga steps"""
        try:
            # Get saga steps
            steps = saga.get_steps()

            # Execute each step
            for step in steps:
                if not self._running:
                    break

                # Update current step
                instance.current_step = step.name
                await self._save_saga_instance(instance)

                logger.info(f"Executing saga step: {step.name} for saga {instance.saga_id}")

                # Execute step
                success = await step.execute(context, trigger_event)

                if success:
                    # Mark step as completed
                    instance.completed_steps.append(step.name)

                    # Add compensation if available
                    compensation = step.get_compensation()
                    if compensation:
                        context.add_compensation(compensation)
                else:
                    # Step failed, start compensation
                    logger.error(f"Saga step {step.name} failed for saga {instance.saga_id}")

                    if self.config.enable_compensation:
                        await self._compensate_saga(instance, context)
                    else:
                        await self._fail_saga(instance, "Step failed without compensation")

                    return

            # All steps completed successfully
            await self._complete_saga(instance)

        except Exception as e:
            logger.error(f"Error executing saga {instance.saga_id}: {e}", exc_info=True)

            if self.config.enable_compensation:
                await self._compensate_saga(instance, context)
            else:
                await self._fail_saga(instance, str(e))

    async def _compensate_saga(self, instance: SagaInstance, context: SagaContext) -> None:
        """Execute compensation steps"""
        logger.info(f"Starting compensation for saga {instance.saga_id}")

        instance.state = SagaState.COMPENSATING
        await self._save_saga_instance(instance)

        # Execute compensations in reverse order
        for compensation in reversed(context.compensations):
            try:
                logger.info(f"Executing compensation: {compensation.name} for saga {instance.saga_id}")

                success = await compensation.compensate(context)

                if success:
                    instance.compensated_steps.append(compensation.name)
                else:
                    logger.error(f"Compensation {compensation.name} failed for saga {instance.saga_id}")

            except Exception as e:
                logger.error(f"Error in compensation {compensation.name}: {e}", exc_info=True)

        # Mark saga as failed after compensation
        await self._fail_saga(instance, "Saga compensated due to failure")

    async def _complete_saga(self, instance: SagaInstance) -> None:
        """Mark saga as completed"""
        instance.state = SagaState.COMPLETED
        instance.completed_at = datetime.now(timezone.utc)
        await self._save_saga_instance(instance)

        # Remove from running instances
        self._running_instances.pop(instance.saga_id, None)

        logger.info(f"Saga {instance.saga_id} completed successfully")

    async def _fail_saga(self, instance: SagaInstance, error_message: str) -> None:
        """Mark saga as failed"""
        instance.state = SagaState.FAILED
        instance.error_message = error_message
        instance.completed_at = datetime.now(timezone.utc)
        await self._save_saga_instance(instance)

        # Remove from running instances
        self._running_instances.pop(instance.saga_id, None)

        logger.error(f"Saga {instance.saga_id} failed: {error_message}")

    async def _process_saga_event(self, event: BaseEvent) -> None:
        """Process event for running sagas"""
        # This would handle events that are part of running sagas
        # For now, we'll skip this as sagas are self-contained
        pass

    async def _check_timeouts(self) -> None:
        """Check for saga timeouts"""
        while self._running:
            try:
                # Check every 30 seconds
                await asyncio.sleep(30)

                cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=self.config.timeout_seconds)

                # Find timed out sagas
                if self._db is None:
                    continue
                sagas_collection = self._db.sagas

                timed_out = await sagas_collection.find({
                    "state": {"$in": [SagaState.RUNNING, SagaState.COMPENSATING]},
                    "created_at": {"$lt": cutoff_time}
                }).to_list(length=100)

                for saga_data in timed_out:
                    instance = SagaInstance(**saga_data)
                    logger.warning(f"Saga {instance.saga_id} timed out")

                    instance.state = SagaState.TIMEOUT
                    instance.error_message = f"Saga timed out after {self.config.timeout_seconds} seconds"
                    instance.completed_at = datetime.now(timezone.utc)

                    await self._save_saga_instance(instance)
                    self._running_instances.pop(instance.saga_id, None)

            except Exception as e:
                logger.error(f"Error checking timeouts: {e}")

    async def _save_saga_instance(self, instance: SagaInstance) -> None:
        """Save saga instance to database"""
        instance.updated_at = datetime.now(timezone.utc)

        if self._db is None:
            raise RuntimeError("Database not initialized")
        sagas_collection = self._db.sagas
        await sagas_collection.replace_one(
            {"saga_id": str(instance.saga_id)},
            instance.model_dump(),
            upsert=True
        )

    def _extract_execution_id(self, event: BaseEvent) -> str | None:
        """Extract execution ID from event"""
        if hasattr(event, 'execution_id'):
            return str(event.execution_id)
        return None

    async def get_saga_status(self, saga_id: str) -> SagaInstance | None:
        """Get saga instance status"""
        # Check memory first
        if saga_id in self._running_instances:
            return self._running_instances[saga_id]

        # Check database
        if self._db is None:
            return None
        sagas_collection = self._db.sagas
        saga_data = await sagas_collection.find_one({"saga_id": str(saga_id)})

        if saga_data:
            return SagaInstance(**saga_data)

        return None

    async def get_execution_sagas(self, execution_id: str) -> List[SagaInstance]:
        """Get all sagas for an execution"""
        if self._db is None:
            return []
        sagas_collection = self._db.sagas

        saga_docs = await sagas_collection.find({
            "execution_id": execution_id
        }).to_list(length=100)

        return [SagaInstance(**doc) for doc in saga_docs]


class BaseSaga(ABC):
    """Base class for saga implementations"""

    @classmethod
    @abstractmethod
    def get_name(cls) -> str:
        """Get saga name"""
        pass

    @classmethod
    @abstractmethod
    def get_trigger_events(cls) -> List[str]:
        """Get events that trigger this saga"""
        pass

    @abstractmethod
    def get_steps(self) -> List[SagaStep]:
        """Get saga steps in order"""
        pass
