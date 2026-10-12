# Result processor

The result processor writes the final state of every execution that reaches the k8s worker. The only other writer is the API, which marks an execution `error` when it can't publish `execution_requested`. It consumes `execution_completed`, `execution_failed` and `execution_timeout` with group id `result-processor`, one message per poll, and each handler runs behind a Redis idempotency key. It also consumes `pod_scheduled` and `pod_running`, and moves the stored status forward to `scheduled` or `running`; that update only applies from an earlier active status, so it never goes back and never overwrites a terminal one.

```mermaid
graph LR
    Kafka[(Kafka)] -->|completed / failed / timeout| Processor[Result processor]
    Processor -->|status, output, resource usage| Mongo[(executions)]
    Processor -->|result_stored or result_failed| Kafka
```

For each event it loads the execution, records metrics, and writes the status, exit code, stdout, stderr, resource usage and error type onto the execution's document in the `executions` collection. There's no separate results collection. The write is conditional: it only applies while the execution is still in an active status, so a late or duplicate event can't overwrite a result that's already stored. A timeout is stored with exit code -1.

After the write it publishes `result_stored`, which carries a storage reference rather than the output. The SSE service reads the output back from MongoDB when it forwards that event. If the MongoDB write or the Kafka publish fails, the processor tries to publish `result_failed` instead. That goes through the same producer, which stores the event in MongoDB first, so it fails too while MongoDB is down.

The result processor doesn't touch Kubernetes. The [pod monitor](pod_monitor.md) deletes finished pods, and their ConfigMaps go with them.

## Key files

| File | Purpose |
|------|---------|
| [`run_result_processor.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/workers/run_result_processor.py) | Entry point |
| [`processor.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/services/result_processor/processor.py) | Event handlers |
| [`execution_repository.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/db/repositories/execution_repository.py) | `write_terminal_result` |
