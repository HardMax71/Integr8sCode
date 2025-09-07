# SSE Partitioned Event Router Architecture

## Overview

The SSE (Server-Sent Events) system has been redesigned to use a partitioned consumer pool architecture that eliminates the previous issues with per-execution consumer groups and offset management complexity. This new architecture provides scalable, efficient event routing for thousands of concurrent SSE connections.

## Previous Architecture Problems

The original implementation created a new Kafka consumer group for each execution, which led to several critical issues. Each SSE connection would spawn its own consumer with a unique group ID following the pattern `sse-{execution_id}`. This approach seemed logical initially but created significant operational problems at scale.

The most severe issue was offset management complexity. When using `auto_offset_reset='earliest'`, new consumer groups would attempt to read all historical messages from the beginning of each topic. With topics containing thousands of messages from previous executions, consumers would spend minutes processing irrelevant historical data before reaching current events. Alternatively, using `auto_offset_reset='latest'` would cause consumers to miss events published between execution start and SSE connection establishment.

Resource waste was another major concern. Each execution would create a consumer group that persisted indefinitely in Kafka, leading to metadata pollution. The system would accumulate thousands of unused consumer groups over time, increasing Kafka's operational overhead.

Race conditions frequently occurred because executions would start and publish events before the frontend could establish SSE connections. This timing gap of one to two seconds would result in missed events, particularly the critical execution_completed events that signal task completion.

## New Partitioned Architecture

The new architecture employs a single consumer group with multiple consumers operating in parallel. This design uses Kafka's built-in partition assignment to distribute load efficiently across the consumer pool.

The system now consists of a partitioned event router that manages a pool of consumers, all belonging to the same consumer group called "sse-router-pool". Events are partitioned by execution_id, ensuring all events for a given execution are processed by the same consumer instance. This partitioning strategy maintains event ordering while enabling parallel processing.

Each SSE connection subscribes to events through the router, which maintains an in-memory buffer for each active execution. Events flow from Kafka through the consumer pool to the router, which then distributes them to the appropriate execution buffers. SSE connections read from these buffers to stream events to clients.

## Implementation Details

The PartitionedSSERouter class serves as the central component of the new architecture. It manages a configurable pool of consumers (defaulting to 10 instances) that operate within a single consumer group. The router maintains a dictionary of event buffers, one per active execution, and handles subscription management for SSE connections.

Event routing occurs through the EventDispatcher pattern. Each consumer in the pool has an EventDispatcher configured with handlers that route events to appropriate execution buffers based on the execution_id field. The routing logic checks each incoming event for an execution_id, determines if there's an active subscription for that execution, and places the event in the corresponding buffer if one exists.

The producer side has been updated to use execution_id as the partition key when publishing events. This ensures that all events for a given execution are sent to the same Kafka partition, which in turn guarantees they're processed by the same consumer in the pool. This partitioning strategy is crucial for maintaining event ordering and enabling efficient parallel processing.

Dependency injection has been properly integrated using the Dishka framework. The router is instantiated as an application-scoped dependency through the ConnectionProvider, ensuring a single router instance serves all SSE connections. The router receives its dependencies (SchemaRegistryManager, Settings, metrics instances) through constructor injection, avoiding any global state or singleton patterns.

## Metrics and Monitoring

The new architecture includes comprehensive metrics collection through the EventMetrics and ConnectionMetrics classes. These metrics track various aspects of system performance and health.

Event processing metrics monitor the number of events routed, events dropped due to buffer overflow, and event processing latency. Connection metrics track active SSE connections per execution, total active executions, and connection duration statistics. Kafka consumer metrics observe consumer lag, message consumption rate, and any consumption errors.

Buffer metrics are particularly important for monitoring system health. They track buffer size, memory usage, backpressure status, and dropped events. These metrics help identify when the system is under stress and may need scaling adjustments.

## Scalability Considerations

The partitioned architecture scales horizontally by adjusting the number of consumers in the pool. With Kafka topics configured for multiple partitions (recommended 20-50), the system can handle thousands of concurrent executions efficiently.

