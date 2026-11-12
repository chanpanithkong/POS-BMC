"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import dispose_engine
from app.middleware.correlation import CorrelationIdMiddleware

DESCRIPTION = """
REST API for the POS and Inventory Management System (PIMS-SRS-001).

**Authentication.** Send `Authorization: Bearer <access token>`. Tokens come from `POST /auth/login`,
which also sets an HttpOnly refresh cookie used by `POST /auth/refresh`.

**Errors.** Every error returns `{"error": {"code", "message", "details", "correlation_id"}}`.

**Money and quantities** are decimal strings. The server calculates every price, total, balance and status;
client-supplied totals are ignored.

**Idempotency.** State-changing POS, payment, receiving, transfer and posting requests take an `Idempotency-Key` header.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=DESCRIPTION,
        openapi_url="/api/v1/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-Match", "X-Terminal-Id", "X-Correlation-Id"],
        expose_headers=["X-Correlation-Id"],
    )
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
