from sse_starlette.sse import EventSourceResponse


class SSEResponse(EventSourceResponse):
    """Workaround: sse-starlette sets media_type only in __init__, not as a
    class attribute.  FastAPI reads the class attribute for OpenAPI generation,
    so without this subclass every SSE endpoint shows application/json."""

    media_type = "text/event-stream"
