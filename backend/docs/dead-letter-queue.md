# Dead Letter Queue in Integr8sCode

## What Problem Does This Solve?

Picture this: your Kafka consumer is happily processing events when suddenly it hits a poison pill - maybe a malformed event, a database outage, or just a bug in your code. Without a Dead Letter Queue (DLQ), that event would either block your entire consumer (if you keep retrying forever) or get lost forever (if you skip it). Neither option is great for an event-sourced system where events are your source of truth.

The DLQ acts as a safety net. When an event fails processing after a reasonable number of retries, instead of losing it, we send it to a special "dead letter" topic where it can be examined, fixed, and potentially replayed later.

## How It Works in Our System

The DLQ implementation in Integr8sCode follows a producer-agnostic pattern. This means consumers don't directly know about or depend on the DLQ infrastructure - they just report errors through callbacks. Here's how the pieces fit together:

### The Producer Side

Every `UnifiedProducer` instance has a `send_to_dlq()` method that knows how to package up a failed event with all its context - the original topic, error message, retry count, and metadata about when and where it failed. When called, it creates a special DLQ message and sends it to the `dead_letter_queue` topic in Kafka.

The beauty here is that the producer doesn't make decisions about *when* to send something to DLQ - it just provides the mechanism. The decision-making happens at a higher level.

### The Consumer Side  

Consumers use an error callback pattern. When you create a consumer, you can register an error handler that gets called whenever event processing fails. We provide pre-built DLQ handlers through the `create_dlq_error_handler()` function that implement common retry strategies.

For example, the event store consumer sets up its error handling like this:

```python
if self.producer:
    dlq_handler = create_dlq_error_handler(
        producer=self.producer,
        original_topic="event-store", 
        max_retries=3
    )
    self.consumer.register_error_callback(dlq_handler)
```

This handler tracks retry counts per event. If an event fails 3 times, it gets sent to DLQ. The consumer itself doesn't know about any of this - it just calls the error callback and moves on.

### The DLQ Processor

The `dlq_processor` is a separate service that monitors the dead letter queue topic. It's responsible for the retry orchestration. When it sees a message in the DLQ, it applies topic-specific retry policies to determine when (or if) to retry sending that message back to its original topic.

Different topics have different retry strategies configured:

- **Execution requests** get aggressive retries with exponential backoff - these are critical user operations
- **Pod events** get fewer retries with longer delays - these are less critical monitoring events  
- **Resource allocation** events get immediate retries - these need quick resolution
- **WebSocket events** use fixed intervals - these are real-time updates that become stale quickly

The processor also implements safety features like:
- Maximum age checks (messages older than 7 days are discarded)
- Permanent failure handling (after max retries, messages are archived)
- Test event filtering in production

## The Flow of a Failed Message

Let's trace what happens when an event fails processing:

1. **Initial Failure**: A consumer tries to process an event and throws an exception
2. **Error Callback**: The consumer's error callback is invoked with the exception and event
3. **Retry Tracking**: The DLQ handler checks how many times this specific event has failed
4. **Decision Point**: If under the retry limit, the handler logs and returns (Kafka will redeliver)
5. **Send to DLQ**: If over the limit, the handler calls `producer.send_to_dlq()`
6. **DLQ Message Creation**: The producer packages the event with failure context
7. **Publish to DLQ Topic**: The message is sent to the `dead_letter_queue` topic
8. **DLQ Processor Pickup**: The DLQ processor service consumes the message
9. **Policy Application**: The processor checks retry policies for the original topic
10. **Scheduled Retry**: After appropriate delay, the message is sent back to original topic
11. **Success or Archive**: If retry succeeds, great! If not, repeat until max attempts

## Configuration and Tuning

The DLQ system is configured through environment variables in the `dlq-processor` service:

- `DLQ_MAX_RETRY_ATTEMPTS`: Global maximum retries (default: 5)
- `DLQ_RETRY_DELAY_HOURS`: Base delay between retries (default: 1 hour)
- `DLQ_MAX_AGE_DAYS`: How long to keep trying (default: 7 days)
- `DLQ_BATCH_SIZE`: How many DLQ messages to process at once (default: 100)

Each topic can override these with custom retry policies in the DLQ processor configuration. The key is finding the balance between giving transient failures time to resolve and not keeping dead messages around forever.

## Monitoring and Operations

The DLQ publishes metrics that help you understand its health:

- **Message counts by status** (pending, retried, discarded)
- **Age statistics** showing how long messages have been stuck
- **Topic breakdown** showing which services are having issues
- **Retry rates** to identify systemic problems

In production, you'd want to set up alerts for:
- High DLQ message rates (something is systematically failing)
- Old messages accumulating (retry isn't working)
- Specific topics dominating the DLQ (service-specific issue)

## When Things Go Wrong

If the DLQ processor itself fails, messages stay safely in the `dead_letter_queue` topic - Kafka acts as the durable buffer. When the processor restarts, it picks up where it left off.

If sending to DLQ fails (extremely rare - would mean Kafka is down), the producer logs a critical error but doesn't crash the consumer. This follows the principle that it's better to lose one message than to stop processing everything.

The system is designed to be resilient but not perfect. In catastrophic scenarios, you still have Kafka's built-in durability and the ability to replay topics from the beginning if needed.

## Best Practices

From our experience running this system:

1. **Keep retry logic simple** - Complex retry strategies are hard to debug when things go wrong
2. **Monitor actively** - A growing DLQ is always a symptom of something else
3. **Set reasonable limits** - Retrying forever just wastes resources
4. **Use topic-specific policies** - One size doesn't fit all for retry strategies
5. **Clean up old messages** - Archive or delete ancient DLQ entries to prevent unbounded growth
6. **Test failure scenarios** - Inject failures in development to verify DLQ behavior

The DLQ is like insurance - you hope you never need it, but when you do, you're really glad it's there. It turns "we lost some events during the outage" into "we successfully recovered all events after the outage resolved."