from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.domain.enums import ExecutionStatus

from .config import LoadConfig
from .http_client import APIClient, APIUser
from .stats import StatsCollector


@dataclass
class UserTask:
    name: str
    weight: int
    fn: Callable[[APIClient], Awaitable[None]]


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
                    if ExecutionStatus(r.json()["status"]).is_terminal:
                        break
                except Exception:
                    pass
            await asyncio.sleep(0.5)


async def _flow_events_and_history(c: APIClient) -> None:
    r = await c.user_executions(limit=10)
    if r.status_code != 200:
        return
    executions = r.json().get("executions", [])
    if executions:
        await c.execution_events(random.choice(executions)["execution_id"])


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


async def _user_client(
    cfg: LoadConfig,
    stats: StatsCollector,
    idx: int,
    population: list[UserTask],
    deadline: float,
    sem: asyncio.Semaphore,
) -> None:
    async with sem, APIClient(cfg, stats) as c:
        uname = f"{cfg.user_prefix}_{idx}_{int(time.time())}"
        user = APIUser(username=uname, email=f"{uname}@{cfg.user_domain}", password=cfg.user_password)
        if cfg.auto_register_users:
            await c.register(user)
        if not await c.login(user.username, user.password):
            return
        await c.me()
        while time.time() < deadline:
            await random.choice(population).fn(c)
            await asyncio.sleep(0)


async def run_user_swarm(cfg: LoadConfig, stats: StatsCollector, clients: int) -> None:
    sem = asyncio.Semaphore(cfg.concurrency)
    deadline = time.time() + max(1, cfg.duration_seconds)
    user_tasks: list[UserTask] = [
        UserTask("execute_and_get_result", 5, _flow_execute_and_get_result),
        UserTask("events_and_history", 2, _flow_events_and_history),
        UserTask("saved_scripts", 2, _flow_saved_scripts),
        UserTask("settings_and_notifications", 2, _flow_settings_and_notifications),
    ]
    population = [task for task in user_tasks for _ in range(task.weight)]
    await asyncio.gather(
        *(_user_client(cfg, stats, idx, population, deadline, sem) for idx in range(clients)), return_exceptions=True
    )
