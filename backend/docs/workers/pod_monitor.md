# Pod Monitor Worker

## What It Does

The pod monitor is essentially a bridge between Kubernetes and our event system. It watches for pods created with specific labels (our execution pods) and translates what happens to them into events that the rest of the system can understand.

Think of it as a translator sitting between Kubernetes speaking its native language of pod phases and conditions, and our application speaking in terms of execution events.

## How It Works

When an execution starts, the system creates a Kubernetes pod to run the user's code. The pod monitor watches the Kubernetes API using their watch mechanism, which is like a WebSocket connection that streams pod changes as they happen.

As pods go through their lifecycle - getting scheduled, starting to run, completing or failing - the monitor captures these state changes and maps them to our domain events. A pod becoming "Running" in Kubernetes becomes an ExecutionRunningEvent in our system. A pod that completes becomes either ExecutionCompletedEvent or ExecutionFailedEvent depending on the exit code.

The clever part is how it extracts logs. When a pod terminates, the monitor fetches the container logs, parses them to extract stdout, stderr, and resource usage metrics that were printed in a special JSON format, then includes all this data in the completion event.

## Its Place in the System

The pod monitor feeds the result processor. Here's the flow:

```
User submits code → Execution service creates pod → Pod runs
                                                        ↓
Pod monitor watches → Detects completion → Publishes event → Result processor stores output
```

Without the pod monitor, we'd have no way to know when executions finish or what their output was. It's the eyes and ears of the system for everything happening in Kubernetes.

The service runs as a standalone container because it needs to maintain a persistent watch connection to the Kubernetes API. If it was part of the main backend, every backend restart would break the watch and potentially miss pod events.

## Reconciliation

One interesting feature is state reconciliation. Every five minutes, the monitor queries Kubernetes for all pods matching our labels and compares them to what it thinks it's tracking. This catches any events that might have been missed due to network issues or restarts. It's like doing a periodic inventory check to make sure nothing slipped through the cracks.