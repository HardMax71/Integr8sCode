from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Mode = Literal["monkey", "user", "both"]


class LoadConfig(BaseModel):
    base_url: str = "https://[::1]:443"
    api_prefix: str = "/api/v1"
    verify_tls: bool = False
    generate_plots: bool = False

    # Clients and workload
    mode: Mode = "both"
    clients: int = 25
    concurrency: int = 10
    # Default run duration ~3 minutes
    duration_seconds: int = 180
    ramp_up_seconds: int = 5

    # User pool (for user-mode)
    auto_register_users: bool = True
    user_prefix: str = "loaduser"
    user_domain: str = "example.com"
    user_password: str = "testpass123!"

    # Endpoint toggles
    enable_sse: bool = True
    enable_saved_scripts: bool = True
    enable_user_settings: bool = True
    enable_notifications: bool = True

    # Reporting
    # Default to tests/load/out relative to current working directory
    output_dir: str = "tests/load/out"

    def api(self, path: str) -> str:
        prefix = self.api_prefix.rstrip("/")
        return f"{self.base_url.rstrip('/')}{prefix}{path}"
