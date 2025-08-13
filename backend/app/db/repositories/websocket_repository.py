import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import WebSocket

from app.core.logging import logger
from app.db.mongodb import DatabaseManager
from app.db.repositories.execution_repository import ExecutionRepository
from app.schemas_pydantic.websocket import (
    AuthMessage,
    ErrorMessage,
    ExecutionStatusData,
    ExecutionStatusMessage,
    SubscribedMessage,
    SubscriptionsMessage,
    UnsubscribedMessage,
    WebSocketAuthResponse,
    WebSocketErrorCode,
    WebSocketMessageType,
)
from app.websocket.auth import WebSocketAuth
from app.websocket.connection_manager import ConnectionManager, WebSocketConnection


class WebSocketRepository:
    def __init__(
            self,
            db_manager: DatabaseManager,
            connection_manager: ConnectionManager,
            websocket_auth: WebSocketAuth,
            execution_repository: ExecutionRepository
    ):
        self.db_manager = db_manager
        self.connection_manager = connection_manager
        self.websocket_auth = websocket_auth
        self.execution_repository = execution_repository

    async def authenticate_connection(
            self,
            websocket: WebSocket,
            token: Optional[str]
    ) -> WebSocketAuthResponse:
        try:
            user_info = await self.websocket_auth.authenticate_websocket(websocket, token)
            
            # Validate required fields
            user_id = user_info.get("user_id")
            username = user_info.get("username")
            role = user_info.get("role")
            
            if not user_id or not username or not role:
                raise ValueError("Missing required authentication fields")
            
            return WebSocketAuthResponse(
                user_id=user_id,
                username=username,
                role=role,
                token_exp=user_info.get("exp")
            )
        except Exception as e:
            logger.error(f"WebSocket authentication failed: {e}")
            raise

    async def create_connection(
            self,
            websocket: WebSocket,
            client_id: Optional[str],
            user_id: str
    ) -> WebSocketConnection:
        return await self.connection_manager.connect(
            websocket=websocket,
            client_id=client_id,
            user_id=user_id
        )

    async def send_auth_success(
            self,
            connection: WebSocketConnection,
            user_id: str
    ) -> None:
        message = AuthMessage(
            status="success",
            user_id=user_id,
            client_id=connection.client_id
        )
        await connection.send_json(message.model_dump())

    async def send_error(
            self,
            connection: WebSocketConnection,
            error: str,
            code: WebSocketErrorCode,
            execution_id: Optional[str] = None
    ) -> None:
        message = ErrorMessage(
            error=error,
            code=code,
            execution_id=execution_id
        )
        await connection.send_json(message.model_dump())

    async def handle_ping(self, client_id: str) -> None:
        await self.connection_manager.handle_ping(client_id)

    async def handle_subscribe(
            self,
            connection: WebSocketConnection,
            execution_id: str,
            user_info: Dict[str, Any]
    ) -> bool:
        # Validate subscription request
        can_subscribe = await self.websocket_auth.validate_subscription_request(
            connection.websocket,
            user_info,
            execution_id
        )

        if not can_subscribe:
            await self.send_error(
                connection,
                "Not authorized to subscribe to this execution",
                WebSocketErrorCode.UNAUTHORIZED,
                execution_id
            )
            return False

        # Subscribe to execution
        success = await self.connection_manager.subscribe(
            connection.client_id,
            execution_id
        )

        if success:
            message = SubscribedMessage(
                execution_id=execution_id,
                timestamp=datetime.now(timezone.utc)
            )
            await connection.send_json(message.model_dump())

            # Send current execution status
            await self.send_current_execution_status(connection, execution_id)
        else:
            await self.send_error(
                connection,
                "Subscription failed",
                WebSocketErrorCode.SUBSCRIPTION_FAILED,
                execution_id
            )

        return success

    async def handle_unsubscribe(
            self,
            connection: WebSocketConnection,
            execution_id: str
    ) -> bool:
        success = await self.connection_manager.unsubscribe(
            connection.client_id,
            execution_id
        )

        if success:
            message = UnsubscribedMessage(
                execution_id=execution_id,
                timestamp=datetime.now(timezone.utc)
            )
            await connection.send_json(message.model_dump())

        return success

    async def handle_list_subscriptions(
            self,
            connection: WebSocketConnection
    ) -> None:
        message = SubscriptionsMessage(
            subscriptions=list(connection.subscriptions),
            timestamp=datetime.now(timezone.utc)
        )
        await connection.send_json(message.model_dump())

    async def send_current_execution_status(
            self,
            connection: WebSocketConnection,
            execution_id: str
    ) -> None:
        try:
            execution = await self.execution_repository.get_execution(execution_id)

            if execution:
                status_data = ExecutionStatusData(
                    execution_id=execution_id,
                    status=execution.status,
                    created_at=execution.created_at.isoformat(),
                    lang=execution.lang,
                    lang_version=execution.lang_version,
                    has_output=bool(execution.output),
                    has_errors=bool(execution.errors)
                )

                message = ExecutionStatusMessage(
                    timestamp=datetime.now(timezone.utc),
                    data=status_data
                )

                await connection.send_json(message.model_dump())
        except Exception as e:
            logger.error(f"Error sending execution status: {e}")

    async def process_message(
            self,
            connection: WebSocketConnection,
            message: Dict[str, Any],
            user_info: Dict[str, Any]
    ) -> None:
        """Process incoming WebSocket message.
        
        Args:
            connection: WebSocket connection
            message: Message data
            user_info: User information
        """
        msg_type = message.get("type")

        if msg_type == WebSocketMessageType.PING:
            await self.handle_ping(connection.client_id)

        elif msg_type == WebSocketMessageType.SUBSCRIBE:
            execution_id = message.get("execution_id")
            if not execution_id:
                await self.send_error(
                    connection,
                    "Missing execution_id",
                    WebSocketErrorCode.MISSING_EXECUTION_ID
                )
                return

            await self.handle_subscribe(connection, execution_id, user_info)

        elif msg_type == WebSocketMessageType.UNSUBSCRIBE:
            execution_id = message.get("execution_id")
            if not execution_id:
                await self.send_error(
                    connection,
                    "Missing execution_id",
                    WebSocketErrorCode.MISSING_EXECUTION_ID
                )
                return

            await self.handle_unsubscribe(connection, execution_id)

        elif msg_type == WebSocketMessageType.LIST_SUBSCRIPTIONS:
            await self.handle_list_subscriptions(connection)

        else:
            await self.send_error(
                connection,
                f"Unknown message type: {msg_type}",
                WebSocketErrorCode.UNKNOWN_MESSAGE_TYPE
            )

    async def disconnect_client(self, client_id: str) -> None:
        """Disconnect a client.
        
        Args:
            client_id: Client connection ID
        """
        await self.connection_manager.disconnect(client_id)

    def parse_json_message(self, raw_message: str) -> Optional[Dict[str, Any]]:
        """Parse JSON message.
        
        Args:
            raw_message: Raw message string
            
        Returns:
            Parsed message or None if invalid
        """
        try:
            result: Dict[str, Any] = json.loads(raw_message)
            return result
        except json.JSONDecodeError:
            return None
