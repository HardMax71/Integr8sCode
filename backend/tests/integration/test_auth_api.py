import time
import httpx
import pytest
from app.schemas.user import UserCreate
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase
from tests.conftest import create_test_ssl_context


@pytest.mark.integration
class TestAuthAPI:

    @pytest.fixture(autouse=True)
    async def setup(self, client: AsyncClient, db: AsyncIOMotorDatabase) -> None:
        """Setup user and authentication for auth tests."""
        self.client = client
        self.db = db
        self.test_username = f"testuser_auth_{int(time.time() * 1000)}"
        self.test_email = f"{self.test_username}@example.com"
        self.test_password = "testpass123"

        test_user = UserCreate(
            username=self.test_username,
            email=self.test_email,
            password=self.test_password
        )
        # Register
        reg_response = await self.client.post("/api/v1/register", json=test_user.model_dump())
        if reg_response.status_code not in [200, 400]:
            pytest.fail(f"Auth setup: Registration failed: {reg_response.status_code} {reg_response.text}")

        # Login
        login_response = await self.client.post(
            "/api/v1/login",
            data={"username": self.test_username, "password": self.test_password},
        )
        if login_response.status_code != 200:
            pytest.fail(f"Auth setup: Login failed: {login_response.status_code} {login_response.text}")

        login_data = login_response.json()
        assert "csrf_token" in login_data
        assert "message" in login_data
        self.csrf_token = login_data["csrf_token"]
        self.headers = {"X-CSRF-Token": self.csrf_token}

    @pytest.mark.asyncio
    async def test_login_success(self) -> None:
        """Test successful login (implicitly tested in setup, but explicit check)."""
        login_response = await self.client.post(
            "/api/v1/login",
            data={"username": self.test_username, "password": self.test_password},
        )
        assert login_response.status_code == 200
        data = login_response.json()
        assert "csrf_token" in data
        assert "message" in data
        assert data["message"] == "Login successful"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self) -> None:
        """Test login with incorrect password."""
        login_response = await self.client.post(
            "/api/v1/login",
            data={"username": self.test_username, "password": "wrongpassword"},
        )
        assert login_response.status_code == 401
        assert "Invalid credentials" in login_response.text

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self) -> None:
        """Test login with a username that does not exist."""
        login_response = await self.client.post(
            "/api/v1/login",
            data={"username": "nonexistentuser123", "password": "somepassword"},
        )
        assert login_response.status_code == 401
        assert "Invalid credentials" in login_response.text

    @pytest.mark.asyncio
    async def test_register_success(self) -> None:
        """Test successful user registration."""
        # Use different user details for this specific test
        reg_username = f"testuser_reg_success_{int(time.time() * 1000)}"
        reg_email = f"{reg_username}@example.com"
        reg_password = "register_pass"
        new_user = UserCreate(username=reg_username, email=reg_email, password=reg_password)

        response = await self.client.post("/api/v1/register", json=new_user.model_dump())
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == reg_username
        assert data["email"] == reg_email
        assert "id" in data
        assert "hashed_password" not in data  # Ensure password isn't returned

    @pytest.mark.asyncio
    async def test_register_duplicate_user(self) -> None:
        """Verify registering a duplicate username fails (uses user from setup)."""
        duplicate_user = UserCreate(
            username=self.test_username,  # Username from setup
            email="duplicate@example.com",
            password=self.test_password
        )
        response = await self.client.post("/api/v1/register", json=duplicate_user.model_dump())
        assert response.status_code == 400
        assert "Username already registered" in response.text

    @pytest.mark.asyncio
    async def test_verify_token_valid(self) -> None:
        """Verify a valid token (using token from setup)."""
        response = await self.client.get("/api/v1/verify-token")
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] == True
        assert data["username"] == self.test_username
        assert "csrf_token" in data

    @pytest.mark.asyncio
    async def test_verify_token_invalid_token(self) -> None:
        """Verify an invalid/malformed token fails."""
        async with httpx.AsyncClient(
            base_url="https://localhost:443",
            verify=create_test_ssl_context(),
            timeout=30.0
        ) as new_client:
            response = await new_client.get("/api/v1/verify-token")
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_verify_token_no_token(self) -> None:
        """Verify request fails without token."""
        async with httpx.AsyncClient(
            base_url="https://localhost:443",
            verify=create_test_ssl_context(),
            timeout=30.0
        ) as new_client:
            response = await new_client.get("/api/v1/verify-token")
            assert response.status_code == 401
