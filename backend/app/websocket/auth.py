import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import WebSocket
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import Settings, get_settings
from app.core.exceptions import AuthenticationError
from app.core.logging import logger
from app.schemas_pydantic.user import UserRole


class WebSocketAuth:
    """Simplified WebSocket authentication handler."""

    def __init__(self, database: AsyncIOMotorDatabase | None = None, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.database = database
        self._auth_timeout = 5.0  # seconds
        self._ws_token_lifetime = timedelta(minutes=15)

    async def _get_token(self, websocket: WebSocket, provided_token: str | None = None) -> str:
        """Extract token from various sources with simplified logic."""
        # Return provided token if available
        if provided_token:
            return provided_token

        # Check query parameters
        if token := websocket.query_params.get("token"):
            return token

        # Get token from first message
        await websocket.accept()

        try:
            auth_message = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=self._auth_timeout
            )
        except asyncio.TimeoutError as e:
            await self._send_error(websocket, "AUTH_TIMEOUT", "Authentication timeout")
            raise AuthenticationError("Authentication timeout") from e

        # Use match statement for cleaner pattern matching
        match auth_message:
            case {"type": "auth", "token": str(token)} if token:
                return token
            case _:
                await self._send_error(websocket, "AUTH_REQUIRED", "Authentication required")
                raise AuthenticationError("No authentication token provided")

    async def _send_error(self, websocket: WebSocket, code: str, message: str) -> None:
        """Send error message and close connection."""
        with suppress(Exception):
            await websocket.send_json({
                "type": "error",
                "code": code,
                "error": message
            })
            await websocket.close(code=4001, reason=message)

    def _decode_token(self, token: str) -> dict[str, Any]:
        """Decode and validate JWT token with proper exception handling."""
        try:
            decoded: dict[str, Any] = jwt.decode(
                token,
                self.settings.SECRET_KEY,
                algorithms=[self.settings.ALGORITHM],
                options={"verify_exp": True}
            )
            return decoded
        except ExpiredSignatureError as e:
            raise AuthenticationError("Token expired") from e
        except InvalidTokenError as e:
            raise AuthenticationError(f"Invalid token: {e}") from e

    async def authenticate_websocket(
            self,
            websocket: WebSocket,
            token: str | None = None,
    ) -> dict[str, Any]:
        """
        Authenticate WebSocket connection with simplified flow.

        Returns user info dict if authenticated, raises AuthenticationError otherwise.
        """
        # Get token from available sources
        token = await self._get_token(websocket, token)

        # Decode and validate token
        payload = self._decode_token(token)

        # Extract user info
        user_id = payload.get("sub", "")
        if not user_id:
            raise AuthenticationError("Invalid user ID in token")

        user_info = {
            "user_id": user_id,
            "email": payload.get("email"),
            "roles": payload.get("roles", []),
            "authenticated_at": datetime.now(timezone.utc).isoformat(),
            # Include additional fields that might be expected
            "sub": user_id,  # For backward compatibility
            "exp": payload.get("exp"),
            "username": payload.get("username"),
            "role": payload.get("role"),
        }

        logger.info(
            "WebSocket authenticated",
            extra={"user_id": user_id, "email": user_info["email"]}
        )

        return user_info

    async def validate_subscription_request(
            self,
            websocket: WebSocket,
            user_info: dict[str, Any],
            execution_id: str,
    ) -> bool:
        """
        Validate execution subscription request against database.

        Returns True if user owns the execution or is admin.
        """
        if self.database is None:
            logger.warning("No database available for execution validation")
            return False

        user_id = user_info.get("user_id") or user_info.get("sub")
        if not user_id:
            return False

        try:
            # Get execution and check ownership
            if not (execution := await self.database.executions.find_one({"execution_id": execution_id})):
                logger.warning(f"Execution {execution_id} not found")
                return False

            # Fast path: check if user owns the execution
            if execution.get("user_id") == user_id:
                return True

            # Check admin role - first from token, then from database
            roles = user_info.get("roles", [])
            # Since UserRole is StrEnum, it IS the string value
            is_admin = UserRole.ADMIN in roles

            if not is_admin and self.database is not None:
                if user := await self.database.users.find_one({"user_id": user_id}):
                    is_admin_user: bool = user.get("role") == UserRole.ADMIN
                    return is_admin_user

            return is_admin

        except Exception as e:
            logger.error(f"Error validating execution subscription: {e}")
            return False

    def create_connection_token(
            self,
            user_id: str,
            expires_delta: timedelta | None = None,
    ) -> str:
        """
        Create a short-lived token for WebSocket connection.
        """
        now = datetime.now(timezone.utc)
        expires_delta = expires_delta or self._ws_token_lifetime

        payload = {
            "sub": user_id,
            "exp": now + expires_delta,
            "type": "websocket",
            "iat": now,
        }

        return jwt.encode(
            payload,
            self.settings.SECRET_KEY,
            algorithm=self.settings.ALGORITHM
        )
