import json
import random
import time
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin

import requests
from locust import HttpUser, between, task, events
from locust.exception import RescheduleTask


class IntegrationTestUser(HttpUser):
    # Wait between 1 and 3 seconds between tasks
    wait_time = between(1, 3)
    token: Optional[str] = None
    script_ids: List[str] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Disable SSL verification for self-signed certificates
        self.client.verify = False

    def on_start(self) -> None:
        """Login and get token before starting tasks"""
        # Register a unique user
        username = f"loadtest_user_{random.randint(1000, 9999)}"
        register_data = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "loadtest123",
        }
        self.client.post("/api/v1/register", json=register_data)

        # Login to get token
        login_response = self.client.post(
            "/api/v1/login", data={"username": username, "password": "loadtest123"}
        )
        self.token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task(1)
    def health_check(self) -> None:
        """Test the health check endpoint"""
        self.client.get("/api/v1/health")

    @task(3)
    def execute_script(self) -> None:
        """Test script execution"""
        script = random.choice(
            [
                "print('Hello, World!')",
                "print(sum(range(10)))",
                "print('Load test script')",
                "for i in range(3): print(i)",
            ]
        )

        execution_data = {
            "script": script,
            "lang": "python",
            "lang_version": random.choice(["3.9", "3.10", "3.11"]),
        }

        # Execute script
        response = self.client.post(
            "/api/v1/execute", json=execution_data, headers=self.headers
        )

        if response.status_code == 200:
            execution_id = response.json()["execution_id"]
            # Get result
            self.client.get(f"/api/v1/result/{execution_id}", headers=self.headers)

    @task(2)
    def get_k8s_limits(self) -> None:
        """Test K8S resource limits endpoint"""
        self.client.get("/api/v1/k8s-limits", headers=self.headers)

    @task(2)
    def saved_scripts_workflow(self) -> None:
        """Test saved scripts endpoints"""
        # Create script
        script_data = {
            "name": f"Load Test Script {random.randint(1, 1000)}",
            "script": f"print('Load test {random.randint(1, 1000)}')",
            "description": "Created during load test",
        }

        response = self.client.post(
            "/api/v1/scripts", json=script_data, headers=self.headers
        )

        if response.status_code == 200:
            script_id = response.json()["id"]
            self.script_ids.append(script_id)

            # Get script
            self.client.get(f"/api/v1/scripts/{script_id}", headers=self.headers)

            # Update script
            update_data = {
                "name": f"Updated Script {random.randint(1, 1000)}",
                "script": "print('Updated during load test')",
                "description": "Updated during load test",
            }
            self.client.put(
                f"/api/v1/scripts/{script_id}", json=update_data, headers=self.headers
            )

    @task(1)
    def list_scripts(self) -> None:
        """Test listing saved scripts"""
        self.client.get("/api/v1/scripts", headers=self.headers)

    @task(1)
    def cleanup_scripts(self) -> None:
        """Clean up created scripts"""
        if self.script_ids:
            script_id = self.script_ids.pop()
            self.client.delete(f"/api/v1/scripts/{script_id}", headers=self.headers)


class ReadOnlyUser(HttpUser):
    """User that only performs read operations"""

    wait_time = between(1, 2)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Disable SSL verification for self-signed certificates
        self.client.verify = False

    @task(4)
    def health_check(self) -> None:
        self.client.get("/api/v1/health")

    @task(1)
    def get_k8s_limits(self) -> None:
        self.client.get("/api/v1/k8s-limits")


