import pytest
from fastapi.testclient import TestClient


def test_register_and_login(test_app: TestClient):
    # Register a new user
    register_response = test_app.post(
        "/api/v1/register",
        json={
            "username": "testuser",
            "email": "testuser@example.com",
            "password": "testpass"
        }
    )
    assert register_response.status_code == 200, register_response.text
    assert "id" in register_response.json()

    # Login with the new user
    login_response = test_app.post(
        "/api/v1/login",
        data={
            "username": "testuser",
            "password": "testpass"
        }
    )
    assert login_response.status_code == 200, login_response.text
    assert "access_token" in login_response.json()

    # Verify token
    token = login_response.json()["access_token"]
    verify_response = test_app.get(
        "/api/v1/verify-token",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert verify_response.status_code == 200, verify_response.text
    assert verify_response.json()["valid"] == True
    assert verify_response.json()["username"] == "testuser"