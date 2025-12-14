# SSE partitioned router

The SSE system uses a partitioned consumer pool architecture that eliminates issues with per-execution consumer groups and offset management. This provides scalable, efficient event routing for thousands of concurrent SSE connections.

## Why the redesign

The original implementation created a new Kafka consumer group for each execution (`sse-{execution_id}`). This caused several problems at scale.

With `auto_offset_reset='earliest'`, new consumer groups would read all historical messages before reaching current events — minutes of processing irrelevant data. With `auto_offset_reset='latest'`, consumers would miss events published between execution start and SSE connection establishment.

Each execution created a consumer group that persisted indefinitely, leading to metadata pollution — thousands of unused consumer groups over time. Race conditions occurred because executions would start and publish events before the frontend could establish SSE connections, causing missed `execution_completed` events.

## How it works now

The new architecture uses a single consumer group (`sse-router-pool`) with multiple consumers operating in parallel. Events are partitioned by `execution_id`, ensuring all events for a given execution are processed by the same consumer instance. This maintains event ordering while enabling parallel processing.

The `SSEKafkaRedisBridge` manages a configurable pool of consumers (default 10). It deserializes Kafka events and publishes them to Redis channels keyed by `execution_id`. In-process buffers have been removed in favor of Redis-only fan-out.

The producer side uses `execution_id` as the partition key, so all events for a given execution go to the same Kafka partition and are processed by the same consumer. Dependency injection uses Dishka framework — the router is application-scoped, receiving dependencies through constructor injection without global state.

## Scaling

The architecture scales horizontally by adjusting consumer pool size. With Kafka topics configured for 20-50 partitions, the system handles thousands of concurrent executions. Load distribution occurs automatically through Kafka's partition assignment. As load increases, increase the consumer pool size.

Memory management uses configurable buffer limits: max size, TTL for expiration, memory limit. Buffers clean up when SSE connections close or executions complete. Multiple backend instances can handle SSE connections behind a load balancer.

## Configuration

`SSE_CONSUMER_POOL_SIZE` controls consumer count (default 10). Kafka settings include 300-second max poll interval to accommodate processing delays. Buffer defaults: 100 events max, 10MB memory limit, 5-minute TTL.

## Shutdown coordination

The `SSEShutdownManager` complements the router. The router handles the data plane (Kafka consumers, event routing to Redis). The shutdown manager handles the control plane (tracking connections, coordinating graceful shutdown, notifying clients).

When the server shuts down, SSE clients receive a shutdown event so they can display messages and attempt reconnection. The shutdown manager implements phased shutdown: notify clients, wait for graceful disconnection, force-close remaining connections. SSE connections register with the shutdown manager and monitor a shutdown event while streaming from Redis. When shutdown triggers, connections send shutdown messages and close gracefully.
