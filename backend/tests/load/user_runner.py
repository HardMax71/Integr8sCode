from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Callable

from .config import LoadConfig
from .http_client import APIClient, APIUser
from .stats import StatsCollector


@dataclass
class UserTask:
    name: str
    weight: int
    fn: Callable[[APIClient], asyncio.Future]


async def _flow_execute_and_get_result(c: APIClient) -> None:
    # 50% valid, 50% invalid
    script = c.random_script(valid=(random.random() < 0.5))
    status, body = await c.execute(script)
    if status != 200:
        return
    exec_id = body.get("execution_id")
    if not exec_id:
        return
    # choose SSE or GET
    if random.random() < 0.6:
        await c.sse_execution(exec_id, max_seconds=8.0)
    else:
        # poll a few times with small delay
        for _ in range(5):
            r = await c.result(exec_id)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                try:
                    if r.json().get("status") in ("completed", "failed", "timeout", "cancelled"):
                        break
                except Exception:
                    pass
            await asyncio.sleep(0.5)


async def _flow_events_and_history(c: APIClient) -> None:
    # Fetch a random execution id from events (if any)
    r = await c._request("GET", c.cfg.api("/events/user?limit=10"))
    exec_id = None
    try:
        data = r.json()
        for ev in data.get("events", []):
            agg = ev.get("aggregate_id")
            if agg:
                exec_id = agg
                break
    except Exception:
        pass
    if exec_id:
        await c.execution_events(exec_id)


async def _flow_saved_scripts(c: APIClient) -> None:
    name = f"script-{int(time.time() * 1000)}"
    r = await c.create_script(name, c.random_script(True))
    script_id = None
    try:
        script_id = r.json().get("script_id")
    except Exception:
        pass
    await c.list_scripts()
    if script_id:
        await c.update_script(script_id, name + "-u", c.random_script(True))
        await c.delete_script(script_id)


async def _flow_settings_and_notifications(c: APIClient) -> None:
    await c.get_settings()
    await c.update_theme()
    await c.list_notifications()
    if random.random() < 0.5:
        await c.mark_all_read()


import time


async def run_user_swarm(cfg: LoadConfig, stats: StatsCollector, clients: int) -> None:
    tasks: list[asyncio.Task] = []
    sem = asyncio.Semaphore(cfg.concurrency)
    deadline = time.time() + max(1, cfg.duration_seconds)

    user_tasks: list[UserTask] = [
        UserTask("execute_and_get_result", 5, _flow_execute_and_get_result),
        UserTask("events_and_history", 2, _flow_events_and_history),
        UserTask("saved_scripts", 2, _flow_saved_scripts),
        UserTask("settings_and_notifications", 2, _flow_settings_and_notifications),
    ]

    population: list[UserTask] = []
    for t in user_tasks:
        population.extend([t] * t.weight)

    async def one_client(idx: int) -> None:
        c = APIClient(cfg, stats)
        try:
            # register/login
            uname = f"{cfg.user_prefix}_{idx}_{int(time.time())}"
            user = APIUser(username=uname, email=f"{uname}@{cfg.user_domain}", password=cfg.user_password)
            if cfg.auto_register_users:
                await c.register(user)
            ok = await c.login(user.username, user.password)
            if not ok:
                return
            # basic /auth/me to ensure session
            await c.me()
            # run random tasks until deadline
            while time.time() < deadline:
                t = random.choice(population)
                await t.fn(c)
                await asyncio.sleep(0)
        finally:
            await c.close()

    for i in range(clients):
        await sem.acquire()

        async def _spawn(j: int) -> None:
            try:
                await one_client(j)
            finally:
                sem.release()

        tasks.append(asyncio.create_task(_spawn(i)))

    await asyncio.gather(*tasks, return_exceptions=True)
