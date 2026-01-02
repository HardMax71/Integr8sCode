from __future__ import annotations

from types import TracebackType
from typing import Self


class LifecycleEnabled:
    """Base class for services with async lifecycle management.

    Usage:
        async with MyService() as service:
            # service is running
        # service is stopped

    Subclasses override _on_start() and _on_stop() for their logic.
    Base class handles idempotency and context manager protocol.

    For internal component cleanup, use aclose() which follows Python's
    standard async cleanup pattern (like aiofiles, aiohttp).
    """

    def __init__(self) -> None:
        self._lifecycle_started: bool = False

    async def _on_start(self) -> None:
        """Override with startup logic. Called once on enter."""
        pass

    async def _on_stop(self) -> None:
        """Override with cleanup logic. Called once on exit."""
        pass

    async def aclose(self) -> None:
        """Close the service. For internal component cleanup.

        Mirrors Python's standard aclose() pattern (like aiofiles, aiohttp).
        Idempotent - safe to call multiple times.
        """
        if not self._lifecycle_started:
            return
        self._lifecycle_started = False
        await self._on_stop()

    @property
    def is_running(self) -> bool:
        """Check if service is currently running."""
        return self._lifecycle_started

    async def __aenter__(self) -> Self:
        if self._lifecycle_started:
            return self  # Already started, idempotent
        await self._on_start()
        self._lifecycle_started = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
