from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

from app.core.logging import logger
from app.events.core.consumer_group_names import GroupId
from app.schemas_avro.event_schemas import (
    BaseEvent,
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionErrorType,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    PodRunningEvent,
    PodScheduledEvent,
    PodTerminatedEvent,
)

type PodPhase = str
type EventList = list[BaseEvent]


@dataclass(frozen=True)
class PodContext:
    """Immutable context for pod event processing"""
    pod: k8s_client.V1Pod
    execution_id: str
    metadata: EventMetadata
    phase: PodPhase
    event_type: str


@dataclass(frozen=True)
class PodLogs:
    """Parsed pod logs and execution results"""
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    resource_usage: dict[str, Any] | None = None

    @property
    def output(self) -> str:
        """Combined output with stderr marked if present"""
        if not self.stderr:
            return self.stdout
        if not self.stdout:
            return self.stderr
        return f"{self.stdout}\n--- stderr ---\n{self.stderr}"

    @property
    def runtime_ms(self) -> int:
        """Execution time in milliseconds"""
        if not self.resource_usage:
            return 0
        return int(float(self.resource_usage.get("execution_time_wall_seconds", 0)) * 1000)


class EventMapper(Protocol):
    """Protocol for event mapping functions"""

    def __call__(self, ctx: PodContext) -> BaseEvent | None: ...


