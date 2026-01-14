# Kafka test stability

## The problem

When running tests in parallel with `pytest-xdist`, you might encounter sporadic crashes:

```text
Fatal Python error: Aborted
```

The stack trace typically points to `confluent_kafka` operations during producer initialization. This isn't a bug in
the application code—it's a known race condition in the underlying `librdkafka` C library.

## Why it happens

The `confluent-kafka-python` library wraps `librdkafka`, a high-performance C library. When multiple processes or
threads create Kafka `Producer` instances simultaneously, they can trigger a race condition in `librdkafka`'s internal
initialization. This manifests as random `SIGABRT` signals, crashes in `rd_kafka_broker_destroy_final`, or flaky CI
failures that pass on retry.

## The fix

Serialize `Producer` initialization using a global threading lock. In
[
`app/events/core/producer.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/events/core/producer.py):

```python
--8<-- "backend/app/events/core/producer.py:22:24"
```

The lock is process-global, so all `UnifiedProducer` instances serialize their initialization. This adds negligible
overhead in production (producers are created once at startup) while eliminating the race condition in tests.

## Related issues

These GitHub issues document the underlying problem:

| Issue                                                                                             | Description                                             |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------------|
| [confluent-kafka-python#1797](https://github.com/confluentinc/confluent-kafka-python/issues/1797) | Segfaults in multithreaded/asyncio pytest environments  |
| [confluent-kafka-python#1761](https://github.com/confluentinc/confluent-kafka-python/issues/1761) | Segfault on garbage collection in multithreaded context |
| [librdkafka#3608](https://github.com/confluentinc/librdkafka/issues/3608)                         | Crash in `rd_kafka_broker_destroy_final`                |

## Alternative approaches

If you still encounter issues:

1. **Reduce parallelism** - Run Kafka-dependent tests with fewer workers: `pytest -n 2` instead of `-n auto`

2. **Isolate Kafka tests** - Mark Kafka tests and run them separately:
   ```python
   @pytest.mark.kafka
   def test_producer_sends_message():
       ...
   ```
   ```bash
   pytest -m "not kafka" -n auto  # parallel
   pytest -m kafka -n 1           # sequential
   ```

3. **Use fixtures carefully** - Ensure producer fixtures are properly scoped and cleaned up:
   ```python
   @pytest.fixture(scope="function")
   async def producer():
       p = UnifiedProducer(config, schema_registry)
       await p.start()
       yield p
       await p.stop()  # Always clean up
   ```

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
