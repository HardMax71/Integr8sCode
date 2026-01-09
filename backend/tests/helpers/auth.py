from typing import TypedDict

from httpx import AsyncClient


class AuthResult(TypedDict):
    """Result of a login operation with CSRF token."""

    csrf_token: str
    headers: dict[str, str]


async def login_user(client: AsyncClient, username: str, password: str) -> AuthResult:
    """Login a user and return CSRF token and headers for subsequent requests.

    Use this helper when tests need to switch users or re-authenticate.
    The returned headers dict should be passed to POST/PUT/DELETE requests.

    Args:
        client: The httpx AsyncClient
        username: Username to login with
        password: Password for the user

    Returns:
        AuthResult with csrf_token and headers dict containing X-CSRF-Token

    Raises:
        AssertionError: If login fails
    """
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200, f"Login failed: {response.text}"

    json_data: dict[str, str] = response.json()
    csrf_token = json_data.get("csrf_token", "")

    return AuthResult(
        csrf_token=csrf_token,
        headers={"X-CSRF-Token": csrf_token},
    )
