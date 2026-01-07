from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["monkey", "user", "both"]


def _get_mode() -> Mode:
    """Get mode from env with proper Literal type."""
    env_val = os.getenv("LOAD_MODE", "both")
    if env_val == "monkey":
        return "monkey"
    if env_val == "user":
        return "user"
    return "both"


@dataclass(slots=True)
class LoadConfig:
    base_url: str = field(default_factory=lambda: os.getenv("LOAD_BASE_URL", "https://[::1]:443"))
    api_prefix: str = field(default_factory=lambda: os.getenv("LOAD_API_PREFIX", "/api/v1"))
    verify_tls: bool = field(
        default_factory=lambda: os.getenv("LOAD_VERIFY_TLS", "false").lower() in ("1", "true", "yes")
    )
    generate_plots: bool = field(default=False)

    # Clients and workload
    mode: Mode = field(default_factory=_get_mode)
    clients: int = int(os.getenv("LOAD_CLIENTS", "25"))
    concurrency: int = int(os.getenv("LOAD_CONCURRENCY", "10"))
    # Default run duration ~3 minutes
    duration_seconds: int = int(os.getenv("LOAD_DURATION", "180"))
    ramp_up_seconds: int = int(os.getenv("LOAD_RAMP", "5"))

    # User pool (for user-mode)
    auto_register_users: bool = field(
        default_factory=lambda: os.getenv("LOAD_AUTO_REGISTER", "true").lower() in ("1", "true", "yes")
    )
    user_prefix: str = os.getenv("LOAD_USER_PREFIX", "loaduser")
    user_domain: str = os.getenv("LOAD_USER_DOMAIN", "example.com")
    user_password: str = os.getenv("LOAD_USER_PASSWORD", "testpass123!")

    # Endpoint toggles
    enable_sse: bool = field(
        default_factory=lambda: os.getenv("LOAD_ENABLE_SSE", "true").lower() in ("1", "true", "yes")
    )
    enable_saved_scripts: bool = field(
        default_factory=lambda: os.getenv("LOAD_ENABLE_SCRIPTS", "true").lower() in ("1", "true", "yes")
    )
    enable_user_settings: bool = field(
        default_factory=lambda: os.getenv("LOAD_ENABLE_SETTINGS", "true").lower() in ("1", "true", "yes")
    )
    enable_notifications: bool = field(
        default_factory=lambda: os.getenv("LOAD_ENABLE_NOTIFICATIONS", "true").lower() in ("1", "true", "yes")
    )

    # Reporting
    # Default to tests/load/out relative to current working directory
    output_dir: str = field(default_factory=lambda: os.getenv("LOAD_OUTPUT_DIR", "tests/load/out"))

    def api(self, path: str) -> str:
        prefix = self.api_prefix.rstrip("/")
        return f"{self.base_url.rstrip('/')}{prefix}{path}"
