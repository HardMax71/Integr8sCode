from __future__ import annotations

import asyncio
import json
import random
import secrets
import string
import time
from typing import Any

from .config import LoadConfig
from .http_client import APIClient, APIUser
from .stats import StatsCollector


def _rand(n: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _random_body() -> Any:
    # Generate random JSON-like structures
    options: list[Any] = [
        {"foo": _rand(), "bar": random.randint(-1000, 1000)},
        [random.random() for _ in range(random.randint(0, 10))],
        _rand(64),
        123,
        None,
        {"nested": {"a": _rand(), "b": [1, 2, _rand()]}},
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
        ("GET", "/notifications"),
        ("POST", "/notifications/mark-all-read"),
        ("GET", "/user/settings/"),
        ("PUT", "/user/settings/theme"),
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


async def _monkey_client(
    cfg: LoadConfig,
    stats: StatsCollector,
    catalog: list[tuple[str, str]],
    deadline: float,
    sem: asyncio.Semaphore,
) -> None:
    async with sem, APIClient(cfg, stats) as c:
        # Half of the clients sign up first
        if random.random() < 0.5:
            uname = f"monkey_{_rand(6)}"
            await c.register(APIUser(username=uname, email=f"{uname}@{cfg.user_domain}", password=cfg.user_password))
            await c.login(uname, cfg.user_password)

        while time.time() < deadline:
            method, url = random.choice(catalog)
            headers = c._with_csrf() if random.random() < 0.5 else {}
            if method in ("POST", "PUT") and random.random() < 0.8:
                body = _random_body()
                # 70% JSON, the rest as raw text with the wrong content type
                if random.random() < 0.7:
                    await c._request(method, url, json=body, headers=headers)
                else:
                    await c._request(method, url, content=json.dumps(body), headers=headers)
            else:
                await c._request(method, url)
            await asyncio.sleep(0)


async def run_monkey_swarm(cfg: LoadConfig, stats: StatsCollector, clients: int) -> None:
    catalog = build_monkey_catalog(cfg)
    sem = asyncio.Semaphore(cfg.concurrency)
    deadline = time.time() + max(1, cfg.duration_seconds)
    await asyncio.gather(
        *(_monkey_client(cfg, stats, catalog, deadline, sem) for _ in range(clients)), return_exceptions=True
    )
