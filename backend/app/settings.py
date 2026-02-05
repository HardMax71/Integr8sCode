import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.execution import LanguageInfoDomain
from app.runtime_registry import EXAMPLE_SCRIPTS as EXEC_EXAMPLE_SCRIPTS
from app.runtime_registry import SUPPORTED_RUNTIMES as RUNTIME_MATRIX


class Settings(BaseModel):
    """Application settings loaded from TOML configuration files.

    All config is read from TOML — no environment variables, no .env files.

    Load order (each layer overrides the previous):
        1. config_path    — base settings (committed to git)
        2. secrets_path   — sensitive overrides (gitignored, mounted from K8s Secret in prod)
        3. override_path  — per-worker service overrides (TRACING_SERVICE_NAME, etc.)

    Usage:
        Settings()                                                       # config.toml + secrets
        Settings(config_path="config.test.toml")                         # test config (has own secrets)
        Settings(override_path="config.coordinator.toml")                # base + secrets + worker
    """

    model_config = ConfigDict(extra="forbid")

    def __init__(
        self,
        config_path: str = "config.toml",
        override_path: str | None = None,
        secrets_path: str = "secrets.toml",
    ) -> None:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        if Path(secrets_path).is_file():
            with open(secrets_path, "rb") as f:
                data |= tomllib.load(f)
        if override_path:
            with open(override_path, "rb") as f:
                data |= tomllib.load(f)
        super().__init__(**data)

    PROJECT_NAME: str = "integr8scode"
    DATABASE_NAME: str = "integr8scode_db"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = Field(
        ...,
        min_length=32,
        description="Secret key for JWT token signing. Must be at least 32 characters.",
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    MONGODB_URL: str = "mongodb://mongo:27017/integr8scode"
    KUBERNETES_CONFIG_PATH: str = "~/.kube/config"
    KUBERNETES_CA_CERTIFICATE_PATH: str | None = None
    RATE_LIMITS: str = "100/minute"
    RATE_LIMIT_ENABLED: bool = True  # Set to False to disable rate limiting entirely

    SSL_KEYFILE: str = "/app/certs/server.key"
    SSL_CERTFILE: str = "/app/certs/server.crt"

    SERVER_HOST: str = "localhost"
    SERVER_PORT: int = 443

    # Kubernetes namespace for execution pods
    K8S_NAMESPACE: str = "integr8scode"

    # Maximum concurrent pod creations allowed by k8s worker
    K8S_MAX_CONCURRENT_PODS: int = 10

    # Settings for Kubernetes resource limits and requests
    K8S_POD_CPU_LIMIT: str = "1000m"
    K8S_POD_MEMORY_LIMIT: str = "128Mi"
    K8S_POD_CPU_REQUEST: str = "1000m"
    K8S_POD_MEMORY_REQUEST: str = "128Mi"
    K8S_POD_EXECUTION_TIMEOUT: int = 300  # in seconds
    K8S_POD_PRIORITY_CLASS_NAME: str | None = None

    SUPPORTED_RUNTIMES: dict[str, LanguageInfoDomain] = Field(default_factory=lambda: RUNTIME_MATRIX)

    EXAMPLE_SCRIPTS: dict[str, str] = Field(default_factory=lambda: EXEC_EXAMPLE_SCRIPTS)

    TESTING: bool = False

    # Security: bcrypt rounds (lower in tests for speed, higher in production for security)
    BCRYPT_ROUNDS: int = 12

    # Event-Driven Design Configuration
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:29092"
    ENABLE_EVENT_STREAMING: bool = False
    EVENT_RETENTION_DAYS: int = 30
    KAFKA_TOPIC_PREFIX: str = "pref"
    KAFKA_CONSUMER_GROUP_ID: str = "integr8scode-backend"
    KAFKA_AUTO_OFFSET_RESET: str = "earliest"
    KAFKA_ENABLE_AUTO_COMMIT: bool = True
    KAFKA_SESSION_TIMEOUT_MS: int = 45000
    KAFKA_HEARTBEAT_INTERVAL_MS: int = 10000
    KAFKA_MAX_POLL_INTERVAL_MS: int = 300000
    KAFKA_MAX_POLL_RECORDS: int = 500
    KAFKA_REQUEST_TIMEOUT_MS: int = 40000

    # SSE Configuration
    SSE_CONSUMER_POOL_SIZE: int = 10  # Number of consumers in the partitioned pool
    SSE_HEARTBEAT_INTERVAL: int = 30  # Heartbeat interval in seconds for SSE - keep connection alive

    # Notification configuration
    NOTIF_THROTTLE_WINDOW_HOURS: int = 1
    NOTIF_THROTTLE_MAX_PER_HOUR: int = 5
    NOTIF_MAX_SCHEDULE_DAYS: int = 25  # Max days ahead a notification can be scheduled (must be < TTL)

    # OpenTelemetry / Jaeger Configuration
    ENABLE_TRACING: bool = True
    JAEGER_AGENT_HOST: str = "jaeger"
    JAEGER_AGENT_PORT: int = 6831
    JAEGER_COLLECTOR_ENDPOINT: str | None = None
    TRACING_SAMPLING_RATE: float = Field(
        default=0.1,  # 10% sampling by default
        ge=0.0,
        le=1.0,
        description="Sampling rate for distributed tracing (0.0 to 1.0)",
    )
    TRACING_SERVICE_NAME: str = "integr8scode-backend"
    TRACING_SERVICE_VERSION: str = "1.0.0"
    TRACING_ADAPTIVE_SAMPLING: bool = False  # Enable adaptive sampling in production

    # Dead Letter Queue Configuration
    DLQ_RETRY_MAX_ATTEMPTS: int = 5
    DLQ_RETRY_BASE_DELAY_SECONDS: float = 60.0
    DLQ_RETRY_MAX_DELAY_SECONDS: float = 3600.0
    DLQ_RETENTION_DAYS: int = 7
    DLQ_WARNING_THRESHOLD: int = 100
    DLQ_CRITICAL_THRESHOLD: int = 1000

    # App URL for notification links
    APP_URL: str = "https://integr8scode.cc"

    # Redis Configuration
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_SSL: bool = False
    REDIS_MAX_CONNECTIONS: int = 200
    REDIS_DECODE_RESPONSES: Literal[True] = True

    # Rate Limiting Configuration
    RATE_LIMIT_DEFAULT_REQUESTS: int = 100
    RATE_LIMIT_DEFAULT_WINDOW: int = 60  # seconds
    RATE_LIMIT_BURST_MULTIPLIER: float = 1.5
    RATE_LIMIT_REDIS_PREFIX: str = "rate_limit:"
    RATE_LIMIT_ALGORITHM: str = "sliding_window"  # sliding_window or token_bucket

    # Service metadata
    SERVICE_NAME: str = "integr8scode-backend"
    SERVICE_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "production"  # deployment environment (production, staging, development)

    # OpenTelemetry Configuration
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    OTEL_SERVICE_NAME: str | None = None
    OTEL_SERVICE_VERSION: str | None = None
    OTEL_RESOURCE_ATTRIBUTES: str | None = None

    # Web server (Gunicorn/Uvicorn) concurrency settings
    WEB_CONCURRENCY: int = 4
    WEB_THREADS: int = 1
    WEB_TIMEOUT: int = 60
    WEB_BACKLOG: int = 2048

    # Development mode detection
    DEVELOPMENT_MODE: bool = False
    SECURE_COOKIES: bool = True

    # Logging configuration
    LOG_LEVEL: str = Field(default="DEBUG", description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
