import asyncio
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


async def eventually(
    fn: Callable[[], Awaitable[T]] | Callable[[], T],
    *,
    timeout: float = 10.0,
    interval: float = 0.1,
    exceptions: tuple[type[BaseException], ...] = (AssertionError,),
) -> T:
    """Polls `fn` until it succeeds or timeout elapses.

    - `fn` may be sync or async. If it raises one of `exceptions`, it is retried.
    - Returns the value of `fn` on success.
    - Raises the last exception after timeout.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    last_exc: BaseException | None = None
    while True:
        try:
            res = fn()
            if asyncio.iscoroutine(res):
                return await res  # type: ignore[return-value]
            return res  # type: ignore[return-value]
        except exceptions as exc:  # type: ignore[misc]
            last_exc = exc
            if asyncio.get_running_loop().time() >= deadline:
                raise
            await asyncio.sleep(interval)

