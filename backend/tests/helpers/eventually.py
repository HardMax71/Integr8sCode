import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def eventually(
    fn: Callable[[], Awaitable[T]],
    *,
    timeout: float = 10.0,
    interval: float = 0.1,
    exceptions: tuple[type[BaseException], ...] = (AssertionError,),
) -> T:
    """Poll async `fn` until it succeeds or timeout elapses.

    Args:
        fn: Async callable to poll. Retried if it raises one of `exceptions`.
        timeout: Maximum time to wait in seconds.
        interval: Time between retries in seconds.
        exceptions: Exception types that trigger a retry.

    Returns:
        The return value of `fn` on success.

    Raises:
        The last exception raised by `fn` after timeout.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            return await fn()
        except exceptions:
            if asyncio.get_running_loop().time() >= deadline:
                raise
            await asyncio.sleep(interval)
