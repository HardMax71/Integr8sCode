from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "integr8scode"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "default_secret_key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    MONGODB_URL: str = "mongodb://mongo:27017/integr8scode"
    KUBERNETES_CONFIG_PATH: str = "~/.kube/config"
    KUBERNETES_CA_CERTIFICATE_PATH: Optional[str] = None
    RATE_LIMITS: str = "100/minute"

    SERVER_HOST: str = "localhost"
    SERVER_PORT: int = 443

    # Settings for Kubernetes resource limits and requests
    K8S_POD_CPU_LIMIT: str = "100m"
    K8S_POD_MEMORY_LIMIT: str = "128Mi"
    K8S_POD_CPU_REQUEST: str = "100m"
    K8S_POD_MEMORY_REQUEST: str = "128Mi"
    K8S_POD_EXECUTION_TIMEOUT: int = 5  # in seconds
    SUPPORTED_PYTHON_VERSIONS: list[str] = ["3.7", "3.8", "3.9", "3.10", "3.11", "3.12"]
    PROMETHEUS_URL: str = "http://prometheus:9090"

    TESTING: bool = False

    class Config:
        env_file = ".env"


def get_settings() -> Settings:
    return Settings()
