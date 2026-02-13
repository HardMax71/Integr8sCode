from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import HTTPException, Request

from app.domain.user import User
from app.services.auth_service import AuthService


async def check_request_size(request: Request) -> None:
    """Reject requests whose body exceeds MAX_REQUEST_SIZE_MB from settings.

    Two-phase check:
    1. Content-Length header — rejects known-oversized requests without any I/O.
    2. Streaming read with cap — rejects as soon as accumulated bytes exceed the
       limit, so a missing or dishonest Content-Length cannot force the full
       payload into memory.

    After a successful check the body is cached on ``request._body`` so that
    downstream calls to ``request.body()`` return the already-read bytes
    (same attribute Starlette uses internally for caching).
    """
    settings = request.app.state.settings
    max_bytes: int = settings.MAX_REQUEST_SIZE_MB * 1024 * 1024
    detail = f"Request too large. Maximum size is {settings.MAX_REQUEST_SIZE_MB}MB"

    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > max_bytes:
        raise HTTPException(status_code=413, detail=detail)

    received = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        received += len(chunk)
        if received > max_bytes:
            raise HTTPException(status_code=413, detail=detail)
        chunks.append(chunk)
    request._body = b"".join(chunks)


@inject
async def current_user(request: Request, auth_service: FromDishka[AuthService]) -> User:
    """Get authenticated user."""
    return await auth_service.get_current_user(request)


@inject
async def admin_user(request: Request, auth_service: FromDishka[AuthService]) -> User:
    """Get authenticated admin user."""
    return await auth_service.get_admin(request)
