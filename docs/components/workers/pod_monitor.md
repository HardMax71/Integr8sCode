# Pod monitor

The pod monitor watches executor pods and turns what Kubernetes reports into events. It's the only component that reads a pod's output, and it publishes the events that end an execution.

```mermaid
graph LR
    K8s[Kubernetes API] -->|LIST, then WATCH| Monitor[Pod monitor]
    Monitor -->|read logs| K8s
    Monitor -->|pod and execution events| Kafka[(Kafka)]
    Monitor -->|delete finished pod| K8s
```

## Watching

The monitor uses list-then-watch on pods matching `app=integr8s,component=executor` in `K8S_NAMESPACE`. On the first run, and again after the Kubernetes API answers 410 Gone, it LISTs all matching pods, handles each one as if it had just been added, and keeps the list's resource version. After that it WATCHes from that version. Each watch is bounded to 30 seconds, and APScheduler starts the next one every 5 seconds (never two at once), so a dropped connection just means the next cycle picks up from the saved version.

## Mapping

`PodEventMapper` maps each pod update by phase:

| Phase or watch event | Event |
|----------------------|-------|
| Pending with the PodScheduled condition | `pod_scheduled` |
| Running | `pod_running` |
| Succeeded | `execution_completed` |
| Failed | `execution_failed`, or `execution_completed` if all containers exited 0 |
| status reason `DeadlineExceeded` | `execution_timeout` (unless all containers exited 0) |
| watch event DELETED | `pod_terminated` |

It remembers the last phase seen per pod and drops an update with the same phase, so a watch restart doesn't publish duplicates. The memory holds up to 10,000 pods and then forgets the oldest half, so a late update for a forgotten pod can publish again. That check runs before the DELETED mapping, so a pod deleted after its final phase was already seen produces no `pod_terminated`. The memory is per process, which is why the monitor runs as a single replica.

For terminal events the mapper reads the container's logs, where the entrypoint writes stdout and stderr as length-prefixed frames, and the termination message, which carries the exit code, wall time, CPU jiffies and peak memory. If the logs can't be read, a pod whose containers all exited 0 publishes nothing at all. Any other failed pod, a timed-out one included, still publishes `execution_failed` with the error taken from the pod status.

Every event goes through the producer, which stores it in the MongoDB `events` collection before sending it to Kafka.

## Cleanup

After publishing `execution_completed`, `execution_failed` or `execution_timeout`, the monitor deletes the pod with no grace period. The ConfigMap goes with it through its ownerReference.

## Key files

| File | Purpose |
|------|---------|
| [`worker.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/worker.py) | Entry point, watch scheduling, 410 handling |
| [`monitor.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/services/pod_monitor/monitor.py) | List-then-watch and pod deletion |
| [`event_mapper.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/services/pod_monitor/event_mapper.py) | Phase mapping and log parsing |
