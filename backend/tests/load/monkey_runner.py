from __future__ import annotations

import asyncio
import json
import random
import string
import secrets
from typing import Any

from .config import LoadConfig
from .http_client import APIClient, APIUser
from .stats import StatsCollector
from .strategies import json_value


def _rand(n: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(n))


def _random_body() -> Any:
    # Generate random JSON-like structures
    options: list[Any] = [
        {"foo": _rand(), "bar": random.randint(-1000, 1000)},
        [random.random() for _ in range(random.randint(0, 10))],
        _rand(64),
        123,
        None,
        {"nested": {"a": _rand(), "b": [1, 2, _rand()]}}
    ]
    return random.choice(options)


def build_monkey_catalog(cfg: LoadConfig) -> list[tuple[str, str]]:
    # method, path pairs (intentionally including wrong methods)
    paths = [
        ("GET", "/auth/me"),
        ("POST", "/auth/login"),
        ("POST", "/auth/register"),
        ("POST", "/execute"),
        ("GET", "/k8s-limits"),
        ("GET", "/example-scripts"),
        ("GET", "/events/types/list"),
        ("GET", "/notifications"),
        ("POST", "/notifications/mark-all-read"),
        ("GET", "/user/settings/"),
        ("PUT", "/user/settings/theme"),
        ("GET", "/events/user"),
        ("GET", "/events/statistics"),
        # Wrong/unsupported paths to test 404 handling
        ("GET", "/nope"),
        ("POST", "/does-not-exist"),
    ]
    # Build absolute URLs:
    # - If entry is already an absolute URL (starts with http), keep it as-is
    # - Otherwise, treat it as an API-relative path and prepend base+prefix via cfg.api()
    out: list[tuple[str, str]] = []
    for m, p in paths:
        if p.startswith("http://") or p.startswith("https://"):
            out.append((m, p))
        else:
            out.append((m, cfg.api(p)))
    return out


import time


async def run_monkey_swarm(cfg: LoadConfig, stats: StatsCollector, clients: int) -> None:
    catalog = build_monkey_catalog(cfg)
    sem = asyncio.Semaphore(cfg.concurrency)
    deadline = time.time() + max(1, cfg.duration_seconds)

    async def one_client(i: int) -> None:
        c = APIClient(cfg, stats)
        try:
            # Half of clients attempt to login/register first
            if random.random() < 0.5:
                uname = f"monkey_{_rand(6)}"
                user = APIUser(
                    username=uname,
                    email=f"{uname}@{cfg.user_domain}",
                    password=cfg.user_password
                )
                await c.register(user)
                await c.login(uname, cfg.user_password)

            # Run until deadline
            while time.time() < deadline:
                method, url = random.choice(catalog)
                headers = {}
                # Randomly include/omit CSRF header
                if random.random() < 0.5:
                    headers = c._with_csrf()
                # Random bodies for POST/PUT
                body = None
                if method in ("POST", "PUT") and random.random() < 0.8:
                    # Prefer Hypothesis-generated JSON payloads when available
                    try:
                        body = json_value.example()
                    except Exception:
                        body = _random_body()
                    # 70% send JSON, 30% send text or wrong content type
                    if random.random() < 0.7:
                        await c._request(method, url, json=body, headers=headers)
                    else:
                        await c._request(method, url, content=json.dumps(body), headers=headers)
                else:
                    await c._request(method, url)
                # Yield a tiny bit to share the loop
                await asyncio.sleep(0)
        finally:
            await c.close()

    tasks = []
    for i in range(clients):
        await sem.acquire()
        async def _spawn(idx: int) -> None:
            try:
                await one_client(idx)
            finally:
                sem.release()
        tasks.append(asyncio.create_task(_spawn(i)))
    await asyncio.gather(*tasks, return_exceptions=True)
