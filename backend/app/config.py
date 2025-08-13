from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.runtime_registry import EXAMPLE_SCRIPTS as EXEC_EXAMPLE_SCRIPTS
from app.runtime_registry import SUPPORTED_RUNTIMES as RUNTIME_MATRIX


class Settings(BaseSettings):
    PROJECT_NAME: str = "integr8scode"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = Field(
        default="key" * 12,  # Actual key be loaded from .env file
        min_length=32,
        description="Secret key for JWT token signing. Must be at least 32 characters."
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    MONGODB_URL: str = "mongodb://mongo:27017/integr8scode"
    KUBERNETES_CONFIG_PATH: str = "~/.kube/config"
    KUBERNETES_CA_CERTIFICATE_PATH: str | None = None
    RATE_LIMITS: str = "100/minute"

    SSL_KEYFILE: str = "/app/certs/server.key"
    SSL_CERTFILE: str = "/app/certs/server.crt"

    SERVER_HOST: str = "localhost"
    SERVER_PORT: int = 443

    # Settings for Kubernetes resource limits and requests
    K8S_POD_CPU_LIMIT: str = "1000m"
    K8S_POD_MEMORY_LIMIT: str = "128Mi"
    K8S_POD_CPU_REQUEST: str = "1000m"
    K8S_POD_MEMORY_REQUEST: str = "128Mi"
    K8S_POD_EXECUTION_TIMEOUT: int = 300  # in seconds
    K8S_POD_PRIORITY_CLASS_NAME: str | None = None

    SUPPORTED_RUNTIMES: dict[str, list[str]] = Field(
        default_factory=lambda: RUNTIME_MATRIX
    )

    EXAMPLE_SCRIPTS: dict[str, str] = Field(
        default_factory=lambda: EXEC_EXAMPLE_SCRIPTS
    )

    PROMETHEUS_URL: str = "http://prometheus:9090"

    TESTING: bool = False

    # Event-Driven Design Configuration
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:29092"
    SCHEMA_REGISTRY_URL: str = "http://schema-registry:8081"
    SCHEMA_REGISTRY_AUTH: str | None = None  # Format: "username:password"
    ENABLE_EVENT_STREAMING: bool = False
    EVENT_RETENTION_DAYS: int = 30
    KAFKA_CONSUMER_GROUP_ID: str = "integr8scode-backend"
    KAFKA_AUTO_OFFSET_RESET: str = "earliest"
    KAFKA_ENABLE_AUTO_COMMIT: bool = True
    KAFKA_SESSION_TIMEOUT_MS: int = 30000
    KAFKA_MAX_POLL_RECORDS: int = 500

    # Schema Configuration
    SCHEMA_BASE_PATH: str = "app/schemas_avro"
    SCHEMA_AVRO_PATH: str = "app/schemas_avro"
    SCHEMA_CONFIG_PATH: str | None = None

    # OpenTelemetry / Jaeger Configuration
    ENABLE_TRACING: bool = True
    JAEGER_AGENT_HOST: str = "jaeger"
    JAEGER_AGENT_PORT: int = 6831
    JAEGER_COLLECTOR_ENDPOINT: str | None = None
    TRACING_SAMPLING_RATE: float = 1.0  # 100% sampling by default
    TRACING_SERVICE_NAME: str = "integr8scode-backend"
    TRACING_SERVICE_VERSION: str = "1.0.0"
    TRACING_ADAPTIVE_SAMPLING: bool = False  # Enable adaptive sampling in production

    # Dead Letter Queue Configuration
    KAFKA_DLQ_TOPIC: str = "dead-letter-queue"
    DLQ_RETRY_MAX_ATTEMPTS: int = 5
    DLQ_RETRY_BASE_DELAY_SECONDS: float = 60.0
    DLQ_RETRY_MAX_DELAY_SECONDS: float = 3600.0
    DLQ_RETENTION_DAYS: int = 7
    DLQ_WARNING_THRESHOLD: int = 100
    DLQ_CRITICAL_THRESHOLD: int = 1000

    # App URL for notification links
    APP_URL: str = "https://integr8scode.cc"

    # Feature flags
    FEATURE_EVENT_DRIVEN_EXECUTION: bool = True
    FEATURE_SSE_STREAMING: bool = True
    FEATURE_WEBSOCKET_UPDATES: bool = True
    FEATURE_DISTRIBUTED_TRACING: bool = True
    FEATURE_EVENT_STORE_ENABLED: bool = True
    FEATURE_CIRCUIT_BREAKER_ENABLED: bool = True
    FEATURE_KAFKA_EVENTS: bool = True

    # WebSocket configuration
    WEBSOCKET_PING_INTERVAL: int = 30
    WEBSOCKET_PING_TIMEOUT: int = 10
    WEBSOCKET_MAX_CONNECTIONS_PER_USER: int = 5
    WEBSOCKET_STALE_CONNECTION_TIMEOUT: int = 300

    # Service metadata
    SERVICE_NAME: str = "integr8scode-backend"
    SERVICE_VERSION: str = "1.0.0"

    # Additional MongoDB settings (for docker-compose compatibility)
    MONGO_ROOT_USER: str | None = None
    MONGO_ROOT_PASSWORD: str | None = None

    # Development mode detection
    DEVELOPMENT_MODE: bool = False
    SECURE_COOKIES: bool = True  # Can be overridden in .env for development

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="forbid"  # Raise error on extra fields
    )


def get_settings() -> Settings:
    return Settings()
