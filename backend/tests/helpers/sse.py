import asyncio
import json
from typing import Any, AsyncIterator, Iterable

from httpx import AsyncClient


async def stream_sse(client: AsyncClient, url: str, timeout: float = 20.0) -> AsyncIterator[dict[str, Any]]:
    """Yield parsed SSE event dicts from the given URL within a timeout.

    Expects lines in the form "data: {...json...}" and ignores keepalives.
    """
    async with asyncio.timeout(timeout):
        async with client.stream("GET", url) as resp:
            assert resp.status_code == 200, f"SSE stream {url} returned {resp.status_code}"
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    ev = json.loads(payload)
                except Exception:
                    continue
                yield ev


async def wait_for_event_type(
    client: AsyncClient,
    url: str,
    wanted_types: Iterable[str],
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Return first event whose type/event_type is in wanted_types, otherwise timeout."""
    wanted = {str(t).lower() for t in wanted_types}
    async for ev in stream_sse(client, url, timeout=timeout):
        et = str(ev.get("type") or ev.get("event_type") or "").lower()
        if et in wanted:
            return ev
    raise TimeoutError(f"No event of types {wanted} seen on {url} within {timeout}s")


async def wait_for_execution_terminal(
    client: AsyncClient,
    execution_id: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    terminal = {"execution_completed", "result_stored", "execution_failed", "execution_timeout", "execution_cancelled"}
    url = f"/api/v1/events/executions/{execution_id}"
    return await wait_for_event_type(client, url, terminal, timeout=timeout)


async def wait_for_execution_running(
    client: AsyncClient,
    execution_id: str,
    timeout: float = 15.0,
) -> dict[str, Any]:
    running = {"execution_running", "execution_started", "execution_scheduled", "execution_queued"}
    url = f"/api/v1/events/executions/{execution_id}"
    return await wait_for_event_type(client, url, running, timeout=timeout)

