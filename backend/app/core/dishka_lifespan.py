from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Minimal lifespan - container.close() triggers all provider cleanup."""
    yield
    await app.state.dishka_container.close()
