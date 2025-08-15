"""WebSocket connection manager with simplified patterns and Python 3.11 features."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.core.logging import logger
from app.websocket.metrics import WEBSOCKET_CONNECTIONS, WEBSOCKET_SUBSCRIPTIONS


@dataclass
class WebSocketConnection:
    """Represents a WebSocket client connection."""
    websocket: WebSocket
    client_id: str
    user_id: str | None = None
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    subscriptions: set[str] = field(default_factory=set)
    last_ping: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    async def send_json(self, data: dict[str, Any]) -> bool:
        """Send JSON data to client if connected."""
        if self.websocket.client_state != WebSocketState.CONNECTED:
            return False

        try:
            await self.websocket.send_json(data)
            return True
        except Exception as e:
            logger.error(f"Error sending to client {self.client_id}: {e}")
            return False

    async def send_text(self, message: str) -> bool:
        """Send text message to client if connected."""
        if self.websocket.client_state != WebSocketState.CONNECTED:
            return False

        try:
            await self.websocket.send_text(message)
            return True
        except Exception as e:
            logger.error(f"Error sending to client {self.client_id}: {e}")
            return False

    def subscribe(self, execution_id: str) -> None:
        """Subscribe to execution updates."""
        self.subscriptions.add(execution_id)
        WEBSOCKET_SUBSCRIPTIONS.inc()

    def unsubscribe(self, execution_id: str) -> None:
        """Unsubscribe from execution updates."""
        if execution_id in self.subscriptions:
            self.subscriptions.remove(execution_id)
            WEBSOCKET_SUBSCRIPTIONS.dec()

    def unsubscribe_all(self) -> None:
        """Remove all subscriptions."""
        if count := len(self.subscriptions):
            self.subscriptions.clear()
            WEBSOCKET_SUBSCRIPTIONS.dec(count)

    def is_subscribed_to(self, execution_id: str) -> bool:
        """Check if subscribed to an execution."""
        return execution_id in self.subscriptions

    def update_ping(self) -> None:
        """Update last ping timestamp."""
        self.last_ping = datetime.now(timezone.utc)

    def get_connection_info(self) -> dict[str, Any]:
        """Get connection information as dict."""
        return {
            "client_id": self.client_id,
            "user_id": self.user_id,
            "connected_at": self.connected_at.isoformat(),
            "last_ping": self.last_ping.isoformat(),
            "subscriptions": list(self.subscriptions),
            "metadata": self.metadata,
        }


class ConnectionManager:
    """Manages WebSocket connections with simplified data structures."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocketConnection] = {}
        self._user_connections: defaultdict[str, set[str]] = defaultdict(set)
        self._execution_subscribers: defaultdict[str, set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(
            self,
            websocket: WebSocket,
            client_id: str | None = None,
            user_id: str | None = None,
    ) -> WebSocketConnection:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()

        client_id = client_id or str(uuid4())
        connection = WebSocketConnection(websocket, client_id, user_id)

        async with self._lock:
            self._connections[client_id] = connection
            if user_id:
                self._user_connections[user_id].add(client_id)

        WEBSOCKET_CONNECTIONS.inc()

        logger.info(
            "WebSocket connected",
            extra={
                "client_id": client_id,
                "user_id": user_id,
                "total_connections": len(self._connections),
            }
        )

        # Send welcome message
        await connection.send_json({
            "type": "connection",
            "status": "connected",
            "client_id": client_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return connection

    async def disconnect(self, client_id: str) -> None:
        """Disconnect and cleanup a WebSocket connection."""
        async with self._lock:
            if not (connection := self._connections.get(client_id)):
                return

            # Remove from user connections
            if connection.user_id:
                self._user_connections[connection.user_id].discard(client_id)
                if not self._user_connections[connection.user_id]:
                    del self._user_connections[connection.user_id]

            # Remove from execution subscribers
            for execution_id in list(connection.subscriptions):
                self._unsubscribe_internal(client_id, execution_id)

            # Remove connection
            del self._connections[client_id]

        WEBSOCKET_CONNECTIONS.dec()

        logger.info(
            "WebSocket disconnected",
            extra={
                "client_id": client_id,
                "user_id": connection.user_id,
                "total_connections": len(self._connections),
            }
        )

    async def subscribe(self, client_id: str, execution_id: str) -> bool:
        """Subscribe a client to execution updates."""
        async with self._lock:
            if not (connection := self._connections.get(client_id)):
                return False

            # Add to connection subscriptions
            connection.subscribe(execution_id)

            # Add to execution subscribers
            self._execution_subscribers[execution_id].add(client_id)

        logger.info(
            "Client subscribed to execution",
            extra={
                "client_id": client_id,
                "execution_id": execution_id,
                "total_subscribers": len(self._execution_subscribers[execution_id]),
            }
        )

        return True

    async def unsubscribe(self, client_id: str, execution_id: str) -> bool:
        """Unsubscribe a client from execution updates"""
        async with self._lock:
            return self._unsubscribe_internal(client_id, execution_id)

    def _unsubscribe_internal(self, client_id: str, execution_id: str) -> bool:
        """Internal unsubscribe without lock."""
        if not (connection := self._connections.get(client_id)):
            return False

        # Remove from connection subscriptions
        connection.unsubscribe(execution_id)

        # Remove from execution subscribers
        self._execution_subscribers[execution_id].discard(client_id)
        if not self._execution_subscribers[execution_id]:
            del self._execution_subscribers[execution_id]

        return True

    async def broadcast_to_execution(
            self,
            execution_id: str,
            message: dict[str, Any]
    ) -> int:
        """Broadcast message to all clients subscribed to an execution."""
        # Get subscriber IDs while holding lock
        async with self._lock:
            subscriber_ids = list(self._execution_subscribers[execution_id])

        # Send messages and track results
        results = await asyncio.gather(
            *(self._send_to_connection(client_id, message) for client_id in subscriber_ids),
            return_exceptions=True
        )

        # Count successful sends and identify failed connections
        sent_count = 0
        disconnected_clients = []

        for client_id, result in zip(subscriber_ids, results, strict=False):
            match result:
                case True:
                    sent_count += 1
                case False | Exception():
                    disconnected_clients.append(client_id)

        # Cleanup disconnected clients
        for client_id in disconnected_clients:
            await self.disconnect(client_id)

        if sent_count > 0:
            logger.debug(
                "Broadcasted to execution subscribers",
                extra={
                    "execution_id": execution_id,
                    "sent_count": sent_count,
                    "message_type": message.get("type"),
                }
            )

        return sent_count

    async def _send_to_connection(self, client_id: str, message: dict[str, Any]) -> bool:
        """Helper to send message to a specific connection."""
        if connection := self._connections.get(client_id):
            return await connection.send_json(message)
        return False

    async def broadcast_to_user(
            self,
            user_id: str,
            message: dict[str, Any]
    ) -> int:
        """Broadcast message to all connections for a user."""
        async with self._lock:
            client_ids = list(self._user_connections[user_id])

        # Send to all user connections concurrently
        results = await asyncio.gather(
            *(self._send_to_connection(client_id, message) for client_id in client_ids),
            return_exceptions=True
        )

        # Count successful sends
        return sum(1 for result in results if result is True)

    async def send_to_client(
            self,
            client_id: str,
            message: dict[str, Any]
    ) -> bool:
        """Send message to specific client."""
        return await self._send_to_connection(client_id, message)

    async def handle_ping(self, client_id: str) -> bool:
        """Handle ping from client."""
        if connection := self._connections.get(client_id):
            connection.update_ping()
            return await connection.send_json({
                "type": "pong",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        return False

    def get_connection(self, client_id: str) -> WebSocketConnection | None:
        """Get connection by client ID."""
        return self._connections.get(client_id)

    def get_all_connections(self) -> dict[str, WebSocketConnection]:
        """Get all active connections."""
        return self._connections.copy()

    def get_execution_subscribers(self, execution_id: str) -> set[str]:
        """Get all subscribers for an execution."""
        return set(self._execution_subscribers[execution_id])

    def get_connection_count(self) -> int:
        """Get total number of active connections."""
        return len(self._connections)

    def get_stats(self) -> dict[str, Any]:
        """Get connection statistics."""
        return {
            "total_connections": len(self._connections),
            "total_users": len(self._user_connections),
            "total_executions_tracked": len(self._execution_subscribers),
            "connections_by_user": {
                user_id: len(clients)
                for user_id, clients in self._user_connections.items()
            },
            "subscribers_by_execution": {
                exec_id: len(subscribers)
                for exec_id, subscribers in self._execution_subscribers.items()
            },
        }

    async def cleanup_stale_connections(self, timeout_seconds: int = 300) -> int:
        """Cleanup connections that haven't pinged recently."""
        now = datetime.now(timezone.utc)

        # Find stale connections
        stale_clients = [
            client_id
            for client_id, connection in self._connections.items()
            if (now - connection.last_ping).total_seconds() > timeout_seconds
        ]

        # Disconnect stale clients
        await asyncio.gather(
            *(self.disconnect(client_id) for client_id in stale_clients),
            return_exceptions=True
        )

        if stale_clients:
            logger.info(
                "Cleaned up stale connections",
                extra={"count": len(stale_clients)}
            )

        return len(stale_clients)


def create_connection_manager() -> ConnectionManager:
    """Factory function to create a ConnectionManager instance."""
    return ConnectionManager()
