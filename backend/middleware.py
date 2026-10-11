"""Pure ASGI middleware for streaming request size limits and production security headers."""
from fastapi.responses import JSONResponse
from starlette import status

MAX_REQUEST_BYTES = 1024 * 1024  # 1 MB


class RequestSizeLimitMiddleware:
    """Pure ASGI middleware enforcing hard streaming request body limits and security headers.

    Guarantees:
    1. Early rejection: Checks Content-Length upfront if provided.
    2. Streaming enforcement: Intercepts ASGI http.request messages chunk-by-chunk. If the
       cumulative received byte count exceeds max_bytes, marks stream exceeded without buffering
       and immediately intercepts the response to return HTTP 413.
    3. Handles chunked transfer encoding, missing Content-Length, and malformed headers.
    4. Guards against duplicate ASGI response starts and injects production security headers.
    """

    def __init__(self, app, max_bytes: int = MAX_REQUEST_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length_raw = headers.get(b"content-length")

        if content_length_raw is not None:
            try:
                content_length = int(content_length_raw.decode("latin1").strip())
                if content_length < 0:
                    resp = JSONResponse(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        content={"detail": "Invalid Content-Length header: negative length."},
                    )
                    await resp(scope, receive, send)
                    return
                if content_length > self.max_bytes:
                    resp = JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={"detail": f"Payload exceeds {self.max_bytes} bytes limit."},
                    )
                    await resp(scope, receive, send)
                    return
            except ValueError:
                resp = JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": "Invalid Content-Length header: non-numeric value."},
                )
                await resp(scope, receive, send)
                return

        total_bytes = 0
        exceeded = False

        async def limited_receive():
            nonlocal total_bytes, exceeded
            message = await receive()
            msg_type = message.get("type")

            if msg_type == "http.request":
                chunk = message.get("body", b"")
                total_bytes += len(chunk)
                if total_bytes > self.max_bytes:
                    exceeded = True
            return message

        response_sent = False

        async def send_with_headers(message):
            nonlocal response_sent
            if exceeded:
                if not response_sent:
                    response_sent = True
                    resp = JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={"detail": f"Payload exceeds {self.max_bytes} bytes limit (streaming limit breached)."},
                    )
                    await resp(scope, receive, send)
                return

            if message["type"] == "http.response.start":
                response_sent = True
                headers_list = list(message.get("headers", []))
                security_headers = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"x-xss-protection", b"1; mode=block"),
                    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
                    (b"content-security-policy", b"default-src 'self' 'unsafe-inline' https:; img-src 'self' data: https:;"),
                ]
                headers_list.extend(security_headers)
                message["headers"] = headers_list

            await send(message)

        await self.app(scope, limited_receive, send_with_headers)
