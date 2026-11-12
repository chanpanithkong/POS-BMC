"""Sign-in, lockout, refresh rotation and reuse detection, sign-out, PIN, password flows."""

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AuditLog, OutboxEvent
from tests.conftest import LoginFn, World, new_password

pytestmark = pytest.mark.db
COOKIE = get_settings().refresh_cookie_name


async def _login(client: httpx.AsyncClient, username: str, password: str) -> httpx.Response:
    return await client.post("/api/v1/auth/login", json={"username": username, "password": password})


async def test_login_returns_token_cookie_and_effective_rights(client: httpx.AsyncClient, world: World):
    account = await world.user("CASHIER", branches=[world.branch_a])
    response = await _login(client, account.user.username, account.password)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 900
    user = body["user"]
    assert user["home_path"] == "/pos"
    assert "pos.sale.create" in user["permissions"] and "users.user.manage" not in user["permissions"]
    assert user["limits"]["discount_pct"] == "5"
    assert user["branch_ids"] == [str(world.branch_a.id)]
    cookie = response.headers["set-cookie"]
    assert COOKIE in cookie and "HttpOnly" in cookie and "Path=/api/v1/auth" in cookie and "samesite=lax" in cookie.lower()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["id"] == str(account.user.id)


async def test_login_by_email_is_case_insensitive(client: httpx.AsyncClient, world: World):
    account = await world.user("READONLY")
    assert (await _login(client, account.user.email.upper(), account.password)).status_code == 200


async def test_wrong_password_and_unknown_user_look_the_same(client: httpx.AsyncClient, world: World):
    account = await world.user("READONLY")
    wrong = await _login(client, account.user.username, "Wrong-password-123")
    unknown = await _login(client, "nobody-" + uuid.uuid4().hex[:8], "Wrong-password-123")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_five_failures_lock_the_account(client: httpx.AsyncClient, world: World):
    account = await world.user("READONLY")
    for _ in range(5):
        assert (await _login(client, account.user.username, "Wrong-password-123")).status_code == 401
    locked = await _login(client, account.user.username, account.password)
    assert locked.status_code == 401
    assert locked.json()["error"]["code"] == "ACCOUNT_LOCKED"
    flagged = await world.db.scalar(select(AuditLog).where(AuditLog.entity_id == str(account.user.id), AuditLog.action == "ACCOUNT_LOCKED"))
    assert flagged is not None and flagged.flagged


async def test_admin_unlock_restores_sign_in(client: httpx.AsyncClient, world: World, login: LoginFn):
    admin = await world.user("SYSADMIN")
    headers = await login(admin)
    account = await world.user("READONLY")
    for _ in range(5):
        await _login(client, account.user.username, "Wrong-password-123")
    assert (await client.post(f"/api/v1/users/{account.user.id}/unlock", headers=headers)).status_code == 200
    assert (await _login(client, account.user.username, account.password)).status_code == 200


async def test_inactive_user_cannot_sign_in(client: httpx.AsyncClient, world: World):
    account = await world.user("READONLY")
    account.user.status = "INACTIVE"
    await world.db.commit()
    assert (await _login(client, account.user.username, account.password)).status_code == 401


async def test_refresh_rotates_and_reuse_ends_the_session(client: httpx.AsyncClient, world: World):
    account = await world.user("READONLY")
    first = await _login(client, account.user.username, account.password)
    old_refresh = first.cookies[COOKIE]

    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    new_refresh = rotated.cookies[COOKIE]
    assert new_refresh != old_refresh

    client.cookies.set(COOKIE, old_refresh, path="/api/v1/auth")
    reused = await client.post("/api/v1/auth/refresh")
    assert reused.status_code == 401

    # The whole session is gone, including the legitimately rotated token and the access token.
    client.cookies.set(COOKIE, new_refresh, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {rotated.json()['access_token']}"})).status_code == 401
    event = await world.db.scalar(select(AuditLog).where(AuditLog.action == "REFRESH_TOKEN_REUSE", AuditLog.user_id == account.user.id))
    assert event is not None and event.flagged


async def test_refresh_without_cookie_is_401(client: httpx.AsyncClient):
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_revokes_access_and_refresh(client: httpx.AsyncClient, world: World, login: LoginFn):
    account = await world.user("READONLY")
    headers = await login(account)
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_pin_login_on_registered_terminal(client: httpx.AsyncClient, world: World):
    account = await world.user("CASHIER", branches=[world.branch_a], pin="4821")
    ok = await client.post("/api/v1/auth/pin-login", json={"pin": "4821", "terminal_id": str(world.terminal.id)})
    assert ok.status_code == 200 and ok.json()["user"]["id"] == str(account.user.id)
    wrong = await client.post("/api/v1/auth/pin-login", json={"pin": "4822", "terminal_id": str(world.terminal.id)})
    assert wrong.status_code == 401
    unknown_terminal = await client.post("/api/v1/auth/pin-login", json={"pin": "4821", "terminal_id": str(uuid.uuid4())})
    assert unknown_terminal.json()["error"]["code"] == "TERMINAL_NOT_REGISTERED"


async def test_pin_login_refused_outside_assigned_branch(client: httpx.AsyncClient, world: World):
    await world.user("CASHIER", branches=[world.branch_b], pin="7392")
    response = await client.post("/api/v1/auth/pin-login", json={"pin": "7392", "terminal_id": str(world.terminal.id)})
    assert response.status_code == 401


async def test_change_password_signs_out_other_sessions(client: httpx.AsyncClient, world: World, login: LoginFn):
    account = await world.user("READONLY")
    other_session = await login(account)
    this_session = await login(account)
    new = new_password()
    response = await client.post("/api/v1/auth/change-password", headers=this_session, json={"current_password": account.password, "new_password": new})
    assert response.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=this_session)).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=other_session)).status_code == 401
    assert (await _login(client, account.user.username, new)).status_code == 200


async def test_change_password_enforces_policy(client: httpx.AsyncClient, world: World, login: LoginFn):
    account = await world.user("READONLY")
    headers = await login(account)
    response = await client.post("/api/v1/auth/change-password", headers=headers, json={"current_password": account.password, "new_password": "short"})
    assert response.status_code == 422


async def test_forgot_and_reset_password(client: httpx.AsyncClient, world: World):
    account = await world.user("READONLY")
    known = await client.post("/api/v1/auth/forgot-password", json={"email": account.user.email})
    unknown = await client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert known.json() == unknown.json()
    event = await world.db.scalar(
        select(OutboxEvent).where(OutboxEvent.event_type == "PASSWORD_RESET_REQUESTED", OutboxEvent.payload["user_id"].astext == str(account.user.id))
    )
    assert event is not None
    token = event.payload["token"]
    new = new_password()
    assert (await client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": new})).status_code == 200
    assert (await client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": new_password()})).status_code == 422
    assert (await _login(client, account.user.username, new)).status_code == 200


async def test_malformed_terminal_header_does_not_break_back_office(client: httpx.AsyncClient, world: World, login: LoginFn):
    """A stale device id (for example one saved by the frontend's mock mode) is treated as no terminal."""
    headers = {**await login(await world.user("CASHIER", branches=[world.branch_a])), "X-Terminal-Id": "term-tk1"}
    assert (await client.get("/api/v1/branches", headers=headers)).status_code == 200
    pos = await client.get("/api/v1/sales/current", headers=headers)
    assert pos.status_code == 409 and pos.json()["error"]["code"] == "TERMINAL_NOT_REGISTERED"
