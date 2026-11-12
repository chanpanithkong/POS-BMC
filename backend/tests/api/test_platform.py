"""Health, error envelope, correlation IDs, CORS and API docs."""

import uuid

import httpx
import pytest

pytestmark = pytest.mark.db


async def test_health_reports_database(client: httpx.AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_correlation_id_generated_and_echoed(client: httpx.AsyncClient):
    generated = (await client.get("/api/v1/health")).headers["x-correlation-id"]
    assert uuid.UUID(generated)
    supplied = str(uuid.uuid4())
    assert (await client.get("/api/v1/health", headers={"X-Correlation-Id": supplied})).headers["x-correlation-id"] == supplied


async def test_unsafe_correlation_id_is_replaced(client: httpx.AsyncClient):
    response = await client.get("/api/v1/health", headers={"X-Correlation-Id": "bad id\r\nx: y"})
    assert uuid.UUID(response.headers["x-correlation-id"])


async def test_unknown_route_uses_error_envelope(client: httpx.AsyncClient):
    response = await client.get("/api/v1/nope", headers={"X-Correlation-Id": "abc-123"})
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "NOT_FOUND" and body["correlation_id"] == "abc-123" and body["details"] == []


async def test_validation_error_lists_fields(client: httpx.AsyncClient):
    response = await client.post("/api/v1/auth/login", json={"username": "a"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert any(d["field"] == "password" for d in error["details"])


async def test_unknown_fields_are_rejected(client: httpx.AsyncClient):
    response = await client.post("/api/v1/auth/login", json={"username": "a", "password": "b", "is_admin": True})
    assert response.status_code == 422
    assert any(d["field"] == "is_admin" for d in response.json()["error"]["details"])


async def test_missing_token_is_401_envelope(client: httpx.AsyncClient):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


async def test_garbage_token_is_rejected(client: httpx.AsyncClient):
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


async def test_cors_allows_the_frontend_only(client: httpx.AsyncClient):
    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,idempotency-key"}
    ok = await client.options("/api/v1/auth/login", headers={"Origin": "http://localhost:3000", **preflight})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert ok.headers["access-control-allow-credentials"] == "true"
    denied = await client.options("/api/v1/auth/login", headers={"Origin": "http://evil.example", **preflight})
    assert "access-control-allow-origin" not in denied.headers


async def test_docs_and_schema_are_served(client: httpx.AsyncClient):
    assert (await client.get("/docs")).status_code == 200
    assert (await client.get("/redoc")).status_code == 200
    schema = (await client.get("/api/v1/openapi.json")).json()
    assert "/api/v1/auth/login" in schema["paths"]
