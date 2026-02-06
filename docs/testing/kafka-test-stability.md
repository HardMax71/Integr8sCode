# Kafka test stability

## Producer lifecycle

The project uses aiokafka (`aiokafka==0.12.0`) via FastStream as the Kafka backend. `UnifiedProducer` is a thin wrapper that delegates to `await self._broker.publish()` — it has no internal Kafka client and no `start()`/`stop()` methods of its own. The broker lifecycle is managed externally (by FastStream in the API process, or by each worker's startup code), so the confluent-kafka `librdkafka` race conditions that plague many Python Kafka test suites do not apply here.

In test fixtures, construct the producer and yield it directly:

```python
@pytest.fixture(scope="function")
async def producer():
    p = UnifiedProducer(broker, event_repository, logger, settings, event_metrics)
    yield p
```

No explicit cleanup is needed — the broker is started and stopped separately.

## Consumer teardown delays

### The problem

Test teardown taking 40+ seconds with errors like:

```text
ERROR aiokafka.consumer.group_coordinator: Error sending LeaveGroupRequest to node 1 [[Error 7] RequestTimedOutError]
```

This happens when `consumer.stop()` sends a `LeaveGroupRequest` to the Kafka coordinator, but the request times out.

### Root cause

The `request_timeout_ms` parameter in aiokafka defaults to **40000ms** (40 seconds). When the Kafka coordinator is slow
or
unresponsive during test teardown, the consumer waits the full timeout before giving up.

See [aiokafka#773](https://github.com/aio-libs/aiokafka/issues/773) for details on consumer stop delays.

### The fix

Configure shorter timeouts in `.env.test`:

```bash
# Reduce consumer pool and timeouts for faster test startup/teardown
# https://github.com/aio-libs/aiokafka/issues/773
SSE_CONSUMER_POOL_SIZE=1
KAFKA_SESSION_TIMEOUT_MS=6000
KAFKA_HEARTBEAT_INTERVAL_MS=2000
KAFKA_REQUEST_TIMEOUT_MS=5000
```

All consumers must pass these settings to `AIOKafkaConsumer`:

```python
consumer = AIOKafkaConsumer(
    *topics,
    bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
    session_timeout_ms=settings.KAFKA_SESSION_TIMEOUT_MS,
    heartbeat_interval_ms=settings.KAFKA_HEARTBEAT_INTERVAL_MS,
    request_timeout_ms=settings.KAFKA_REQUEST_TIMEOUT_MS,
)
```

### Results

| Metric          | Before | After  |
|-----------------|--------|--------|
| Teardown time   | 40s    | <1s    |
| Total test time | 70s    | 20-35s |

### Key timeouts explained

| Setting                       | Default | Test Value | Purpose                                            |
|-------------------------------|---------|------------|----------------------------------------------------|
| `KAFKA_SESSION_TIMEOUT_MS`    | 45000   | 6000       | Time before broker considers consumer dead         |
| `KAFKA_HEARTBEAT_INTERVAL_MS` | 10000   | 2000       | Frequency of heartbeats to coordinator             |
| `KAFKA_REQUEST_TIMEOUT_MS`    | 40000   | 5000       | Timeout for broker requests (including LeaveGroup) |
| `SSE_CONSUMER_POOL_SIZE`      | 10      | 1          | Number of SSE consumers (fewer = faster startup)   |

!!! note "Timeout constraints"
    `request_timeout_ms` must be less than `session_timeout_ms`. The test values (5000 < 6000) and
    production defaults (40000 < 45000) satisfy this constraint.
