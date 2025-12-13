# Result Processor Worker

## Purpose
Consumes execution completion events from Kafka and persists results to MongoDB.

## Event Flow
```
pod-monitor → ExecutionCompletedEvent → Kafka → result-processor → MongoDB
```

## Responsibilities
- Store execution output (stdout, stderr, exit codes) in execution_results collection
- Update execution status in executions collection
- Record execution metrics (duration, memory usage)
- Publish ResultStoredEvent for downstream consumers

## Configuration
- Consumer group: `result-processor-group`
- Topic: `EXECUTION_RESULTS`
- Processes events: ExecutionCompletedEvent, ExecutionFailedEvent, ExecutionTimeoutEvent

## Deployment
Runs as standalone container via docker-compose:
```yaml
result-processor:
  build:
    dockerfile: workers/Dockerfile.result_processor
```

## Dependencies
- Kafka for event consumption
- MongoDB for result storage
- Schema registry for event deserialization