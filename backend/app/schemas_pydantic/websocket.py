"""Pydantic schemas for WebSocket communication.

This module defines schemas for WebSocket messages. There are two types of messages:
1. WebSocket protocol messages (auth, ping/pong, subscriptions) - use WebSocketMessageType
2. Event messages forwarded from Kafka (execution, pod, result events) - use EventType from event_schemas
"""
from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas_avro.event_schemas import EventType


class WebSocketMessageType(StrEnum):
    """WebSocket message types for WebSocket-specific messages."""
    # Authentication
    AUTH = "auth"

    # Connection management
    PING = "ping"
    PONG = "pong"

    # Subscription management
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"
    LIST_SUBSCRIPTIONS = "list_subscriptions"
    SUBSCRIPTIONS = "subscriptions"

    # WebSocket-specific
    EXECUTION_STATUS = "execution.status"  # Current status query response
    ERROR = "error"


class WebSocketErrorCode(StrEnum):
    """WebSocket error codes."""
    INVALID_JSON = "INVALID_JSON"
    MISSING_EXECUTION_ID = "MISSING_EXECUTION_ID"
    UNAUTHORIZED = "UNAUTHORIZED"
    SUBSCRIPTION_FAILED = "SUBSCRIPTION_FAILED"
    UNKNOWN_MESSAGE_TYPE = "UNKNOWN_MESSAGE_TYPE"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"


class WebSocketMessage(BaseModel):
    """Base WebSocket message."""
    type: str = Field(description="Message type")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message timestamp")


class AuthMessage(WebSocketMessage):
    """Authentication message."""
    type: str = Field(default=WebSocketMessageType.AUTH)
    status: str = Field(description="Authentication status")
    user_id: Optional[str] = Field(None, description="Authenticated user ID")
    client_id: Optional[str] = Field(None, description="Client connection ID")


class ErrorMessage(WebSocketMessage):
    """Error message."""
    type: str = Field(default=WebSocketMessageType.ERROR)
    error: str = Field(description="Error description")
    code: WebSocketErrorCode = Field(description="Error code")
    execution_id: Optional[str] = Field(None, description="Related execution ID")


class PingMessage(WebSocketMessage):
    """Ping message."""
    type: str = Field(default=WebSocketMessageType.PING)


class PongMessage(WebSocketMessage):
    """Pong message."""
    type: str = Field(default=WebSocketMessageType.PONG)


class SubscribeMessage(WebSocketMessage):
    """Subscribe to execution updates."""
    type: str = Field(default=WebSocketMessageType.SUBSCRIBE)
    execution_id: str = Field(description="Execution ID to subscribe to")


class UnsubscribeMessage(WebSocketMessage):
    """Unsubscribe from execution updates."""
    type: str = Field(default=WebSocketMessageType.UNSUBSCRIBE)
    execution_id: str = Field(description="Execution ID to unsubscribe from")


class SubscribedMessage(WebSocketMessage):
    """Subscription confirmation."""
    type: str = Field(default=WebSocketMessageType.SUBSCRIBED)
    execution_id: str = Field(description="Subscribed execution ID")


class UnsubscribedMessage(WebSocketMessage):
    """Unsubscription confirmation."""
    type: str = Field(default=WebSocketMessageType.UNSUBSCRIBED)
    execution_id: str = Field(description="Unsubscribed execution ID")


class ListSubscriptionsMessage(WebSocketMessage):
    """Request list of current subscriptions."""
    type: str = Field(default=WebSocketMessageType.LIST_SUBSCRIPTIONS)


class SubscriptionsMessage(WebSocketMessage):
    """Current subscriptions list."""
    type: str = Field(default=WebSocketMessageType.SUBSCRIPTIONS)
    subscriptions: List[str] = Field(default_factory=list, description="List of execution IDs")


class ExecutionStatusData(BaseModel):
    """Execution status data."""
    execution_id: str = Field(description="Execution ID")
    status: str = Field(description="Execution status")
    created_at: str = Field(description="Creation timestamp")
    lang: str = Field(description="Programming language")
    lang_version: str = Field(description="Language version")
    has_output: bool = Field(description="Whether execution has output")
    has_errors: bool = Field(description="Whether execution has errors")


class ExecutionStatusMessage(WebSocketMessage):
    """Execution status update."""
    type: str = Field(default=WebSocketMessageType.EXECUTION_STATUS)
    data: ExecutionStatusData = Field(description="Execution status data")


class ExecutionEventData(BaseModel):
    """Base execution event data."""
    execution_id: str = Field(description="Execution ID")
    user_id: str = Field(description="User ID")
    status: Optional[str] = Field(None, description="Execution status")
    message: Optional[str] = Field(None, description="Event message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional details")


class ExecutionEventMessage(WebSocketMessage):
    """Execution event message."""
    type: EventType = Field(description="Event type")
    data: ExecutionEventData = Field(description="Event data")


class PodEventData(BaseModel):
    """Pod event data."""
    execution_id: str = Field(description="Execution ID")
    pod_name: str = Field(description="Pod name")
    namespace: str = Field(description="Kubernetes namespace")
    status: str = Field(description="Pod status")
    message: Optional[str] = Field(None, description="Status message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional details")


class PodEventMessage(WebSocketMessage):
    """Pod event message."""
    type: EventType = Field(description="Event type")
    data: PodEventData = Field(description="Pod event data")


class ResultStoredData(BaseModel):
    """Result stored event data."""
    execution_id: str = Field(description="Execution ID")
    has_output: bool = Field(description="Whether result has output")
    has_errors: bool = Field(description="Whether result has errors")
    exit_code: Optional[int] = Field(None, description="Process exit code")
    execution_time: Optional[float] = Field(None, description="Execution time in seconds")


class ResultStoredMessage(WebSocketMessage):
    """Result stored event message."""
    type: EventType = Field(default=EventType.RESULT_STORED)
    data: ResultStoredData = Field(description="Result data")


class WebSocketAuthRequest(BaseModel):
    """WebSocket authentication request."""
    type: WebSocketMessageType = Field(default=WebSocketMessageType.AUTH)
    token: str = Field(description="Authentication token")


class WebSocketAuthResponse(BaseModel):
    """WebSocket authentication response."""
    user_id: str = Field(description="Authenticated user ID")
    username: str = Field(description="Username")
    role: str = Field(description="User role")
    token_exp: Optional[datetime] = Field(None, description="Token expiration")
