# Kafka test stability

## The problem

When running tests in parallel (e.g., with `pytest-xdist`), you might encounter sporadic crashes with messages like:

```
Fatal Python error: Aborted
```

The stack trace typically points to `confluent_kafka` operations, often during producer initialization in fixtures or test setup. This isn't a bug in the application code - it's a known race condition in the underlying `librdkafka` C library.

## Why it happens

The `confluent-kafka-python` library is a thin wrapper around `librdkafka`, a high-performance C library. When multiple Python processes or threads try to create Kafka `Producer` instances simultaneously, they can trigger a race condition in `librdkafka`'s internal initialization routines.

This manifests as:

- Random `SIGABRT` signals during test runs
- Crashes in `rd_kafka_broker_destroy_final` or similar internal functions
- Flaky CI failures that pass on retry

The issue is particularly common in CI environments where tests run in parallel across multiple workers.

## The fix

The solution is to serialize `Producer` initialization using a global threading lock. This prevents multiple threads from entering `librdkafka`'s initialization code simultaneously.

In `app/events/core/producer.py`:

```python
import threading

# Global lock to serialize Producer initialization (workaround for librdkafka race condition)
# See: https://github.com/confluentinc/confluent-kafka-python/issues/1797
_producer_init_lock = threading.Lock()

class UnifiedProducer:
    async def start(self) -> None:
        # ... config setup ...

        # Serialize Producer initialization to prevent librdkafka race condition
        with _producer_init_lock:
            self._producer = Producer(producer_config)

        # ... rest of startup ...
```

The lock is process-global, so all `UnifiedProducer` instances in the same process will serialize their initialization. This adds negligible overhead in production (producers are typically created once at startup) while eliminating the race condition in tests.

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
