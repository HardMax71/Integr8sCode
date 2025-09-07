from __future__ import annotations

import asyncio
from typing import Dict, Set

from app.core.logging import logger
from app.core.metrics.connections import ConnectionMetrics
from app.core.metrics.events import EventMetrics
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.dispatcher import EventDispatcher
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.base import BaseEvent
from app.services.sse.event_buffer import BufferPriority, EventBuffer
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings


class PartitionedSSERouter:
    """
    Routes events from multiple Kafka consumers to SSE connections.
    
    Uses a consumer pool for parallel processing and partitions events
    by execution_id for optimal load distribution.
    """
    
    def __init__(
        self,
        schema_registry: SchemaRegistryManager,
        settings: Settings,
        event_metrics: EventMetrics,
        connection_metrics: ConnectionMetrics,
        sse_bus: SSERedisBus
    ) -> None:
        """Initialize the partitioned SSE router.
        
        Args:
            schema_registry: Schema registry for event deserialization
            settings: Application settings
            event_metrics: Event metrics instance
            connection_metrics: Connection metrics instance
        """
        self.schema_registry = schema_registry
        self.settings = settings
        self.event_metrics = event_metrics
        self.connection_metrics = connection_metrics
        self.sse_bus = sse_bus
        
        # Consumer pool configuration
        self.num_consumers = settings.SSE_CONSUMER_POOL_SIZE
        self.consumers: list[UnifiedConsumer] = []
        
        # Execution tracking
        self.execution_buffers: Dict[str, EventBuffer[BaseEvent]] = {}
        self.active_executions: Set[str] = set()
        self._lock = asyncio.Lock()
        
        # Router state
        self._running = False
        self._initialized = False
        
    async def start(self) -> None:
        """Start the consumer pool."""
        async with self._lock:
            if self._initialized:
                return
                
            logger.info(f"Starting partitioned SSE router with {self.num_consumers} consumers")
            
            # Create and start consumers
            for i in range(self.num_consumers):
                consumer = await self._create_consumer(i)
                self.consumers.append(consumer)
                
            self._running = True
            self._initialized = True
            
            logger.info("Partitioned SSE router started successfully")
            
    async def stop(self) -> None:
        """Stop the consumer pool and clean up resources."""
        async with self._lock:
            if not self._initialized:
                return
                
            logger.info("Stopping partitioned SSE router")
            
            self._running = False
            
            # Stop all consumers
            for consumer in self.consumers:
                await consumer.stop()
                
            # Clean up buffers
            for buffer in self.execution_buffers.values():
                await buffer.shutdown()
                
            self.consumers.clear()
            self.execution_buffers.clear()
            self.active_executions.clear()
            self._initialized = False
            
            logger.info("Partitioned SSE router stopped")
            
    async def subscribe(self, execution_id: str) -> EventBuffer[BaseEvent]:
        """Subscribe to events for a specific execution.
        
        Args:
            execution_id: ID of the execution to subscribe to
            
        Returns:
            Event buffer that will receive filtered events
        """
        async with self._lock:
            if execution_id not in self.execution_buffers:
                buffer = EventBuffer[BaseEvent](
                    maxsize=100,
                    buffer_name=f"sse_{execution_id}",
                    max_memory_mb=10.0,
                    enable_priority=True,
                    ttl_seconds=300.0
                )
                self.execution_buffers[execution_id] = buffer
                self.active_executions.add(execution_id)
                
                logger.info(f"Created SSE buffer for execution {execution_id}")
                self.connection_metrics.increment_sse_connections("executions")
                
            return self.execution_buffers[execution_id]
            
    async def unsubscribe(self, execution_id: str) -> None:
        """Unsubscribe from events for an execution.
        
        Args:
            execution_id: ID of the execution to unsubscribe from
        """
        async with self._lock:
            if execution_id in self.execution_buffers:
                buffer = self.execution_buffers[execution_id]
                stats = await buffer.get_stats()
                
                logger.info(
                    f"Removing SSE buffer for execution {execution_id}, "
                    f"stats: {stats}"
                )
                
                await buffer.shutdown()
                del self.execution_buffers[execution_id]
                self.active_executions.discard(execution_id)
                
                self.connection_metrics.decrement_sse_connections("executions")
                
    async def _create_consumer(self, consumer_index: int) -> UnifiedConsumer:
        """Create a consumer instance for the pool.
        
        Args:
            consumer_index: Index of this consumer in the pool
            
        Returns:
            Configured consumer instance
        """
        config = ConsumerConfig(
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="sse-router-pool",  # All consumers in same group
            client_id=f"sse-router-{consumer_index}",
            enable_auto_commit=True,
            auto_offset_reset='latest',  # Only process new events
            max_poll_interval_ms=300000,
            session_timeout_ms=30000,
            heartbeat_interval_ms=3000,
        )
        
        # Create dispatcher with routing logic
        dispatcher = EventDispatcher()
        self._register_routing_handlers(dispatcher)
        
        consumer = UnifiedConsumer(
            config=config,
            event_dispatcher=dispatcher
        )
        
        # Subscribe to relevant topics
        topics = [
            KafkaTopic.EXECUTION_EVENTS,
            KafkaTopic.EXECUTION_COMPLETED,
            KafkaTopic.EXECUTION_FAILED,
            KafkaTopic.EXECUTION_TIMEOUT,
            KafkaTopic.EXECUTION_RESULTS,
            KafkaTopic.POD_EVENTS,
            KafkaTopic.POD_STATUS_UPDATES
        ]
        
        await consumer.start(topics)
        
        logger.info(f"Consumer {consumer_index} started in pool")
        return consumer
        
    def _register_routing_handlers(self, dispatcher: EventDispatcher) -> None:
        """Register event routing handlers on the dispatcher.
        
        Args:
            dispatcher: Event dispatcher to configure
        """
        # Event types we route to SSE connections
        relevant_events = [
            EventType.EXECUTION_REQUESTED,
            EventType.EXECUTION_QUEUED,
            EventType.EXECUTION_STARTED,
            EventType.EXECUTION_RUNNING,
            EventType.EXECUTION_COMPLETED,
            EventType.EXECUTION_FAILED,
            EventType.EXECUTION_TIMEOUT,
            EventType.EXECUTION_CANCELLED,
            EventType.RESULT_STORED,
            EventType.POD_CREATED,
            EventType.POD_SCHEDULED,
            EventType.POD_RUNNING,
            EventType.POD_SUCCEEDED,
            EventType.POD_FAILED,
            EventType.POD_TERMINATED,
            EventType.POD_DELETED,
        ]
        
        async def route_event(event: BaseEvent) -> None:
            """Route event to appropriate execution buffer."""
            # Extract execution_id from event data
            event_data = event.model_dump()
            execution_id = event_data.get("execution_id")
            
            if not execution_id:
                logger.debug(f"Event {event.event_type} has no execution_id")
                return
            
            # Always publish to shared SSE bus so any worker can deliver to clients
            try:
                await self.sse_bus.publish_event(execution_id, event)
                logger.info(f"Published {event.event_type} to SSE Redis bus for {execution_id}")
            except Exception as e:
                logger.error(f"Failed to publish {event.event_type} to SSE bus for {execution_id}: {e}", exc_info=True)

            # Log current buffers
            logger.debug(f"Current buffers: {list(self.execution_buffers.keys())}")
            
            # Skip if no active subscription
            if execution_id not in self.execution_buffers:
                logger.warning(f"No buffer for execution {execution_id}, skipping {event.event_type}. "
                               f"Active buffers: {list(self.execution_buffers.keys())}")
                return
                
            buffer = self.execution_buffers[execution_id]
            
            # Determine priority
            priority = self._get_event_priority(event.event_type)
            
            # Add to buffer
            success = await buffer.put(
                event,
                priority=priority,
                timeout=1.0,
                source=str(event.event_type)
            )
            
            if success:
                self.event_metrics.record_event_buffer_processed()
                logger.debug(
                    f"Routed {event.event_type} to buffer for execution {execution_id}"
                )
            else:
                self.event_metrics.record_event_buffer_dropped()
                logger.warning(
                    f"Failed to buffer {event.event_type} for execution {execution_id}"
                )
                
        # Register handler for all relevant event types
        for event_type in relevant_events:
            dispatcher.register_handler(event_type, route_event)
            
    def _get_event_priority(self, event_type: EventType) -> BufferPriority:
        """Determine priority for an event type.
        
        Args:
            event_type: Type of the event
            
        Returns:
            Buffer priority for the event
        """
        if event_type in {EventType.RESULT_STORED, EventType.EXECUTION_FAILED, EventType.EXECUTION_TIMEOUT}:
            return BufferPriority.CRITICAL
        elif event_type in {EventType.EXECUTION_COMPLETED, EventType.EXECUTION_STARTED}:
            return BufferPriority.HIGH
        elif str(event_type).startswith("pod_"):
            return BufferPriority.LOW
        else:
            return BufferPriority.NORMAL
            
    def get_stats(self) -> dict[str, int | bool]:
        """Get router statistics.
        
        Returns:
            Dictionary of router statistics
        """
        return {
            "num_consumers": len(self.consumers),
            "active_executions": len(self.active_executions),
            "total_buffers": len(self.execution_buffers),
            "is_running": self._running,
        }


def create_partitioned_sse_router(
    schema_registry: SchemaRegistryManager,
    settings: Settings,
    event_metrics: EventMetrics,
    connection_metrics: ConnectionMetrics,
    sse_bus: SSERedisBus
) -> PartitionedSSERouter:
    """Factory function to create a partitioned SSE router.
    
    Args:
        schema_registry: Schema registry for event deserialization
        settings: Application settings
        event_metrics: Event metrics instance
        connection_metrics: Connection metrics instance
        
    Returns:
        A new partitioned SSE router instance
    """
    return PartitionedSSERouter(
        schema_registry=schema_registry,
        settings=settings,
        event_metrics=event_metrics,
        connection_metrics=connection_metrics,
        sse_bus=sse_bus
    )
