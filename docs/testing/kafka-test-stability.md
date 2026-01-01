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
[`app/events/core/producer.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/events/core/producer.py):

```python
--8<-- "backend/app/events/core/producer.py:22:24"
```

The lock is process-global, so all `UnifiedProducer` instances serialize their initialization. This adds negligible
overhead in production (producers are created once at startup) while eliminating the race condition in tests.

## Related issues

These GitHub issues document the underlying problem:

| Issue | Description |
|-------|-------------|
| [confluent-kafka-python#1797](https://github.com/confluentinc/confluent-kafka-python/issues/1797) | Segfaults in multithreaded/asyncio pytest environments |
| [confluent-kafka-python#1761](https://github.com/confluentinc/confluent-kafka-python/issues/1761) | Segfault on garbage collection in multithreaded context |
| [librdkafka#3608](https://github.com/confluentinc/librdkafka/issues/3608) | Crash in `rd_kafka_broker_destroy_final` |

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
