# Kafka test stability

Most of what used to make Kafka tests flaky is gone. What's left is how long consumers take to shut down, and which settings actually control that.

## No producer to manage

`UnifiedProducer` is a store-then-publish outbox. It writes the event to MongoDB, then publishes through `KafkaEventTransport`, which calls `broker.publish()`. If the publish fails, it marks the stored event as failed to publish and re-raises. It has no Kafka client of its own and nothing to start or stop. The one `KafkaBroker` per process (aiokafka 0.14 under FastStream 0.7.7) is started by `dishka_lifespan` in the API and by FastStream's app runner in the worker.

Unit tests don't touch Kafka. The E2E suite runs inside the backend container, and its session-scoped `app` fixture enters the real lifespan. So each xdist worker starts one broker with the SSE and notification subscribers, and stops it when the session ends.

## Shutdown time

When a consumer stops, aiokafka sends a `LeaveGroupRequest` and waits for it up to `request_timeout_ms`. With the default 40 seconds, a slow coordinator stalls teardown for that long ([aiokafka#773](https://github.com/aio-libs/aiokafka/issues/773)). FastStream adds its own `graceful_timeout` for in-flight messages on stop.

`BrokerProvider` passes only two Kafka settings to the broker, and FastStream hands `request_timeout_ms` to both the producer and the consumers:

| Setting                    | config.toml | config.test.toml | Broker argument      |
|----------------------------|---------------|--------------------|----------------------|
| `KAFKA_REQUEST_TIMEOUT_MS` | 40000         | 5000               | `request_timeout_ms` |
| `KAFKA_GRACEFUL_TIMEOUT`   | 15.0 (default) | 5.0               | `graceful_timeout`   |

Session timeout and heartbeat stay at aiokafka's defaults, 10 and 3 seconds, in tests and in production. Per-subscriber options such as `ack_policy`, `auto_offset_reset` and `max_poll_records` are set in `app/events/handlers.py`, not in config.

`SSE_CONSUMER_POOL_SIZE` is 1 in tests (10 in config.toml). It sets `max_workers` on the SSE subscriber.

## Shared consumer groups

Group ids are literals in handlers.py, so every xdist process's API joins the same `sse-bridge-pool` and `notification-service` groups, and Kafka hands each message to one of them. No test waits for a message to reach its own process. Tests wait on what the producer stored instead: `wait_for_event` in tests/e2e/conftest.py polls the events collection, which the producer writes before it publishes, and notification tests poll the delivered notification. The DLQ manager test checks the row it stores and the event it hands to a mocked broker, so it needs no consumer of its own.
