import ast
import json
from dataclasses import dataclass
from typing import Protocol

from kubernetes import client as k8s_client

from app.core.logging import logger
from app.domain.enums.kafka import GroupId
from app.domain.enums.storage import ExecutionErrorType
from app.domain.execution import ResourceUsageDomain
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import (
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
)
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.pod import (
    PodRunningEvent,
    PodScheduledEvent,
    PodTerminatedEvent,
)

# Python 3.12 type aliases
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
    resource_usage: ResourceUsageDomain | None = None


class EventMapper(Protocol):
    """Protocol for event mapping functions"""

    def __call__(self, ctx: PodContext) -> BaseEvent | None: ...


class PodEventMapper:
    """Maps Kubernetes pod objects to application events"""

    def __init__(self, k8s_api: k8s_client.CoreV1Api | None = None) -> None:
        self._event_cache: dict[str, PodPhase] = {}
        self._k8s_api = k8s_api

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
        logger.info(
            f"POD-EVENT: type={event_type} name={getattr(pod.metadata, 'name', None)} "
            f"ns={getattr(pod.metadata, 'namespace', None)} phase={getattr(pod.status, 'phase', None)}"
        )
        # Extract execution ID
        execution_id = self._extract_execution_id(pod)
        if not execution_id:
            logger.warning(
                f"POD-EVENT: missing execution_id name={getattr(pod.metadata, 'name', None)} "
                f"labels={getattr(pod.metadata, 'labels', None)} "
                f"annotations={getattr(pod.metadata, 'annotations', None)}"
            )
            return []

        # Create context
        phase = pod.status.phase if pod.status else "Unknown"

        # Record prior phase before duplicate cache update
        prior_phase = self._event_cache.get(getattr(pod.metadata, "name", "")) if pod.metadata else None

        # Skip duplicate events
        if pod.metadata and self._is_duplicate(pod.metadata.name, phase):
            logger.debug(
                f"POD-EVENT: duplicate ignored name={pod.metadata.name} phase={phase}"
            )
            return []

        ctx = PodContext(
            pod=pod,
            execution_id=execution_id,
            metadata=self._create_metadata(pod),
            phase=phase,
            event_type=event_type
        )
        logger.info(
            f"POD-EVENT: ctx execution_id={ctx.execution_id} phase={ctx.phase} "
            f"reason={getattr(getattr(pod, 'status', None), 'reason', None)}"
        )

        # Collect events from mappers
        events: list[BaseEvent] = []

        # Check for timeout first - if pod timed out, only return timeout event
        if timeout_event := self._check_timeout(ctx):
            logger.info(
                f"POD-EVENT: mapped TIMEOUT exec={ctx.execution_id} phase={ctx.phase} "
                f"adl={getattr(getattr(pod, 'spec', None), 'active_deadline_seconds', None)}"
            )
            events.append(timeout_event)
            return events  # Don't process other events if timed out

        # Special-case: when transitioning Pending -> Running but with no
        # container status info yet, skip emitting running to avoid noise.
        if (
            phase == "Running"
            and (not getattr(pod, "status", None) or not getattr(pod.status, "container_statuses", None))
            and pod.metadata
            and prior_phase == "Pending"
        ):
            logger.debug(
                f"POD-EVENT: skipping running map due to empty statuses after Pending exec={execution_id}"
            )
            return events

        # Phase-based mappers
        for mapper in self._phase_mappers.get(phase, []):
            if event := mapper(ctx):
                mapper_name = getattr(mapper, "__name__", repr(mapper))
                logger.info(
                    f"POD-EVENT: phase-map {mapper_name} -> {event.event_type} exec={ctx.execution_id}"
                )
                events.append(event)

        # Event type mappers
        for mapper in self._event_type_mappers.get(event_type, []):
            if event := mapper(ctx):
                mapper_name = getattr(mapper, "__name__", repr(mapper))
                logger.info(
                    f"POD-EVENT: type-map {mapper_name} -> {event.event_type} exec={ctx.execution_id}"
                )
                events.append(event)

        return events

    def _extract_execution_id(self, pod: k8s_client.V1Pod) -> str | None:
        """Extract execution ID from various pod fields"""
        if not pod.metadata:
            return None

        # Try labels first
        if pod.metadata.labels and (exec_id := pod.metadata.labels.get("execution-id")):
            logger.debug(
                f"POD-EVENT: extracted exec-id from label name={pod.metadata.name} exec_id={exec_id}"
            )
            return str(exec_id)
        
        # Try annotations
        if pod.metadata.annotations and (exec_id := pod.metadata.annotations.get("integr8s.io/execution-id")):
            logger.debug(
                f"POD-EVENT: extracted exec-id from annotation name={pod.metadata.name} exec_id={exec_id}"
            )
            return str(exec_id)
        
        # Try pod name pattern
        if pod.metadata.name and pod.metadata.name.startswith("exec-"):
            logger.debug(
                f"POD-EVENT: extracted exec-id from name pattern name={pod.metadata.name}"
            )
            return str(pod.metadata.name[5:])
        
        return None

    def _create_metadata(self, pod: k8s_client.V1Pod) -> EventMetadata:
        """Create event metadata from pod with correlation tracking"""
        labels = pod.metadata.labels or {}
        annotations = pod.metadata.annotations or {}

        # Try to get correlation_id from annotations first (full value),
        # then labels (potentially truncated)
        correlation_id = (
            annotations.get("integr8s.io/correlation-id") or
            labels.get("correlation-id") or
            ""
        )

        md = EventMetadata(
            user_id=labels.get("user-id"),
            service_name=GroupId.POD_MONITOR,
            service_version="1.0.0",
            correlation_id=correlation_id
        )
        logger.info(
            f"POD-EVENT: metadata user_id={md.user_id} corr={md.correlation_id} name={pod.metadata.name}"
        )
        return md

    def _is_duplicate(self, pod_name: str, phase: PodPhase) -> bool:
        """Check if this is a duplicate event"""
        if self._event_cache.get(pod_name) == phase:
            return True
        self._event_cache[pod_name] = phase
        return False

    def _map_scheduled(self, ctx: PodContext) -> PodScheduledEvent | None:
        """Map pending pod to scheduled event"""
        # K8s API can return pods without status
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

        evt = PodScheduledEvent(
            execution_id=ctx.execution_id,
            pod_name=ctx.pod.metadata.name,
            node_name=ctx.pod.spec.node_name or "pending",
            metadata=ctx.metadata
        )
        logger.debug(f"POD-EVENT: mapped scheduled -> {evt.event_type} exec={ctx.execution_id}")
        return evt

    def _map_running(self, ctx: PodContext) -> PodRunningEvent | None:
        """Map running pod to running event"""
        # K8s API can return pods without status
        if not ctx.pod.status:
            return None

        container_statuses = [
            {
                "name": status.name,
                "ready": str(status.ready),
                "restart_count": str(status.restart_count),
                "state": self._format_container_state(status.state)
            }
            for status in (ctx.pod.status.container_statuses or [])
        ]

        evt = PodRunningEvent(
            execution_id=ctx.execution_id,
            pod_name=ctx.pod.metadata.name,
            container_statuses=json.dumps(container_statuses),  # Serialize as JSON string
            metadata=ctx.metadata
        )
        logger.debug(f"POD-EVENT: mapped running -> {evt.event_type} exec={ctx.execution_id}")
        return evt

    def _map_completed(self, ctx: PodContext) -> ExecutionCompletedEvent | None:
        """Map succeeded pod to completed event"""
        container = self._get_main_container(ctx.pod)
        if not container or not container.state or not container.state.terminated:
            return None

        logs = self._extract_logs(ctx.pod)
        exit_code = logs.exit_code if logs.exit_code is not None else container.state.terminated.exit_code

        evt = ExecutionCompletedEvent(
            execution_id=ctx.execution_id,
            aggregate_id=ctx.execution_id,  # Set aggregate_id to execution_id
            exit_code=exit_code,
            stdout=logs.stdout,
            stderr=logs.stderr,
            resource_usage=logs.resource_usage or ResourceUsageDomain.from_dict({}),
            metadata=ctx.metadata
        )
        logger.info(
            f"POD-EVENT: mapped completed exec={ctx.execution_id} exit_code={exit_code}"
        )
        return evt

    def _map_failed_or_completed(self, ctx: PodContext) -> BaseEvent | None:
        """Map failed pod to either timeout, completed, or failed"""
        if ctx.pod.status and ctx.pod.status.reason == "DeadlineExceeded":
            return self._check_timeout(ctx)

        if self._all_containers_succeeded(ctx.pod):
            return self._map_completed(ctx)

        return self._map_failed(ctx)

    def _map_failed(self, ctx: PodContext) -> ExecutionFailedEvent | None:
        """Map failed pod to failed event"""
        error_info = self._analyze_failure(ctx.pod)
        logs = self._extract_logs(ctx.pod)

        # If no stderr from logs but we have an error message, use it as stderr
        stderr = logs.stderr if logs.stderr else error_info.message
        # Ensure exit_code is populated (fallback to logs or generic non-zero)
        exit_code = error_info.exit_code if error_info.exit_code is not None \
            else (logs.exit_code if logs.exit_code is not None else 1)

        evt = ExecutionFailedEvent(
            execution_id=ctx.execution_id,
            aggregate_id=ctx.execution_id,  # Set aggregate_id to execution_id
            error_type=error_info.error_type,
            exit_code=exit_code,
            stdout=logs.stdout,
            stderr=stderr,
            error_message=stderr,
            resource_usage=logs.resource_usage or ResourceUsageDomain.from_dict({}),
            metadata=ctx.metadata
        )
        logger.info(
            f"POD-EVENT: mapped failed exec={ctx.execution_id} error_type={error_info.error_type} "
            f"exit={error_info.exit_code}"
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
            pod_name=ctx.pod.metadata.name,
            exit_code=terminated.exit_code,
            reason=terminated.reason or "Terminated",
            message=getattr(terminated, "message", None),
            metadata=ctx.metadata
        )
        logger.info(
            f"POD-EVENT: mapped terminated exec={ctx.execution_id} reason={terminated.reason} "
            f"exit={terminated.exit_code}"
        )
        return evt

    def _check_timeout(self, ctx: PodContext) -> ExecutionTimeoutEvent | None:
        if not (ctx.pod.status and ctx.pod.status.reason == "DeadlineExceeded"):
            return None

        logs = self._extract_logs(ctx.pod)
        evt = ExecutionTimeoutEvent(
            execution_id=ctx.execution_id,
            aggregate_id=ctx.execution_id,
            timeout_seconds=ctx.pod.spec.active_deadline_seconds or 0,
            stdout=logs.stdout,
            stderr=logs.stderr,
            resource_usage=logs.resource_usage or ResourceUsageDomain.from_dict({}),
            metadata=ctx.metadata
        )
        logger.info(
            f"POD-EVENT: mapped timeout exec={ctx.execution_id} adl={ctx.pod.spec.active_deadline_seconds}"
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
                    # Prefer explicit messages when available
                    term_msg = getattr(terminated, "message", None)
                    status_msg = pod.status.message if getattr(pod, "status", None) else None
                    return self.FailureInfo(
                        message=term_msg or status_msg or f"Container exited with code {terminated.exit_code}",
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
        # Without k8s API or metadata, can't fetch logs
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
                namespace=pod.metadata.namespace or "integr8scode",
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

        data = ast.literal_eval(text)
        return PodLogs(
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            exit_code=data.get("exit_code", 0),
            resource_usage=ResourceUsageDomain.from_dict(data.get("resource_usage", {}))
        )

    def _log_extraction_error(self, pod_name: str, error: str) -> None:
        """Log extraction errors with appropriate level"""
        error_lower = error.lower()

        if "404" in error or "not found" in error_lower:
            logger.debug(f"Pod {pod_name} logs not found - pod may have been deleted")
        elif "400" in error:
            logger.debug(f"Pod {pod_name} logs not available - container may still be creating")
        else:
            logger.warning(f"Failed to extract logs from pod {pod_name}: {error}")


    def clear_cache(self) -> None:
        """Clear event cache"""
        self._event_cache.clear()
