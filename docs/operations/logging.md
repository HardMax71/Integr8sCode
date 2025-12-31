# Logging

This backend uses structured JSON logging with automatic correlation IDs, trace context injection, and sensitive data sanitization. The goal is logs that are both secure against injection attacks and easy to query in aggregation systems like Elasticsearch or Loki.

## How it's wired

The logger is created once during application startup via dependency injection. The `setup_logger` function in `app/core/logging.py` configures a JSON formatter and attaches filters for correlation IDs and OpenTelemetry trace context. Every log line comes out as a JSON object with timestamp, level, logger name, message, and whatever structured fields you added. Workers and background services use the same setup, so log format is consistent across the entire system.

The JSON formatter does two things beyond basic formatting. First, it injects context that would be tedious to pass manually - the correlation ID from the current request, the trace and span IDs from OpenTelemetry, and request metadata like method and path. Second, it sanitizes sensitive data by pattern-matching things like API keys, JWT tokens, and database URLs, replacing them with redaction placeholders. This sanitization applies to both the log message and exception tracebacks.

## Structured logging

All log calls use the `extra` parameter to pass structured data rather than interpolating values into the message string. The message itself is a static string that describes what happened; the details go in `extra` where they become separate JSON fields.

```python
# This is how logging looks throughout the codebase
self.logger.info(
    "Event deleted by admin",
    extra={
        "event_id": event_id,
        "admin_email": admin.email,
        "event_type": result.event_type,
    },
)
```

The reason for this pattern is partly about queryability - log aggregators can index the `event_id` field separately and let you filter on it - but mostly about security. When you interpolate user-controlled data into a log message, you open the door to log injection attacks.

## Log injection

Log injection is what happens when an attacker crafts input that corrupts your log output. The classic attack looks like this: a user submits an event ID containing a newline and a fake log entry.

```python
# Attacker submits this as event_id
event_id = "abc123\n[CRITICAL] System compromised - contact security@evil.com"

# If you log it directly in the message...
logger.warning(f"Processing event {event_id}")

# Your log output now contains a forged critical alert
```

The fix is to keep user data out of the message string entirely. When you put it in `extra`, the JSON formatter escapes special characters, and the malicious content becomes a harmless string value rather than a log line injection.

The codebase treats these as user-controlled and keeps them in `extra`: path parameters like execution_id or saga_id, query parameters, request body fields, Kafka message content, database results derived from user input, and exception messages (which often contain user data).

## What gets logged

Correlation and trace IDs are injected automatically by filters. The correlation ID follows a request through all services - it's set from incoming headers or generated for new requests. The trace and span IDs come from OpenTelemetry and link logs to distributed traces in Jaeger or Tempo. You don't need to pass these explicitly; they appear in every log line from code running in that request context.

For domain-specific context, developers add fields to `extra` based on what operation they're logging. An execution service method might include `execution_id`, `user_id`, `language`, and `status`. A replay session logs `session_id`, `replayed_events`, `failed_events`, and `duration_seconds`. A saga operation includes `saga_id` and `user_id`. The pattern is consistent: the message says what happened, `extra` says to what and by whom.

## Practical use

When something goes wrong, start by filtering logs by correlation_id to see everything that happened during that request. If you need to correlate with traces, use the trace_id to jump to Jaeger. If you're investigating a specific execution or saga, filter by those IDs - they're in the structured fields, not buried in message text.

The log level is controlled by the `LOG_LEVEL` environment variable. In production it's typically INFO, which captures normal operations (started, completed, processed) and problems (warnings for recoverable issues, errors for failures). DEBUG adds detailed diagnostic info and is usually too noisy for production but useful when investigating specific issues locally.
