"""Domain errors and the standard error envelope (SRS 13.1).

Every error response has the shape
{"error": {"code": ..., "message": ..., "details": [...], "correlation_id": ...}}.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import correlation_id

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Raise from services; the handler turns it into the standard envelope."""

    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or []


class NotAuthenticated(AppError):
    status_code, code = 401, "NOT_AUTHENTICATED"


class Forbidden(AppError):
    status_code, code = 403, "FORBIDDEN"


class NotFound(AppError):
    status_code, code = 404, "NOT_FOUND"

    def __init__(self, what: str = "Record"):
        super().__init__(f"{what} not found.")


class Conflict(AppError):
    status_code, code = 409, "CONFLICT"


class InvalidStateTransition(Conflict):
    code = "INVALID_STATE_TRANSITION"


class ValidationFailed(AppError):
    status_code, code = 422, "VALIDATION_ERROR"

    def __init__(self, field: str, message: str):
        super().__init__(message, details=[{"field": field, "message": message}])


def error_body(code: str, message: str, details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or [], "correlation_id": correlation_id.get()}}


_HTTP_CODES = {401: "NOT_AUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 429: "RATE_LIMITED"}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "code": err["type"], "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(error_body("VALIDATION_ERROR", "Invalid request", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(error_body("INTERNAL_ERROR", "Something went wrong on the server."), status_code=500)
