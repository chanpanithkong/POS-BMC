"""Shared schema pieces: strict command models, list envelope, error model."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Command(BaseModel):
    """Base for request bodies: unknown fields are rejected (NFR-SEC-005)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ListResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    next_cursor: str | None = None


class ErrorDetail(BaseModel):
    field: str | None = None
    code: str | None = None
    message: str


class ErrorBody(BaseModel):
    code: str = Field(examples=["VALIDATION_ERROR"])
    message: str
    details: list[dict[str, Any]] = []
    correlation_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


def error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI documentation for the standard error envelope."""
    text = {400: "Bad request", 401: "Not signed in or session expired", 403: "Missing permission, limit exceeded or separation of duties", 404: "Not found or outside your scope", 409: "State, version or idempotency conflict", 422: "Validation or business rule failed", 429: "Too many attempts"}
    return {code: {"model": ErrorResponse, "description": text.get(code, "Error")} for code in codes}
