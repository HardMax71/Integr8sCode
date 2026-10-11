from __future__ import annotations

import random
import re
import string
import time
from dataclasses import dataclass
from typing import Any

import httpx2

from .config import LoadConfig
from .stats import StatsCollector

UUID_RE = re.compile(r"[0-9a-fA-F-]{36}")


def _rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


@dataclass
class APIUser:
    username: str
    email: str
    password: str


class APIClient:
    """Stateful HTTP client that maintains cookies, CSRF, and helper methods."""

    def __init__(self, cfg: LoadConfig, stats: StatsCollector) -> None:
        self.cfg = cfg
        self.stats = stats
        self.client = httpx2.AsyncClient(verify=cfg.verify_tls, timeout=20.0)
        self.csrf_token: str | None = None

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx2.Response:
        t0 = time.perf_counter()
        try:
            resp = await self.client.request(method, url, **kwargs)
            dur = (time.perf_counter() - t0) * 1000
            # bytes received best-effort
            brx = len(resp.content) if resp.content is not None else 0
            self.stats.record(method.upper(), url, resp.status_code, dur, brx)
            return resp
        except Exception as e:  # noqa: BLE001
            dur = (time.perf_counter() - t0) * 1000
            self.stats.record(method.upper(), url, 599, dur, 0)
            self.stats.record_exception(e)
            raise

    async def register(self, user: APIUser) -> bool:
        url = self.cfg.api("/auth/register")
        payload = {"username": user.username, "email": user.email, "password": user.password}
        r = await self._request("POST", url, json=payload)
        return r.status_code in (200, 201)

    async def login(self, username: str, password: str) -> bool:
        url = self.cfg.api("/auth/login")
        data = {"username": username, "password": password}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        r = await self._request("POST", url, data=httpx2.QueryParams(data), headers=headers)
        if r.status_code != 200:
            return False
        self.csrf_token = r.json().get("csrf_token")
        return True

    def _with_csrf(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        h = dict(headers or {})
        if self.csrf_token:
            h.setdefault("X-CSRF-Token", self.csrf_token)
        return h

    async def me(self) -> httpx2.Response:
        return await self._request("GET", self.cfg.api("/auth/me"))

    async def execute(self, script: str, lang: str = "python", ver: str = "3.11") -> tuple[int, dict[str, Any]]:
        url = self.cfg.api("/execute")
        payload = {"script": script, "lang": lang, "lang_version": ver}
        r = await self._request("POST", url, json=payload, headers=self._with_csrf())
        body: dict[str, Any] = {}
        try:
            body = r.json()
        except ValueError:
            pass
        return r.status_code, body

    async def result(self, execution_id: str) -> httpx2.Response:
        return await self._request("GET", self.cfg.api(f"/executions/{execution_id}/result"))

    async def execution_events(self, execution_id: str, limit: int = 50) -> httpx2.Response:
        return await self._request("GET", self.cfg.api(f"/executions/{execution_id}/events?limit={limit}"))

    async def user_executions(self, limit: int = 10) -> httpx2.Response:
        return await self._request("GET", self.cfg.api(f"/user/executions?limit={limit}"))

    async def sse_execution(self, execution_id: str, max_seconds: float = 10.0) -> tuple[int, int]:
        """Stream SSE for an execution; returns (http_status, bytes_rx)."""
        url = self.cfg.api(f"/events/executions/{execution_id}")
        # Use a separate streaming client to avoid interfering with normal client timeouts
        async with httpx2.AsyncClient(verify=self.cfg.verify_tls, timeout=None) as s:
            # Reuse cookies for auth
            s.cookies.update(self.client.cookies)
            t0 = time.perf_counter()
            try:
                async with s.stream("GET", url) as resp:
                    bytes_rx = 0
                    start = time.perf_counter()
                    async for chunk in resp.aiter_raw():
                        bytes_rx += len(chunk)
                        if time.perf_counter() - start > max_seconds:
                            break
                dur = (time.perf_counter() - t0) * 1000
                self.stats.record("GET", url, getattr(resp, "status_code", 200), dur, bytes_rx)
                return getattr(resp, "status_code", 200), bytes_rx
            except Exception as e:  # noqa: BLE001
                dur = (time.perf_counter() - t0) * 1000
                self.stats.record("GET", url, 599, dur, 0)
                self.stats.record_exception(e)
                return 599, 0

    async def create_script(self, name: str, script: str) -> httpx2.Response:
        url = self.cfg.api("/scripts")
        payload = {"name": name, "script": script}
        return await self._request("POST", url, json=payload, headers=self._with_csrf())

    async def list_scripts(self) -> httpx2.Response:
        return await self._request("GET", self.cfg.api("/scripts"))

    async def update_script(self, script_id: str, name: str, script: str) -> httpx2.Response:
        url = self.cfg.api(f"/scripts/{script_id}")
        payload = {"name": name, "script": script}
        return await self._request("PUT", url, json=payload, headers=self._with_csrf())

    async def delete_script(self, script_id: str) -> httpx2.Response:
        url = self.cfg.api(f"/scripts/{script_id}")
        return await self._request("DELETE", url, headers=self._with_csrf())

    async def get_settings(self) -> httpx2.Response:
        return await self._request("GET", self.cfg.api("/user/settings/"))

    async def update_theme(self) -> httpx2.Response:
        url = self.cfg.api("/user/settings/theme")
        theme = random.choice(["light", "dark", "auto"])
        return await self._request("PUT", url, json={"theme": theme}, headers=self._with_csrf())

    async def list_notifications(self) -> httpx2.Response:
        return await self._request("GET", self.cfg.api("/notifications"))

    async def mark_all_read(self) -> httpx2.Response:
        url = self.cfg.api("/notifications/mark-all-read")
        return await self._request("POST", url, headers=self._with_csrf())

    @staticmethod
    def extract_id(text: str) -> str | None:
        m = UUID_RE.search(text)
        return m.group(0) if m else None

    @staticmethod
    def random_script(valid: bool = True) -> str:
        if valid:
            return f"print('hi-{_rand_str(6)}')"
        # syntax error / crash variants
        options = [
            "print(2",  # missing paren
            "raise Exception('boom')",
            "x = 1/0",
        ]
        return random.choice(options)
