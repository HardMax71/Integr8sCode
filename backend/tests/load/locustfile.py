import random
from typing import Optional

from locust import HttpUser, task, between


class IntegrationTestUser(HttpUser):
    # Wait between 1 and 3 seconds between tasks
    wait_time = between(1, 3)
    token: Optional[str] = None
    script_ids = []

    def on_start(self):
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
    def health_check(self):
        """Test the health check endpoint"""
        self.client.get("/api/v1/health")

    @task(3)
    def execute_script(self):
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
            "python_version": random.choice(["3.9", "3.10", "3.11"]),
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
    def get_k8s_limits(self):
        """Test K8S resource limits endpoint"""
        self.client.get("/api/v1/k8s-limits", headers=self.headers)

    @task(2)
    def saved_scripts_workflow(self):
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
    def list_scripts(self):
        """Test listing saved scripts"""
        self.client.get("/api/v1/scripts", headers=self.headers)

    @task(1)
    def cleanup_scripts(self):
        """Clean up created scripts"""
        if self.script_ids:
            script_id = self.script_ids.pop()
            self.client.delete(f"/api/v1/scripts/{script_id}", headers=self.headers)


class ReadOnlyUser(HttpUser):
    """User that only performs read operations"""

    wait_time = between(1, 2)

    @task(4)
    def health_check(self):
        self.client.get("/api/v1/health")

    @task(1)
    def get_k8s_limits(self):
        self.client.get("/api/v1/k8s-limits")