class PodEventMapper:
    """Maps Kubernetes pod objects to application events"""

    def __init__(self) -> None:
        self._event_cache: dict[str, PodPhase] = {}
        self._k8s_api = self._init_k8s_client()

        # Phase to event mapper registry
        self._phase_mappers: dict[PodPhase, list[EventMapper]] = {
            "Pending": [self._map_scheduled],
            "Running": [self._map_running],
            "Succeeded": [self._map_completed],
            "Failed": [self._map_failed_or_completed],
        }

        # Special event type handlers
        self._event_type_mappers: dict[str, list[EventMapper]] = {
            "DELETED": [self._map_terminated],
        }

    def map_pod_event(self, pod: k8s_client.V1Pod, event_type: str) -> EventList:
        """Map a Kubernetes pod to application events"""
        # Extract execution ID
        execution_id = self._extract_execution_id(pod)
        if not execution_id:
            logger.warning(f"No execution ID found for pod {pod.metadata.name}")
            return []

        # Create context
        phase = pod.status.phase if pod.status else "Unknown"

        # Skip duplicate events
        if self._is_duplicate(pod.metadata.name, phase):
            return []

        ctx = PodContext(
            pod=pod,
            execution_id=execution_id,
            metadata=self._create_metadata(pod),
            phase=phase,
            event_type=event_type
        )

        # Collect events from mappers
        events: list[BaseEvent] = []

        # Check for timeout first - if pod timed out, only return timeout event
        if timeout_event := self._check_timeout(ctx):
            events.append(timeout_event)
            return events  # Don't process other events if timed out

        # Phase-based mappers
        for mapper in self._phase_mappers.get(phase, []):
            if event := mapper(ctx):
                events.append(event)

        # Event type mappers
        for mapper in self._event_type_mappers.get(event_type, []):
            if event := mapper(ctx):
                events.append(event)

        return events

    def _extract_execution_id(self, pod: k8s_client.V1Pod) -> str | None:
        """Extract execution ID from various pod fields"""
        if not pod.metadata:
            return None

        # Try multiple sources in order
        sources = [
            lambda: pod.metadata.labels.get("execution-id") if pod.metadata.labels else None,
            lambda: pod.metadata.annotations.get("integr8s.io/execution-id") if pod.metadata.annotations else None,
            lambda: pod.metadata.name[5:] if pod.metadata.name and pod.metadata.name.startswith("exec-") else None,
        ]

        for source in sources:
            if exec_id := source():
                try:
                    return str(exec_id)
                except ValueError:
                    logger.warning(f"Invalid execution ID: {exec_id}")

        return None

    def _create_metadata(self, pod: k8s_client.V1Pod) -> EventMetadata:
        """Create event metadata from pod"""
        labels = pod.metadata.labels or {}
        return EventMetadata(
            user_id=labels.get("user-id"),
            service_name=GroupId.POD_MONITOR,
            service_version="1.0.0"
        )

    def _is_duplicate(self, pod_name: str, phase: PodPhase) -> bool:
        """Check if this is a duplicate event"""
        if self._event_cache.get(pod_name) == phase:
            return True
        self._event_cache[pod_name] = phase
        return False

    def _map_scheduled(self, ctx: PodContext) -> PodScheduledEvent | None:
        """Map pending pod to scheduled event"""
        if not ctx.pod.status or not ctx.pod.status.conditions:
            return None

        # Find PodScheduled condition
        scheduled_condition = next(
            (c for c in ctx.pod.status.conditions
             if c.type == "PodScheduled" and c.status == "True"),
            None
        )

        if not scheduled_condition:
            return None

        return PodScheduledEvent(
            execution_id=ctx.execution_id,
            pod_name=ctx.pod.metadata.name,
            node_name=ctx.pod.spec.node_name or "pending",
            metadata=ctx.metadata
        )

    def _map_running(self, ctx: PodContext) -> PodRunningEvent | None:
        """Map running pod to running event"""
        if not ctx.pod.status:
            return None

        container_statuses = [
            {
                "name": status.name,
                "ready": status.ready,
                "restart_count": status.restart_count,
                "state": self._format_container_state(status.state)
            }
            for status in (ctx.pod.status.container_statuses or [])
        ]

        return PodRunningEvent(
            execution_id=ctx.execution_id,
            pod_name=ctx.pod.metadata.name,
            container_statuses=container_statuses,
            metadata=ctx.metadata
        )

    def _map_completed(self, ctx: PodContext) -> ExecutionCompletedEvent | None:
        """Map succeeded pod to completed event"""
        container = self._get_main_container(ctx.pod)
        if not container or not container.state or not container.state.terminated:
            return None

        logs = self._extract_logs(ctx.pod)
        exit_code = logs.exit_code if logs.exit_code is not None else container.state.terminated.exit_code

        return ExecutionCompletedEvent(
            execution_id=ctx.execution_id,
            exit_code=exit_code,
            output=logs.output,
            runtime_ms=logs.runtime_ms,
            metadata=ctx.metadata
        )

    def _map_failed_or_completed(self, ctx: PodContext) -> BaseEvent | None:
        """Map failed pod to either completed or failed event"""
        # Check if container actually succeeded despite pod failure
        if self._all_containers_succeeded(ctx.pod):
            return self._map_completed(ctx)
        
        # Also check if pod failed due to deadline but container completed
        if ctx.pod.status and ctx.pod.status.reason == "DeadlineExceeded":
            # Check if any container completed successfully
            for status in (ctx.pod.status.container_statuses or []):
                if (status.state and
                    status.state.terminated and
                    status.state.terminated.exit_code == 0 and
                    status.state.terminated.reason == "Completed"):
                    # Container completed successfully, treat as completion not failure
                    return self._map_completed(ctx)

        return self._map_failed(ctx)

    def _map_failed(self, ctx: PodContext) -> ExecutionFailedEvent | None:
        """Map failed pod to failed event"""
        error_info = self._analyze_failure(ctx.pod)
        logs = self._extract_logs(ctx.pod)

        return ExecutionFailedEvent(
            execution_id=ctx.execution_id,
            error=error_info.message,
            error_type=error_info.error_type,
            exit_code=error_info.exit_code,
            output=logs.output if logs.output else None,
            metadata=ctx.metadata
        )

    def _map_terminated(self, ctx: PodContext) -> PodTerminatedEvent | None:
        """Map deleted pod to terminated event"""
        container = self._get_main_container(ctx.pod)
        if not container or not container.state or not container.state.terminated:
            return None

        terminated = container.state.terminated
        return PodTerminatedEvent(
            execution_id=ctx.execution_id,
            pod_name=ctx.pod.metadata.name,
            exit_code=terminated.exit_code,
            reason=terminated.reason or "Terminated",
            message=terminated.message,
            metadata=ctx.metadata
        )

    def _check_timeout(self, ctx: PodContext) -> ExecutionTimeoutEvent | None:
        """Check if pod exceeded active deadline"""
        # First check if the container actually completed successfully
        if ctx.pod.status and ctx.pod.status.container_statuses:
            # Check if any container completed successfully (exit code 0)
            for status in ctx.pod.status.container_statuses:
                if (status.state and
                    status.state.terminated and
                    status.state.terminated.exit_code == 0 and
                    status.state.terminated.reason == "Completed"):
                    # Container completed successfully, not a real timeout
                    return None
        
        # Check pod status for timeout
        is_timeout = (
                ctx.pod.status and
                ctx.pod.status.reason == "DeadlineExceeded"
        )

        # Check container status for timeout
        if not is_timeout and ctx.pod.status and ctx.pod.status.container_statuses:
            is_timeout = any(
                status.state and
                status.state.terminated and
                status.state.terminated.reason == "DeadlineExceeded"
                for status in ctx.pod.status.container_statuses
            )

        if not is_timeout:
            return None

        logs = self._extract_logs(ctx.pod)
        return ExecutionTimeoutEvent(
            execution_id=ctx.execution_id,
            timeout_seconds=ctx.pod.spec.active_deadline_seconds or 0,
            partial_output=logs.output if logs.output else None,
            metadata=ctx.metadata
        )

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
            status.state and
            status.state.terminated and
            status.state.terminated.exit_code == 0
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
            error_type=ExecutionErrorType.SYSTEM_ERROR
        )

        if not pod.status:
            return default

        # Check for resource limits
        if pod.status.reason == "Evicted":
            return self.FailureInfo(
                message="Pod evicted due to resource constraints",
                error_type=ExecutionErrorType.RESOURCE_LIMIT
            )

        # Check container statuses
        for status in (pod.status.container_statuses or []):
            # Terminated container
            if status.state and status.state.terminated:
                terminated = status.state.terminated
                if terminated.exit_code != 0:
                    return self.FailureInfo(
                        message=terminated.message or f"Container exited with code {terminated.exit_code}",
                        error_type=ExecutionErrorType.SCRIPT_ERROR,
                        exit_code=terminated.exit_code
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
                        message=waiting.message or f"Container waiting: {waiting.reason}",
                        error_type=error_type
                    )

        # Check for OOM
        if "OOMKilled" in (pod.status.message or ""):
            return self.FailureInfo(
                message="Container killed due to out of memory",
                error_type=ExecutionErrorType.RESOURCE_LIMIT
            )

        return default

    def _extract_logs(self, pod: k8s_client.V1Pod) -> PodLogs:
        """Extract and parse pod logs"""
        if not self._k8s_api or not pod.metadata:
            return PodLogs()

        # Check if any container terminated
        has_terminated = any(
            status.state and status.state.terminated
            for status in (pod.status.container_statuses if pod.status else [])
        )

        if not has_terminated:
            logger.debug(f"Pod {pod.metadata.name} has no terminated containers")
            return PodLogs()

        try:
            logs = self._k8s_api.read_namespaced_pod_log(
                name=pod.metadata.name,
                namespace=pod.metadata.namespace or "default",
                tail_lines=10000
            )

            if not logs:
                return PodLogs()

            # Try to parse executor JSON
            return self._parse_executor_output(logs)

        except Exception as e:
            self._log_extraction_error(pod.metadata.name, str(e))
            return PodLogs()

    def _parse_executor_output(self, logs: str) -> PodLogs:
        """Parse executor JSON output from logs"""
        logs_stripped = logs.strip()

        # Try full output as JSON
        if result := self._try_parse_json(logs_stripped):
            return result

        # Try line by line
        for line in logs_stripped.split('\n'):
            if result := self._try_parse_json(line.strip()):
                return result

        # Fallback to raw logs
        logger.warning("Logs do not contain valid executor JSON, treating as raw output")
        return PodLogs(stdout=logs)

    def _try_parse_json(self, text: str) -> PodLogs | None:
        """Try to parse text as executor JSON output"""
        if not (text.startswith('{') and text.endswith('}')):
            return None

        try:
            data = json.loads(text)
            if all(key in data for key in ["exit_code", "stdout", "stderr"]):
                return PodLogs(
                    stdout=data.get("stdout", ""),
                    stderr=data.get("stderr", ""),
                    exit_code=data.get("exit_code", 0),
                    resource_usage=data.get("resource_usage", {})
                )
        except json.JSONDecodeError:
            pass

        return None

    def _log_extraction_error(self, pod_name: str, error: str) -> None:
        """Log extraction errors with appropriate level"""
        error_lower = error.lower()

        if "404" in error or "not found" in error_lower:
            logger.debug(f"Pod {pod_name} logs not found - pod may have been deleted")
        elif "400" in error:
            logger.debug(f"Pod {pod_name} logs not available - container may still be creating")
        else:
            logger.warning(f"Failed to extract logs from pod {pod_name}: {error}")

    def _init_k8s_client(self) -> k8s_client.CoreV1Api | None:
        """Initialize Kubernetes client"""
        try:
            try:
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                k8s_config.load_kube_config()
            return k8s_client.CoreV1Api()
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            return None

    def clear_cache(self) -> None:
        """Clear event cache"""
        self._event_cache.clear()