class EventStreamUser(HttpUser):
    """User that tests Server-Sent Events (SSE) connections"""

    wait_time = between(5, 10)
    token: Optional[str] = None
    execution_ids: List[str] = []

    active_streams: Dict[str, Any] = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Disable SSL verification for self-signed certificates
        self.client.verify = False

    def on_start(self) -> None:
        """Login and get token before starting tasks"""
        # Register and login
        username = f"sse_user_{random.randint(1000, 9999)}"
        register_data = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "ssetest123",
        }
        self.client.post("/api/v1/register", json=register_data)

        login_response = self.client.post(
            "/api/v1/login", data={"username": username, "password": "ssetest123"}
        )
        self.token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task(3)
    def execute_and_stream(self) -> None:
        """Execute script and stream results via SSE"""
        script = random.choice([
            "import time\nfor i in range(5):\n    print(f'Progress: {i+1}/5')\n    time.sleep(1)",
            "print('Starting...')\nfor i in range(10):\n    print(i)\nprint('Done!')",
            "import random\nprint([random.randint(1, 100) for _ in range(5)])",
        ])

        # Execute script
        execution_data = {
            "script": script,
            "lang": "python",
            "lang_version": "3.11",
        }

        with self.client.post(
                "/api/v1/execute",
                json=execution_data,
                headers=self.headers,
                catch_response=True
        ) as response:
            if response.status_code == 200:
                execution_id = response.json()["execution_id"]
                self.execution_ids.append(execution_id)
                response.success()

                # Start SSE connection
                self._connect_sse(execution_id)
            else:
                response.failure(f"Failed to execute: {response.status_code}")

    @task(1)
    def connect_to_existing_execution(self) -> None:
        """Connect to an existing execution's event stream"""
        if self.execution_ids:
            execution_id = random.choice(self.execution_ids)
            self._connect_sse(execution_id)

    def _connect_sse(self, execution_id: str) -> None:
        """Connect to SSE endpoint and measure connection time"""
        start_time = time.time()

        # Create SSE URL
        sse_url = urljoin(self.client.base_url, f"/api/v1/events/executions/{execution_id}")

        # Track as custom request
        request_name = "/api/v1/events/executions/{execution_id}"
        request_type = "SSE"

        try:
            # Use requests library for SSE (locust's client doesn't handle streaming well)
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache"
            }

            response = requests.get(
                sse_url,
                headers=headers,
                stream=True,
                timeout=30,
                verify=False  # For self-signed certs in test env
            )

            if response.status_code == 200:
                connection_time = time.time() - start_time
                events.request.fire(
                    request_type=request_type,
                    name=request_name,
                    response_time=connection_time * 1000,  # Convert to ms
                    response_length=0,
                    exception=None,
                    context={}
                )

                # Process stream for a bit
                self._process_sse_stream(response, execution_id, request_name, request_type)
            else:
                events.request.fire(
                    request_type=request_type,
                    name=request_name,
                    response_time=(time.time() - start_time) * 1000,
                    response_length=0,
                    exception=Exception(f"SSE connection failed: {response.status_code}"),
                    context={}
                )
        except Exception as e:
            events.request.fire(
                request_type=request_type,
                name=request_name,
                response_time=(time.time() - start_time) * 1000,
                response_length=0,
                exception=e,
                context={}
            )

    def _process_sse_stream(self, response, execution_id: str, request_name: str, request_type: str) -> None:
        """Process SSE stream and track events"""
        events_received = 0
        start_time = time.time()
        max_duration = random.uniform(5, 15)  # Stream for 5-15 seconds

        try:
            for line in response.iter_lines():
                if time.time() - start_time > max_duration:
                    break

                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        events_received += 1

                        # Parse event data
                        try:
                            event_data = json.loads(line[6:])
                            event_type = event_data.get('event_type', 'unknown')

                            # Track different event types
                            events.request.fire(
                                request_type="SSE_EVENT",
                                name=f"/events/{event_type}",
                                response_time=1,  # Event processing is fast
                                response_length=len(line),
                                exception=None,
                                context={"execution_id": execution_id}
                            )

                            # If execution completed, close stream
                            if event_type in ['complete', 'error']:
                                break
                        except json.JSONDecodeError:
                            pass

                # Small delay to not overwhelm
                gevent.sleep(0.01)

            # Track stream duration
            stream_duration = time.time() - start_time
            events.request.fire(
                request_type="SSE_STREAM",
                name=f"{request_name}_duration",
                response_time=stream_duration * 1000,
                response_length=events_received,
                exception=None,
                context={"events_count": events_received}
            )

        finally:
            response.close()

    @task(1)
    def test_sse_reconnection(self) -> None:
        """Test SSE reconnection behavior"""
        if not self.execution_ids:
            return

        execution_id = random.choice(self.execution_ids)

        # Connect, disconnect quickly, then reconnect
        for attempt in range(2):
            sse_url = urljoin(self.client.base_url, f"/api/v1/events/executions/{execution_id}")
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Accept": "text/event-stream",
            }

            start_time = time.time()
            try:
                response = requests.get(
                    sse_url,
                    headers=headers,
                    stream=True,
                    timeout=5,
                    verify=False
                )

                if response.status_code == 200:
                    # Read a few events then close
                    for i, line in enumerate(response.iter_lines()):
                        if i > 5:  # Read only 5 lines
                            break
                        gevent.sleep(0.1)

                    response.close()

                    events.request.fire(
                        request_type="SSE_RECONNECT",
                        name=f"/api/v1/events/reconnect_test",
                        response_time=(time.time() - start_time) * 1000,
                        response_length=0,
                        exception=None,
                        context={"attempt": attempt + 1}
                    )

                    # Wait before reconnecting
                    if attempt == 0:
                        gevent.sleep(random.uniform(1, 3))

            except Exception as e:
                events.request.fire(
                    request_type="SSE_RECONNECT",
                    name=f"/api/v1/events/reconnect_test",
                    response_time=(time.time() - start_time) * 1000,
                    response_length=0,
                    exception=e,
                    context={"attempt": attempt + 1}
                )


