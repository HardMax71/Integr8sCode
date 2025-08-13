"""Log extraction service for retrieving pod logs"""

import asyncio
import logging
from functools import partial
from typing import Any, AsyncGenerator, Dict, Optional

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException

from app.core.exceptions import ServiceError

logger = logging.getLogger(__name__)


class LogExtractor:
    """Service for extracting logs from Kubernetes pods"""

    def __init__(self) -> None:
        self.v1: Optional[k8s_client.CoreV1Api] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize Kubernetes client"""
        if self._initialized:
            return

        try:
            # Try in-cluster config first
            try:
                k8s_config.load_incluster_config()
                logger.info("Using in-cluster Kubernetes config")
            except k8s_config.ConfigException:
                # Fall back to kubeconfig
                k8s_config.load_kube_config()
                logger.info("Using kubeconfig")

            self.v1 = k8s_client.CoreV1Api()
            self._initialized = True

        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            raise ServiceError(f"Kubernetes initialization failed: {e}") from e

    async def extract_logs(
        self,
        pod_name: str,
        namespace: str = "default",
        container: Optional[str] = None,
        previous: bool = False,
        tail_lines: Optional[int] = None,
        since_seconds: Optional[int] = None,
        timeout: int = 30,
        max_size: int = 10 * 1024 * 1024,  # 10MB
    ) -> Dict[str, str]:
        """
        Extract logs from a pod
        
        Args:
            pod_name: Name of the pod
            namespace: Kubernetes namespace
            container: Specific container name (optional)
            previous: Get previous container logs
            tail_lines: Number of lines from the end
            since_seconds: Logs since N seconds ago
            timeout: Timeout in seconds
            max_size: Maximum log size in bytes
            
        Returns:
            Dictionary with stdout and stderr logs
        """
        await self.initialize()

        try:
            # Get pod info first
            if not self.v1:
                raise ServiceError("Kubernetes client not initialized")
                
            pod = await asyncio.get_event_loop().run_in_executor(
                None,
                self.v1.read_namespaced_pod,
                pod_name,
                namespace
            )

            logs = {
                "stdout": "",
                "stderr": ""
            }

            # Extract logs from all containers if not specified
            containers = []
            if container:
                containers = [container]
            else:
                # Get all container names
                if pod.spec.containers:
                    containers = [c.name for c in pod.spec.containers]

                # Also check init containers
                if pod.spec.init_containers:
                    for c in pod.spec.init_containers:
                        containers.append(f"init-{c.name}")

            # Extract logs from each container
            for container_name in containers:
                try:
                    # Check if this is an init container
                    is_init = container_name.startswith("init-")
                    actual_container = container_name[5:] if is_init else container_name

                    # Get logs
                    log_kwargs = {
                        "name": pod_name,
                        "namespace": namespace,
                        "container": actual_container,
                        "previous": previous,
                        "_preload_content": False,
                        "follow": False,
                    }

                    if tail_lines:
                        log_kwargs["tail_lines"] = tail_lines
                    if since_seconds:
                        log_kwargs["since_seconds"] = since_seconds

                    # Run in executor to avoid blocking
                    if not self.v1:
                        raise ServiceError("Kubernetes client not initialized")
                        
                    response = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            partial(self.v1.read_namespaced_pod_log, **log_kwargs)
                        ),
                        timeout=timeout
                    )

                    # Read response with size limit
                    container_logs = self._read_response_with_limit(response, max_size)

                    # Try to parse JSON output from executor container
                    if container_name == "executor" and container_logs:
                        parsed_logs = self._parse_executor_output(container_logs)
                        if parsed_logs:
                            # Successfully parsed JSON output
                            logs["stdout"] = parsed_logs.get("stdout", "")
                            logs["stderr"] = parsed_logs.get("stderr", "")
                        else:
                            # Fallback to raw logs
                            if logs["stdout"]:
                                logs["stdout"] += f"\n\n=== Container: {container_name} ===\n"
                            logs["stdout"] += container_logs
                    else:
                        # Append to stdout for non-executor containers
                        if container_logs:
                            if logs["stdout"]:
                                logs["stdout"] += f"\n\n=== Container: {container_name} ===\n"
                            logs["stdout"] += container_logs

                except ApiException as e:
                    if e.status == 404:
                        logger.warning(f"Container {container_name} not found in pod {pod_name}")
                    else:
                        logger.error(f"Failed to get logs for container {container_name}: {e}")
                        logs["stderr"] += f"\nError getting logs for {container_name}: {e.reason}\n"
                except asyncio.TimeoutError:
                    logger.error(f"Timeout getting logs for container {container_name}")
                    logs["stderr"] += f"\nTimeout getting logs for {container_name}\n"
                except Exception as e:
                    logger.error(f"Error getting logs for container {container_name}: {e}")
                    logs["stderr"] += f"\nError getting logs for {container_name}: {str(e)}\n"

            # Check pod status for errors
            if pod.status:
                # Check container statuses
                if pod.status.container_statuses:
                    for status in pod.status.container_statuses:
                        if status.state and status.state.terminated:
                            term = status.state.terminated
                            if term.message:
                                logs["stderr"] += f"\nContainer {status.name} terminated: {term.message}\n"
                            if term.reason and term.reason != "Completed":
                                logs["stderr"] += f"Reason: {term.reason}\n"

                # Check pod conditions
                if pod.status.conditions:
                    for condition in pod.status.conditions:
                        if condition.type == "ContainersReady" and condition.status != "True":
                            if condition.message:
                                logs["stderr"] += f"\nPod condition: {condition.message}\n"

                # Pod message
                if pod.status.message:
                    logs["stderr"] += f"\nPod message: {pod.status.message}\n"

            return logs

        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Pod {pod_name} not found")
                return {
                    "stdout": "",
                    "stderr": f"Pod {pod_name} not found in namespace {namespace}"
                }
            else:
                logger.error(f"Kubernetes API error: {e}")
                raise ServiceError(f"Failed to extract logs: {e.reason}") from e
        except Exception as e:
            logger.error(f"Failed to extract logs: {e}")
            raise ServiceError(f"Log extraction failed: {e}") from e

    def _read_response_with_limit(self, response: Any, max_size: int) -> str:
        """Read response with size limit"""
        try:
            content = b""
            chunk_size = 8192

            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break

                if len(content) + len(chunk) > max_size:
                    # Truncate to max size
                    remaining = max_size - len(content)
                    content += chunk[:remaining]
                    content += b"\n... [truncated due to size limit] ..."
                    break

                content += chunk

            return content.decode('utf-8', errors='replace')

        finally:
            response.release_conn()

    def _parse_executor_output(self, logs: str) -> Optional[Dict[str, str]]:
        """Parse JSON output from executor container"""
        try:
            import json

            # First try to parse the entire output as JSON
            try:
                result_data = json.loads(logs.strip())
                if "stdout" in result_data and "stderr" in result_data:
                    return {"stdout": result_data["stdout"], "stderr": result_data["stderr"]}
            except json.JSONDecodeError:
                pass

            # If that fails, try to find JSON block in the output
            # This handles cases where there's extra debug output
            lines = logs.strip().split('\n')
            json_start = -1
            json_end = -1

            # Find the JSON block (looking for opening and closing braces)
            for i, line in enumerate(lines):
                if line.strip().startswith('{') and json_start == -1:
                    json_start = i
                if line.strip().endswith('}') and json_start >= 0:
                    json_end = i + 1
                    # Try to parse what we found
                    json_text = '\n'.join(lines[json_start:json_end])
                    try:
                        result_data = json.loads(json_text)
                        # Verify it has the expected structure
                        if "stdout" in result_data and "stderr" in result_data:
                            logger.debug("Successfully extracted executor JSON output")
                            return {"stdout": result_data["stdout"], "stderr": result_data["stderr"]}
                    except json.JSONDecodeError:
                        # This wasn't valid JSON, keep looking
                        json_start = -1
                        continue

            logger.debug("Could not parse executor output as JSON")
            return None

        except Exception as e:
            logger.debug(f"Error parsing executor output: {e}")
            return None

    async def get_pod_logs_stream(
        self,
        pod_name: str,
        namespace: str = "default",
        container: Optional[str] = None,
        follow: bool = True,
    ) -> AsyncGenerator[str, None]:
        """
        Stream logs from a pod in real-time
        
        Yields log lines as they become available
        """
        await self.initialize()

        try:
            # Set up streaming request
            kwargs = {
                "name": pod_name,
                "namespace": namespace,
                "follow": follow,
                "_preload_content": False,
                "stream": True,
            }

            if container:
                kwargs["container"] = container

            # Create stream
            if not self.v1:
                raise ServiceError("Kubernetes client not initialized")
            
            # Store reference to avoid mypy error in lambda
            v1_api = self.v1
            stream = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: v1_api.read_namespaced_pod_log(**kwargs)
            )

            try:
                # Stream logs
                for line in stream:
                    if line:
                        yield line.decode('utf-8', errors='replace').rstrip()
            finally:
                stream.release_conn()

        except Exception as e:
            logger.error(f"Failed to stream logs: {e}")
            raise ServiceError(f"Log streaming failed: {e}") from e
