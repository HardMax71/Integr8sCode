from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import aiohttp
import structlog
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.rest import ApiException

from app.core.utils import StringEnum
from app.domain.enums import ExecutionErrorType
from app.domain.events import (
    ContainerStatusInfo,
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    PodRunningEvent,
    PodScheduledEvent,
    PodTerminatedEvent,
    ResourceUsageDomain,
)

# Python 3.12 type aliases
type PodPhase = str
type PodMonitorEvent = (
    PodScheduledEvent
    | PodRunningEvent
    | PodTerminatedEvent
    | ExecutionCompletedEvent
    | ExecutionFailedEvent
    | ExecutionTimeoutEvent
)
type EventList = list[PodMonitorEvent]
type AsyncMapper = Callable[["PodContext"], Awaitable[PodMonitorEvent | None]]

_UNREADABLE_OUTPUT = "The output couldn't be read from the pod's log."


class WatchEventType(StringEnum):
    """Kubernetes watch event types."""

    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"


@dataclass(frozen=True)
class PodContext:
    """Immutable context for pod event processing"""

    pod: k8s_client.V1Pod
    execution_id: str
    metadata: EventMetadata
    phase: PodPhase
    event_type: WatchEventType


@dataclass(frozen=True)
class PodLogs:
    """A finished pod's output and result; the output is empty, with a note in stderr, when the log can't be read."""

    stdout: str
    stderr: str
    exit_code: int
    resource_usage: ResourceUsageDomain


