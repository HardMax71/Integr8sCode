import os
import socket
import tomllib
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.domain.execution import LanguageInfoDomain
from app.runtime_registry import EXAMPLE_SCRIPTS as EXEC_EXAMPLE_SCRIPTS
from app.runtime_registry import LANGUAGE_SPECS


def _supported_runtimes() -> dict[str, LanguageInfoDomain]:
    return {
        lang: LanguageInfoDomain(versions=spec["versions"], file_ext=spec["file_ext"])
        for lang, spec in LANGUAGE_SPECS.items()
    }


class Settings(BaseModel):
    """Application settings loaded from TOML + environment variables.

    Non-secret config comes from TOML files; secrets come from env vars with dev defaults.

    Load order (each layer overrides the previous):
        1. config_path: base settings (committed to git)
        2. override_path: the worker's overrides (SERVICE_NAME)
        3. Environment variables: SECRET_KEY, MONGO_USER, MONGO_PASSWORD, REDIS_PASSWORD and ENVIRONMENT

    Usage:
        Settings()                                                       # config.toml + env vars
        Settings(config_path="config.test.toml")                         # test config + env vars
        Settings(override_path="config.worker.toml")                     # base + worker + env vars
    """

    model_config = ConfigDict(extra="forbid")

    def __init__(
        self,
        config_path: str = "config.toml",
        override_path: str | None = None,
    ) -> None:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        if override_path:
            with open(override_path, "rb") as f:
                data |= tomllib.load(f)
        for key, default in (
            ("SECRET_KEY", "CHANGE_ME_min_32_chars_long_!!!!"),
            ("MONGO_USER", "root"),
            ("MONGO_PASSWORD", "rootpassword"),
            ("REDIS_PASSWORD", "redispassword"),
            ("ENVIRONMENT", "development"),
        ):
            data[key] = os.environ.get(key) or data.get(key) or default
        if data.get("MONGO_USER") and data.get("MONGO_PASSWORD"):
            user = quote(data["MONGO_USER"], safe="")
            password = quote(data["MONGO_PASSWORD"], safe="")
            host = data.get("MONGO_HOST", "mongo")
            port = data.get("MONGO_PORT", 27017)
            db = data.get("MONGO_DB", "integr8scode")
            data["MONGODB_URL"] = f"mongodb://{user}:{password}@{host}:{port}/{db}?authSource=admin"
        super().__init__(**data)

    PROJECT_NAME: str = "integr8scode"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: SecretStr = Field(
        ...,
        min_length=32,
        description="Secret key for JWT token signing. Must be at least 32 characters.",
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    MONGO_HOST: str = "mongo"
    MONGO_PORT: int = 27017
    MONGO_DB: str = "integr8scode"
    MONGO_USER: str = ""
    MONGO_PASSWORD: SecretStr = SecretStr("")
    MONGODB_URL: SecretStr = SecretStr("")
    KUBERNETES_CONFIG_PATH: str = "~/.kube/config"
    # k3s writes 127.0.0.1 into its kubeconfig; a container reaches the same API through the host
    KUBERNETES_API_SERVER: str = "https://host.docker.internal:6443"
    RATE_LIMIT_ENABLED: bool = True  # Set to False to disable rate limiting entirely

    SSL_KEYFILE: str = "/app/certs/key/server.key"
    SSL_CERTFILE: str = "/app/certs/cert/server.crt"

    SERVER_HOST: str = "localhost"
    SERVER_PORT: int = 443

    # Kubernetes namespace for execution pods
    K8S_NAMESPACE: str = "integr8scode"
    # ResourceQuota on what all pods in that namespace may request together
    K8S_NAMESPACE_CPU_QUOTA: str = "32"
    K8S_NAMESPACE_MEMORY_QUOTA: str = "4Gi"

    # Settings for Kubernetes resource limits and requests
    K8S_POD_CPU_LIMIT: str = "1000m"
    K8S_POD_MEMORY_LIMIT: str = "128Mi"
    K8S_POD_CPU_REQUEST: str = "1000m"
    K8S_POD_MEMORY_REQUEST: str = "128Mi"
    K8S_POD_EXECUTION_TIMEOUT: int = 300  # in seconds
    K8S_POD_RUNTIME_CLASS_NAME: str | None = None  # e.g. "gvisor" for sandboxed execution

    SUPPORTED_RUNTIMES: dict[str, LanguageInfoDomain] = Field(default_factory=_supported_runtimes)

    EXAMPLE_SCRIPTS: dict[str, str] = Field(default_factory=lambda: EXEC_EXAMPLE_SCRIPTS)

    # Security: bcrypt rounds (lower in tests for speed, higher in production for security)
    BCRYPT_ROUNDS: int = 12

    # Event-Driven Design Configuration
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:29092"
    KAFKA_REQUEST_TIMEOUT_MS: int = 40000
    KAFKA_GRACEFUL_TIMEOUT: float = 15.0

    # SSE Configuration
    SSE_CONSUMER_POOL_SIZE: int = 10  # Number of consumers in the partitioned pool

    # Notification configuration
    NOTIF_THROTTLE_WINDOW_HOURS: int = 1
    NOTIF_THROTTLE_MAX_PER_HOUR: int = 5

    # OpenTelemetry / Tracing Configuration
    OTLP_TRACES_ENDPOINT: str = ""
    TRACING_SAMPLING_RATE: float = Field(
        default=0.1,  # 10% sampling by default
        ge=0.0,
        le=1.0,
        description="Sampling rate for distributed tracing (0.0 to 1.0)",
    )

    # Redis Configuration
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: SecretStr = SecretStr("")
    REDIS_SSL: bool = False
    REDIS_MAX_CONNECTIONS: int = 200
    REDIS_DECODE_RESPONSES: Literal[True] = True

    # Rate Limiting Configuration
    RATE_LIMIT_REDIS_PREFIX: str = "rate_limit:"

    # Service metadata
    SERVICE_NAME: str = "integr8scode-backend"
    SERVICE_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"  # deployment environment (production, staging, development)
    HOSTNAME: str = Field(default_factory=socket.gethostname)

    # OpenTelemetry metrics export endpoint
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None

    # Web server (Gunicorn/Uvicorn) concurrency settings
    WEB_CONCURRENCY: int = 4
    WEB_TIMEOUT: int = 60
    WEB_BACKLOG: int = 2048

    # Development mode detection
    DEVELOPMENT_MODE: bool = False

    # CORS allowed origins (overridable via config.toml)
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "https://localhost:5001",
            "https://127.0.0.1:5001",
            "https://[::1]:5001",
            "https://localhost",
            "https://127.0.0.1",
            "https://localhost:443",
            "https://127.0.0.1:443",
            "https://[::1]:443",
        ]
    )

    # Logging configuration
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
