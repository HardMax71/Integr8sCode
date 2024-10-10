from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Integr8sCode"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    MONGODB_URL: str
    KUBERNETES_CONFIG_PATH: str = "~/.kube/config"

    # Settings for Kubernetes resource limits and requests
    K8S_POD_CPU_LIMIT: str = "100m"
    K8S_POD_MEMORY_LIMIT: str = "128Mi"
    K8S_POD_CPU_REQUEST: str = "100m"
    K8S_POD_MEMORY_REQUEST: str = "128Mi"

    class Config:
        env_file = ".env"


def get_settings() -> Settings:
    return Settings()