class PodEventMapper:
    """Maps Kubernetes pod objects to application events"""

    _MAX_CACHE_SIZE = 10_000
    # Read the log from its start so the STDOUT header survives; entrypoint.sh frames far less than this.
    _MAX_LOG_BYTES = 2 * 1024 * 1024

    def __init__(self, logger: structlog.stdlib.BoundLogger, k8s_api: k8s_client.CoreV1Api) -> None:
        self.logger = logger
        self._event_cache: dict[str, PodPhase] = {}
        self._k8s_api = k8s_api

        # Phase to event mapper registry
        self._phase_mappers: dict[PodPhase, list[AsyncMapper]] = {
            "Pending": [self._map_scheduled],
            "Running": [self._map_running],
            "Succeeded": [self._map_completed],
            "Failed": [self._map_failed_or_completed],
        }

    async def map_pod_event(self, pod: k8s_client.V1Pod, event_type: WatchEventType) -> EventList:
        """Map a Kubernetes pod to application events"""
        self.logger.info(
            "Pod event received",
            watch_event_type=event_type,
            pod_name=getattr(pod.metadata, "name", None),
            namespace=getattr(pod.metadata, "namespace", None),
            phase=getattr(pod.status, "phase", None),
        )
        # Extract execution ID
        execution_id = self._extract_execution_id(pod)
        if not execution_id:
            self.logger.warning(
                "Pod event without execution_id",
                pod_name=getattr(pod.metadata, "name", None),
                labels=getattr(pod.metadata, "labels", None),
                annotations=getattr(pod.metadata, "annotations", None),
            )
            return []

        phase = pod.status.phase if pod.status else "Unknown"
        pod_name = pod.metadata.name
        prior_phase = self._event_cache.get(pod_name)
        if event_type != WatchEventType.DELETED and prior_phase == phase:
            self.logger.debug("Duplicate pod event ignored", pod_name=pod_name, phase=phase)
            return []

        ctx = PodContext(
            pod=pod, execution_id=execution_id, metadata=self._create_metadata(pod), phase=phase, event_type=event_type
        )
        self.logger.info(
            "Pod event context",
            execution_id=ctx.execution_id,
            phase=ctx.phase,
            reason=getattr(getattr(pod, "status", None), "reason", None),
        )

        # A deleted pod gets what its phase still owes, then its termination, and leaves the cache
        if event_type == WatchEventType.DELETED:
            events = [] if prior_phase == phase else await self._map_phase(ctx, prior_phase)
            if terminated := self._map_terminated(ctx):
                events.append(terminated)
            self._event_cache.pop(pod_name, None)
            return events

        events = await self._map_phase(ctx, prior_phase)
        # A phase counts as seen only once it produced an event, so a later event in that phase tries again
        if events:
            self._remember(pod_name, phase)
        return events

    async def _map_phase(self, ctx: PodContext, prior_phase: PodPhase | None) -> EventList:
        """Map the pod's phase to its events; a timed-out pod yields only its timeout."""
        if timeout_event := await self._check_timeout(ctx):
            self.logger.info(
                "Pod event mapped to timeout",
                execution_id=ctx.execution_id,
                phase=ctx.phase,
                active_deadline_seconds=getattr(getattr(ctx.pod, "spec", None), "active_deadline_seconds", None),
            )
            return [timeout_event]

        # Special-case: when transitioning Pending -> Running but with no
        # container status info yet, skip emitting running to avoid noise.
        if (
            ctx.phase == "Running"
            and (not getattr(ctx.pod, "status", None) or not getattr(ctx.pod.status, "container_statuses", None))
            and prior_phase == "Pending"
        ):
            self.logger.debug(
                "Skipping running event, no container statuses after Pending", execution_id=ctx.execution_id
            )
            return []

        events: EventList = []
        for mapper in self._phase_mappers.get(ctx.phase, []):
            if event := await mapper(ctx):
                self.logger.info(
                    "Pod phase mapped",
                    mapper=getattr(mapper, "__name__", repr(mapper)),
                    mapped_event_type=event.event_type,
                    execution_id=ctx.execution_id,
                )
                events.append(event)
        return events

    def _extract_execution_id(self, pod: k8s_client.V1Pod) -> str | None:
        """Extract execution ID from various pod fields"""
        if not pod.metadata:
            return None

        # Try labels first
        if pod.metadata.labels and (exec_id := pod.metadata.labels.get("execution-id")):
            self.logger.debug("Extracted execution_id from label", pod_name=pod.metadata.name, execution_id=exec_id)
            return str(exec_id)

        # Try annotations
        if pod.metadata.annotations and (exec_id := pod.metadata.annotations.get("integr8s.io/execution-id")):
            self.logger.debug(
                "Extracted execution_id from annotation", pod_name=pod.metadata.name, execution_id=exec_id
            )
            return str(exec_id)

        # Try pod name pattern
        if pod.metadata.name and pod.metadata.name.startswith("exec-"):
            self.logger.debug("Extracted execution_id from pod name", pod_name=pod.metadata.name)
            return str(pod.metadata.name[5:])

        return None

    def _create_metadata(self, pod: k8s_client.V1Pod) -> EventMetadata:
        """Create event metadata from pod"""
        labels = pod.metadata.labels or {}

        md = EventMetadata(
            user_id=labels.get("user-id", ""),
            service_name="pod-monitor",
            service_version="1.0.0",
        )
        self.logger.info("Pod event metadata", user_id=md.user_id, pod_name=pod.metadata.name)
        return md

    def _remember(self, pod_name: str, phase: PodPhase) -> None:
        """Record the phase a pod's events went out for, so a repeat of that phase is skipped."""
        if len(self._event_cache) >= self._MAX_CACHE_SIZE:
            # Evict oldest half to amortise cleanup cost
            keys = list(self._event_cache)[: self._MAX_CACHE_SIZE // 2]
            for k in keys:
                del self._event_cache[k]
        self._event_cache[pod_name] = phase

    async def _map_scheduled(self, ctx: PodContext) -> PodScheduledEvent | None:
        """Map pending pod to scheduled event"""
        # K8s API can return pods without status
        if not ctx.pod.status or not ctx.pod.status.conditions:
            return None

        # Find PodScheduled condition
        scheduled_condition = next(
            (c for c in ctx.pod.status.conditions if c.type == "PodScheduled" and c.status == "True"), None
        )

        if not scheduled_condition:
            return None

        evt = PodScheduledEvent(
            execution_id=ctx.execution_id,
            aggregate_id=ctx.execution_id,
            pod_name=ctx.pod.metadata.name,
            node_name=ctx.pod.spec.node_name or "pending",
            metadata=ctx.metadata,
        )
        self.logger.debug("Mapped scheduled pod", mapped_event_type=evt.event_type, execution_id=ctx.execution_id)
        return evt

    async def _map_running(self, ctx: PodContext) -> PodRunningEvent | None:
        """Map running pod to running event"""
        # K8s API can return pods without status
        if not ctx.pod.status:
            return None

        container_statuses = [
            ContainerStatusInfo(
                name=status.name,
                ready=status.ready,
                restart_count=status.restart_count,
                state=self._format_container_state(status.state),
            )
            for status in (ctx.pod.status.container_statuses or [])
        ]

        evt = PodRunningEvent(
            execution_id=ctx.execution_id,
            aggregate_id=ctx.execution_id,
            pod_name=ctx.pod.metadata.name,
            container_statuses=container_statuses,
            metadata=ctx.metadata,
        )
        self.logger.debug("Mapped running pod", mapped_event_type=evt.event_type, execution_id=ctx.execution_id)
        return evt

    async def _map_completed(self, ctx: PodContext) -> ExecutionCompletedEvent | None:
        """Map succeeded pod to completed event"""
        container = self._get_main_container(ctx.pod)
        if not container or not container.state or not container.state.terminated:
            return None

        logs = await self._extract_logs(ctx.pod)
        if not logs:
            return None

        evt = ExecutionCompletedEvent(
            execution_id=ctx.execution_id,
            aggregate_id=ctx.execution_id,
            exit_code=logs.exit_code,
            resource_usage=logs.resource_usage,
            stdout=logs.stdout,
            stderr=logs.stderr,
            metadata=ctx.metadata,
        )
        self.logger.info("Mapped completed pod", execution_id=ctx.execution_id, exit_code=logs.exit_code)
        return evt

    async def _map_failed_or_completed(self, ctx: PodContext) -> PodMonitorEvent | None:
        """Map failed pod to either timeout, completed, or failed"""
        if ctx.pod.status and ctx.pod.status.reason == "DeadlineExceeded":
            if timeout_event := await self._check_timeout(ctx):
                return timeout_event

        if self._all_containers_succeeded(ctx.pod):
            return await self._map_completed(ctx)

        return await self._map_failed(ctx)

    async def _map_failed(self, ctx: PodContext) -> ExecutionFailedEvent | None:
        """Map failed pod to failed event"""
        error_info = self._analyze_failure(ctx.pod)
        logs = await self._extract_logs(ctx.pod)

        # Use logs data if available, fallback to error_info
        stdout = logs.stdout if logs else ""
        stderr = logs.stderr if logs and logs.stderr else error_info.message
        exit_code = error_info.exit_code
        if exit_code is None:
            exit_code = logs.exit_code if logs else 1

        evt = ExecutionFailedEvent(
            execution_id=ctx.execution_id,
            aggregate_id=ctx.execution_id,
            error_type=error_info.error_type,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            resource_usage=logs.resource_usage if logs else None,
            metadata=ctx.metadata,
        )
        self.logger.info(
            "Mapped failed pod",
            execution_id=ctx.execution_id,
            error_type=error_info.error_type,
            exit_code=exit_code,
        )
        return evt

    def _map_terminated(self, ctx: PodContext) -> PodTerminatedEvent | None:
        """Map deleted pod to terminated event"""
        container = self._get_main_container(ctx.pod)
        if not container or not container.state or not container.state.terminated:
            return None

        terminated = container.state.terminated
        evt = PodTerminatedEvent(
            execution_id=ctx.execution_id,
            aggregate_id=ctx.execution_id,
            pod_name=ctx.pod.metadata.name,
            exit_code=terminated.exit_code,
            reason=terminated.reason or "Terminated",
            message=getattr(terminated, "message", None),
            metadata=ctx.metadata,
        )
        self.logger.info(
            "Mapped terminated pod",
            execution_id=ctx.execution_id,
            reason=terminated.reason,
            exit_code=terminated.exit_code,
        )
        return evt

    async def _check_timeout(self, ctx: PodContext) -> ExecutionTimeoutEvent | None:
        if not (ctx.pod.status and ctx.pod.status.reason == "DeadlineExceeded"):
            return None

        # A pod can carry DeadlineExceeded while containers already exited 0.
        # In that case, let the normal completed mapping path handle it.
        if self._all_containers_succeeded(ctx.pod):
            self.logger.info("Timeout ignored, containers succeeded", execution_id=ctx.execution_id)
            return None

        logs = await self._extract_logs(ctx.pod) or PodLogs(
            stdout="", stderr=_UNREADABLE_OUTPUT, exit_code=-1, resource_usage=ResourceUsageDomain()
        )
        timeout_seconds = ctx.pod.spec.active_deadline_seconds or 0
        evt = ExecutionTimeoutEvent(
            execution_id=ctx.execution_id,
            aggregate_id=ctx.execution_id,
            timeout_seconds=timeout_seconds,
            resource_usage=logs.resource_usage,
            stdout=logs.stdout,
            stderr=logs.stderr,
            metadata=ctx.metadata,
        )
        self.logger.info(
            "Mapped timed out pod",
            execution_id=ctx.execution_id,
            active_deadline_seconds=ctx.pod.spec.active_deadline_seconds,
        )
        return evt

    def _get_main_container(self, pod: k8s_client.V1Pod) -> k8s_client.V1ContainerStatus | None:
        """Get the main (first) container status"""
        if not pod.status or not pod.status.container_statuses:
            return None
        return pod.status.container_statuses[0]

    def _all_containers_succeeded(self, pod: k8s_client.V1Pod) -> bool:
        """Check if all containers terminated with exit code 0"""
        if not pod.status or not pod.status.container_statuses:
            return False

        return all(
            status.state and status.state.terminated and status.state.terminated.exit_code == 0
            for status in pod.status.container_statuses
        )

    def _format_container_state(self, state: k8s_client.V1ContainerState | None) -> str:
        """Format container state as string"""
        if not state:
            return "unknown"

        if state.running:
            return "running"
        elif state.terminated:
            return f"terminated (exit_code={state.terminated.exit_code})"
        elif state.waiting:
            return f"waiting ({state.waiting.reason})"
        else:
            return "unknown"

    @dataclass
    class FailureInfo:
        """Pod failure analysis result"""

        message: str
        error_type: ExecutionErrorType
        exit_code: int | None = None

    def _analyze_failure(self, pod: k8s_client.V1Pod) -> FailureInfo:
        """Analyze pod failure and determine error type"""
        # Default failure info
        default = self.FailureInfo(
            message=(pod.status.message if pod.status else None) or "Pod failed",
            error_type=ExecutionErrorType.SYSTEM_ERROR,
        )

        if not pod.status:
            return default

        # Check for resource limits
        if pod.status.reason == "Evicted":
            return self.FailureInfo(
                message="Pod evicted due to resource constraints", error_type=ExecutionErrorType.RESOURCE_LIMIT
            )

        # Check container statuses
        for status in pod.status.container_statuses or []:
            # Terminated container
            if status.state and status.state.terminated:
                terminated = status.state.terminated
                if terminated.exit_code != 0:
                    return self.FailureInfo(
                        message=terminated.message
                        or pod.status.message
                        or f"Container exited with code {terminated.exit_code}",
                        error_type=ExecutionErrorType.SCRIPT_ERROR,
                        exit_code=terminated.exit_code,
                    )

            # Waiting container
            if status.state and status.state.waiting:
                waiting = status.state.waiting
                error_type_map = {
                    "ImagePullBackOff": ExecutionErrorType.SYSTEM_ERROR,
                    "ErrImagePull": ExecutionErrorType.SYSTEM_ERROR,
                    "CrashLoopBackOff": ExecutionErrorType.SCRIPT_ERROR,
                }

                if error_type := error_type_map.get(waiting.reason):
                    return self.FailureInfo(
                        message=waiting.message or f"Container waiting: {waiting.reason}", error_type=error_type
                    )

        # Check for OOM
        if "OOMKilled" in (pod.status.message or ""):
            return self.FailureInfo(
                message="Container killed due to out of memory", error_type=ExecutionErrorType.RESOURCE_LIMIT
            )

        return default

    async def _extract_logs(self, pod: k8s_client.V1Pod) -> PodLogs | None:
        """Read a finished pod's result, or None while its main container hasn't terminated.

        The exit code and usage come from the termination message. A log that can't be read leaves the output
        empty with a note in stderr, so the execution still ends instead of waiting on a pod nobody looks at again.
        """
        container = self._get_main_container(pod)
        if not container or not container.state or not container.state.terminated:
            return None

        terminated = container.state.terminated

        meta = self._parse_termination_message(terminated.message or "")

        try:
            # The stub says str, but with _preload_content=False the client returns the raw aiohttp response.
            response: aiohttp.ClientResponse = await self._k8s_api.read_namespaced_pod_log(  # type: ignore[assignment]
                name=pod.metadata.name,
                namespace=pod.metadata.namespace or "integr8scode",
                limit_bytes=self._MAX_LOG_BYTES,
                _preload_content=False,
            )
            response.raise_for_status()
            logs = await response.read()
        except ApiException, aiohttp.ClientError, TimeoutError:
            self.logger.warning("Failed to fetch pod logs", pod_name=pod.metadata.name, exc_info=True)
            stdout, stderr = "", _UNREADABLE_OUTPUT
        else:
            stdout, stderr = self._parse_framed_output(logs)

        return PodLogs(
            exit_code=int(meta.get("exit_code", str(terminated.exit_code or 0))),
            stdout=stdout,
            stderr=stderr,
            resource_usage=ResourceUsageDomain(
                execution_time_wall_seconds=float(meta.get("wall_seconds", "0")),
                cpu_time_jiffies=int(meta.get("cpu_jiffies", "0")),
                clk_tck_hertz=int(meta.get("clk_tck", "100")),
                peak_memory_kb=int(meta.get("peak_memory_kb", "0")),
            ),
        )

    @staticmethod
    def _parse_termination_message(raw: str) -> dict[str, str]:
        """Parse key=value metadata from K8s termination message."""
        return {key: value for key, sep, value in (line.partition("=") for line in raw.strip().splitlines()) if sep}

    @staticmethod
    def _parse_framed_output(logs: bytes) -> tuple[str, str]:
        """Extract stdout/stderr from the entrypoint's framed output, whose lengths count bytes."""
        try:
            idx = logs.index(b"STDOUT ") + 7
            nl = logs.index(b"\n", idx)
            stdout_len = int(logs[idx:nl])
            stdout = logs[nl + 1 : nl + 1 + stdout_len]

            idx = logs.index(b"STDERR ", nl + 1 + stdout_len) + 7
            nl = logs.index(b"\n", idx)
            stderr_len = int(logs[idx:nl])
            stderr = logs[nl + 1 : nl + 1 + stderr_len]
        except ValueError, IndexError:
            return "", ""

        return stdout.decode(errors="replace"), stderr.decode(errors="replace")