Load distribution occurs automatically through Kafka's partition assignment mechanism. Each consumer in the pool is assigned a subset of partitions, and the execution_id-based partitioning ensures even distribution of executions across consumers. As load increases, operators can increase the consumer pool size to handle additional throughput.

Memory management is handled through configurable buffer limits. Each execution buffer has a maximum size, TTL for event expiration, and memory limit to prevent unbounded growth. Buffers are automatically cleaned up when SSE connections close or executions complete.

The architecture supports multiple backend instances for handling SSE connections. While the consumer pool runs within each backend instance, a load balancer can distribute SSE connection requests across multiple backends to handle thousands of concurrent connections.

## Configuration

The system is configured through environment variables and the Settings class. The SSE_CONSUMER_POOL_SIZE setting controls the number of consumers in the pool, with a default of 10. This value should be adjusted based on expected load and available resources.

Kafka configuration includes standard consumer settings such as session timeout, heartbeat interval, and max poll interval. These values are tuned for reliable operation with the default being 300 seconds for max poll interval to accommodate potential processing delays.

Buffer configuration parameters control the behavior of execution buffers. Each buffer can hold up to 100 events by default, with a 10MB memory limit and 5-minute TTL for events. These values balance memory usage with the need to buffer events during temporary network disruptions.

## Benefits of the New Architecture

The new architecture provides several significant advantages over the previous implementation. Resource efficiency is dramatically improved with only one consumer group instead of thousands, reducing Kafka metadata overhead and simplifying operations.

Performance is enhanced through parallel processing across the consumer pool, efficient event routing without client-side filtering, and instant event delivery without processing historical messages. The system now handles thousands of concurrent executions without degradation.

Operational simplicity is a key benefit. The single consumer group is easy to monitor and manage, offset management is straightforward with `auto_offset_reset='latest'`, and there's no accumulation of unused consumer groups over time.

Reliability improvements include guaranteed event ordering per execution through partitioning, no race conditions from timing issues, and automatic recovery from consumer failures through Kafka's rebalancing mechanism.

## Migration Considerations

When deploying this new architecture, existing SSE connections will continue to work during the transition. The old per-execution consumer groups can be deleted from Kafka after migration to free up resources. No changes are required on the frontend side, as the SSE API remains unchanged.

Monitoring should be established for the new metrics to ensure the system operates within expected parameters. Operators should watch consumer lag, buffer sizes, and dropped event rates to identify any issues early.

The consumer pool size may need adjustment based on actual load patterns. Start with the default of 10 consumers and increase if consumer lag grows consistently or event processing latency increases beyond acceptable thresholds.

## Shutdown Manager Integration

The SSEShutdownManager remains an essential component even with the partitioned router architecture. While the router handles Kafka consumer lifecycle and event buffering, the shutdown manager serves a complementary role focused on SSE client connections.

### Separation of Concerns

The PartitionedSSERouter manages the data plane - Kafka consumers, event routing, and buffer management. It ensures events flow from Kafka to the appropriate execution buffers efficiently.

The SSEShutdownManager manages the control plane for client connections - tracking active SSE connections, coordinating graceful shutdown, and ensuring clients are properly notified before disconnection.

### Why Both Are Needed

Client notification is critical for user experience. When the server shuts down, SSE clients need to receive a shutdown event so they can display appropriate messages and attempt reconnection. The router doesn't have visibility into individual SSE connections, only execution subscriptions.

The shutdown manager implements a phased shutdown process that first notifies clients, then waits for graceful disconnection, and finally forces closure of remaining connections. This prevents abrupt disconnections that would confuse users.

Connection-level tracking by the shutdown manager provides operational visibility through metrics about how many connections are draining during shutdown, helping operators understand shutdown progress.

### Integration Points

The shutdown manager and router work together through minimal coupling. The shutdown manager holds a reference to the router to coordinate shutdown, but they operate independently during normal operation.

SSE connections register with the shutdown manager and receive a shutdown event object. They monitor this event while streaming data from the router's buffers. When shutdown is initiated, the event is triggered, causing connections to send shutdown messages to clients and close gracefully.

This architecture maintains clean separation of concerns while ensuring both efficient event routing and graceful client handling during shutdown.