class ConcurrentEventStreamUser(HttpUser):
    """User that maintains multiple concurrent SSE connections"""

    wait_time = between(10, 20)
    token: Optional[str] = None
    max_concurrent_streams = 3

    active_streams: List[Any] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Disable SSL verification for self-signed certificates
        self.client.verify = False

    def on_start(self) -> None:
        """Login and setup"""
        username = f"concurrent_sse_{random.randint(1000, 9999)}"
        register_data = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "concurrent123",
        }
        self.client.post("/api/v1/register", json=register_data)

        login_response = self.client.post(
            "/api/v1/login", data={"username": username, "password": "concurrent123"}
        )
        self.token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task
    def maintain_concurrent_streams(self) -> None:
        """Execute multiple scripts and maintain concurrent SSE connections"""
        # Execute multiple scripts
        execution_ids = []
        for i in range(self.max_concurrent_streams):
            execution_data = {
                "script": f"import time\nfor i in range(10):\n    print(f'Stream {i + 1}: {{i}}')\n    time.sleep(1)",
                "lang": "python",
                "lang_version": "3.11",
            }

            response = self.client.post(
                "/api/v1/execute",
                json=execution_data,
                headers=self.headers
            )

            if response.status_code == 200:
                execution_ids.append(response.json()["execution_id"])

        if not execution_ids:
            return

        # Create concurrent SSE connections
        start_time = time.time()
        streams = []

        for exec_id in execution_ids:
            sse_url = urljoin(self.client.base_url, f"/api/v1/events/executions/{exec_id}")
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Accept": "text/event-stream",
            }

            try:
                response = requests.get(
                    sse_url,
                    headers=headers,
                    stream=True,
                    timeout=30,
                    verify=False
                )

                if response.status_code == 200:
                    streams.append(response)
            except Exception:
                pass

        # Track concurrent connections
        events.request.fire(
            request_type="SSE_CONCURRENT",
            name=f"/concurrent_streams_x{len(streams)}",
            response_time=(time.time() - start_time) * 1000,
            response_length=len(streams),
            exception=None,
            context={"stream_count": len(streams)}
        )

        # Process all streams for a while
        duration = random.uniform(10, 20)
        end_time = time.time() + duration
        total_events = 0

        while time.time() < end_time and streams:
            for stream in streams[:]:  # Copy list to safely remove
                try:
                    # Non-blocking read from each stream
                    line = next(stream.iter_lines(decode_unicode=True), None)
                    if line and line.startswith('data: '):
                        total_events += 1
                except (StopIteration, Exception):
                    stream.close()
                    streams.remove(stream)

            gevent.sleep(0.1)

        # Close remaining streams
        for stream in streams:
            stream.close()

        # Report metrics
        events.request.fire(
            request_type="SSE_CONCURRENT",
            name="/concurrent_streams_total_events",
            response_time=duration * 1000,
            response_length=total_events,
            exception=None,
            context={"total_events": total_events, "duration": duration}
        )


class EventProducerUser(HttpUser):
    """User that generates high volume of events to test event processing"""

    wait_time = between(0.1, 0.5)  # Very aggressive
    token: Optional[str] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Disable SSL verification for self-signed certificates
        self.client.verify = False

    def on_start(self) -> None:
        """Login and setup"""
        username = f"event_producer_{random.randint(1000, 9999)}"
        register_data = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "producer123",
        }
        self.client.post("/api/v1/register", json=register_data)

        login_response = self.client.post(
            "/api/v1/login", data={"username": username, "password": "producer123"}
        )
        self.token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task(10)
    def rapid_fire_executions(self) -> None:
        """Execute many small scripts rapidly"""
        scripts = [
            "print('Quick test')",
            "print(2 + 2)",
            "print([i for i in range(5)])",
            "import time; print(time.time())",
            "print({'test': True})",
        ]

        execution_data = {
            "script": random.choice(scripts),
            "lang": "python",
            "lang_version": "3.11",
        }

        self.client.post(
            "/api/v1/execute",
            json=execution_data,
            headers=self.headers,
            name="/api/v1/execute_rapid"
        )

    @task(1)
    def batch_executions(self) -> None:
        """Execute multiple scripts in quick succession"""
        batch_size = random.randint(5, 10)

        for i in range(batch_size):
            execution_data = {
                "script": f"print('Batch item {i + 1}/{batch_size}')",
                "lang": "python",
                "lang_version": "3.11",
            }

            self.client.post(
                "/api/v1/execute",
                json=execution_data,
                headers=self.headers,
                name="/api/v1/execute_batch"
            )

            # Very short delay between batch items
            gevent.sleep(0.05)
