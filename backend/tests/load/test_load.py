import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app


@pytest.mark.asyncio
async def test_load(test_settings):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Register a test user
        register_response = await ac.post(
            "/api/v1/register",
            json={
                "username": "loadtestuser",
                "email": "loadtestuser@example.com",
                "password": "testpass"
            }
        )
        assert register_response.status_code == 200, register_response.text

        # Login to get auth token
        login_response = await ac.post(
            "/api/v1/login",
            data={
                "username": "loadtestuser",
                "password": "testpass"
            }
        )
        assert login_response.status_code == 200, login_response.text
        token = login_response.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        async def execute_script():
            script = "print('Hello, World!')"
            response = await ac.post(
                "/api/v1/execute",
                json={"script": script},
                headers=auth_headers
            )
            assert response.status_code == 200, response.text

        # Simulate 100 concurrent users
        tasks = [asyncio.create_task(execute_script()) for _ in range(100)]
        await asyncio.gather(*tasks)
