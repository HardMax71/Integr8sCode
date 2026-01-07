"""Async polling helper for E2E tests."""

import asyncio
from typing import Any

from app.domain.enums.execution import ExecutionStatus
from httpx import AsyncClient


async def poll_until_terminal(
    client: AsyncClient, execution_id: str, *, timeout: float = 30.0
) -> dict[str, Any]:
    """Poll result endpoint until execution reaches terminal state."""
    async with asyncio.timeout(timeout):
        while True:
            r = await client.get(f"/api/v1/result/{execution_id}")
            if r.status_code == 200:
                data: dict[str, Any] = r.json()
                if ExecutionStatus(data["status"]).is_terminal:
                    return data
            await asyncio.sleep(0.5)
