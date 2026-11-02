"""Limit actual request bytes before JSON parsing (including chunked requests)."""
from starlette.responses import JSONResponse


class RequestSizeLimit:
    def __init__(self, app, max_bytes=12_000_000):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            part = message.get("body", b"")
            size += len(part)
            if size > self.max_bytes:
                return await JSONResponse({"detail": "Request is too large."},413)(scope,receive,send)
            chunks.append(part)
            if not message.get("more_body",False):
                break
        body = b"".join(chunks)
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type":"http.request","body":body,"more_body":False}
            return await receive()

        await self.app(scope,bounded_receive,send)
