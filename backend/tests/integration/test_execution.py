import pytest
from fastapi.testclient import TestClient


def test_execute_script(test_app: TestClient, test_db):
    # Register a new user
    register_response = test_app.post(
        "/api/v1/register",
        json={
            "username": "testuser_exec",
            "email": "testuser_exec@example.com",
            "password": "testpass"
        }
    )
    assert register_response.status_code == 200, register_response.text

    # Login to get auth headers
    login_response = test_app.post(
        "/api/v1/login",
        data={
            "username": "testuser_exec",
            "password": "testpass"
        }
    )
    assert login_response.status_code == 200, login_response.text
    token = login_response.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Execute a script
    script = "print('Hello, World!')"
    execute_response = test_app.post(
        "/api/v1/execute",
        json={"script": script},
        headers=auth_headers
    )
    assert execute_response.status_code == 200, execute_response.text
    assert "execution_id" in execute_response.json()

    execution_id = execute_response.json()["execution_id"]

    # Retrieve execution result
    result_response = test_app.get(
        f"/api/v1/result/{execution_id}",
        headers=auth_headers
    )
    assert result_response.status_code == 200, result_response.text
    assert result_response.json()["status"] in ["queued", "running", "completed"]
