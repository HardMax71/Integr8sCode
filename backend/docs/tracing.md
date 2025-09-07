# Distributed Tracing

## What is this?

The tracing module gives you visibility into what happens when someone executes code through our platform. Think of it like a GPS tracker for requests - it follows them as they move between different services and shows you exactly where they go, how long each step takes, and if anything goes wrong.

## How it works

When a user submits code to execute, we generate a unique trace ID that acts like a tracking number. This ID follows the request everywhere:

First, the API receives the request and starts a trace. It records things like who made the request, what language they're using, and when it arrived. Then it publishes an event to Kafka with that trace ID embedded in the message headers.

The K8s Worker picks up that event and continues the trace. It knows it's part of the same request because of the trace ID. When it creates a Kubernetes pod to run the code, it logs that as a span (a unit of work) within the larger trace.

The Pod Monitor watches the pod and adds its own spans showing the pod starting up, running, and completing. If the pod crashes or times out, that gets recorded too with the full error details.

Finally, the Result Processor takes the execution results and adds the final spans showing how the results were stored and sent back to the user.

## Why we need it

Without tracing, debugging distributed systems is like trying to follow a package through the postal system without a tracking number. You know it went in one end and maybe came out the other, but you have no idea what happened in between.

With tracing, you can answer questions like:
- Why did this execution take 30 seconds when it usually takes 5?
- Which service is the bottleneck when we're under load?
- Why did this execution fail but the logs don't show any errors?
- How many retries happened before this succeeded?

## The technical bits

We use OpenTelemetry because it's the industry standard and works with everything. The traces get sent to Jaeger through the OpenTelemetry Collector, which acts as a middleman that can filter, sample, and route traces to different backends.

Each service creates spans that nest inside their parent span, forming a tree structure. The root span represents the entire request, and child spans represent the work done by each service. Spans can have attributes (key-value pairs), events (timestamped logs), and links to other traces.

The adaptive sampling is clever - when the system is quiet, we trace everything to catch rare issues. When it's busy, we sample less to avoid overwhelming the tracing backend. This happens automatically based on the current load.

## Using it

To see traces, open Jaeger at http://localhost:16686. You can search by trace ID, execution ID, user ID, or time range. Each trace shows as a timeline with colored bars representing different services. Click on any bar to see its details, including timing, attributes, and any errors.

The most useful view is often the trace comparison - you can compare a slow execution with a fast one to see exactly where the extra time went. This has saved us countless hours of debugging.

## Adding tracing to new code

If you're adding a new service or endpoint, just use the trace_span context manager or trace_method decorator. The module handles all the complexity of context propagation and error handling. The important thing is to add meaningful span names and attributes so future you (or your teammates) can understand what's happening.

Remember that traces are for understanding system behavior, not for logging every detail. Keep spans focused on significant operations like database queries, external API calls, or complex computations. Too many spans make traces hard to read and expensive to store.