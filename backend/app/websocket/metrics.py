from prometheus_client import Gauge

WEBSOCKET_CONNECTIONS = Gauge(
    "websocket_active_connections",
    "Number of active WebSocket connections"
)

WEBSOCKET_SUBSCRIPTIONS = Gauge(
    "websocket_active_subscriptions",
    "Number of active execution subscriptions"
)
