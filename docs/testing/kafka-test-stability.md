# Kafka test stability

Most of what used to make Kafka tests flaky is gone. What's left is how long consumers take to shut down, and which settings actually control that.

## No producer to manage

`UnifiedProducer` is a store-then-publish outbox. It writes the event to MongoDB, then publishes through `KafkaEventTransport`, which calls `broker.publish()`. If the publish fails, it marks the stored event as failed to publish and re-raises. It has no Kafka client of its own and nothing to start or stop. The one `KafkaBroker` per process (aiokafka 0.14 under FastStream 0.7.7) is started by `dishka_lifespan` in the API and by FastStream's app runner in the workers.

Unit tests don't touch Kafka. The E2E suite runs inside the backend container, and its session-scoped `app` fixture enters the real lifespan. So each xdist worker starts one broker with the SSE and notification subscribers, and stops it when the session ends.

## Shutdown time

When a consumer stops, aiokafka sends a `LeaveGroupRequest` and waits for it up to `request_timeout_ms`. With the default 40 seconds, a slow coordinator stalls teardown for that long ([aiokafka#773](https://github.com/aio-libs/aiokafka/issues/773)). FastStream adds its own `graceful_timeout` for in-flight messages on stop.

`BrokerProvider` passes only two Kafka settings to the broker, and FastStream hands `request_timeout_ms` to both the producer and the consumers:

| Setting                    | `config.toml` | `config.test.toml` | Broker argument      |
|----------------------------|---------------|--------------------|----------------------|
| `KAFKA_REQUEST_TIMEOUT_MS` | 40000         | 5000               | `request_timeout_ms` |
| `KAFKA_GRACEFUL_TIMEOUT`   | 15.0 (default) | 5.0               | `graceful_timeout`   |

`config.test.toml` also lowers `KAFKA_SESSION_TIMEOUT_MS` to 6000 and `KAFKA_HEARTBEAT_INTERVAL_MS` to 2000, but nothing reads either setting, so they have no effect ([#293](https://github.com/HardMax71/Integr8sCode/issues/293)). Per-subscriber options such as `ack_policy`, `auto_offset_reset` and `max_poll_records` are set in `app/events/handlers.py`, not in config.

`SSE_CONSUMER_POOL_SIZE` is 1 in tests (10 in `config.toml`). It sets `max_workers` on the SSE subscriber.

## Shared consumer groups

Group ids are literals in `handlers.py`, so every xdist worker joins the same groups. Tests that depend on a group's messages, such as the DLQ tests, carry an `xdist_group` marker. With `--dist=loadgroup` from `pyproject.toml`, all tests in one group run on one worker, one after another.
