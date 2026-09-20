"""Safe infrastructure errors at the ASGI boundary, including authentication I/O."""

import logging
from uuid import uuid4

from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class InfrastructureErrorsMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        started = False

        async def tracked_send(message: Message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] = [*message["headers"], (b"x-request-id", request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except (DBAPIError, PoolTimeout) as error:
            unavailable = (
                isinstance(error, (OperationalError, InterfaceError, PoolTimeout))
                or getattr(error, "connection_invalidated", False)
                or getattr(getattr(error, "orig", None), "sqlstate", None) == "25P03"
            )
            if not unavailable:
                raise  # Integrity and programming errors are not temporary outages.
            # SQL, parameters, URLs and exception messages can contain credentials.
            logger.warning(
                "database_unavailable request_id=%s method=%s error_type=%s",
                request_id,
                scope["method"],
                type(error).__name__,
            )
            if started:
                raise  # A partially sent response cannot be replaced safely.
            response = JSONResponse(
                {
                    "detail": "Service temporarily unavailable. Refresh status before retrying an action.",
                    "code": "database_unavailable",
                    "request_id": request_id,
                },
                status_code=503,
                headers={"Cache-Control": "no-store", "Retry-After": "5"},
            )
            await response(scope, receive, tracked_send)
