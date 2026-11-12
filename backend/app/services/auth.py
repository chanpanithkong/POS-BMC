"""Sign-in, PIN sign-in, refresh rotation, sign-out and password flows (AUTH).

Failed attempts and lockouts are committed before the error is raised, so they
persist even though the request fails (FR-AUTH-008, FR-AUTH-011).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError, NotAuthenticated, ValidationFailed
from app.core.security import (
    create_access_token,
    hash_secret,
    needs_rehash,
    new_opaque_token,
    password_problems,
    pin_lookup,
    token_digest,
    verify_secret,
)
from app.models import LoginAttempt, OutboxEvent, PasswordResetToken, TerminalCashier, User, UserSession
from app.repositories.users import find_by_login, terminal_for_company, user_view
from app.services import audit
from app.services.principal import effective_rights

GENERIC_FAILURE = "Incorrect sign-in details"
IP_LIMIT, IP_WINDOW = 10, timedelta(minutes=15)  # proposed NFR-SEC-008 targets
PIN_LIMIT, PIN_WINDOW = 5, timedelta(minutes=5)


class RateLimited(AppError):
    status_code, code = 429, "RATE_LIMITED"


@dataclass
class IssuedSession:
    body: dict
    refresh_token: str
    refresh_expires_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


async def session_user(db: AsyncSession, user: User) -> dict:
    roles, perms, limits = await effective_rights(db, user.id)
    view = await user_view(db, user)
    codes = {r.code for r in roles}
    return {
        **view,
        "roles": [{"id": r.id, "code": r.code, "name": r.name} for r in roles],
        "permissions": sorted(perms),
        "limits": limits,
        "home_path": "/pos" if codes & {"CASHIER", "SALES"} else "/dashboard",
    }


async def _issue(db: AsyncSession, user: User, *, device: str, ip: str | None, terminal_id: uuid.UUID | None = None) -> IssuedSession:
    settings = get_settings()
    now = _now()
    absolute = now + timedelta(hours=settings.session_absolute_hours)
    refresh_expires = min(now + timedelta(days=settings.refresh_token_expire_days), absolute)
    refresh = new_opaque_token()
    session = UserSession(
        user_id=user.id, refresh_token_hash=token_digest(refresh), device=device[:200], ip_address=ip, terminal_id=terminal_id,
        created_at=now, last_seen_at=now, expires_at=refresh_expires, absolute_expires_at=absolute,
    )
    db.add(session)
    await db.flush()
    access, expires_in = create_access_token(user.id, session.id, user.company_id)
    return IssuedSession({"access_token": access, "token_type": "bearer", "expires_in": expires_in, "user": await session_user(db, user)}, refresh, refresh_expires)


async def _record_attempt(db: AsyncSession, *, username: str, ip: str | None, terminal_id: uuid.UUID | None, method: str, succeeded: bool) -> None:
    db.add(LoginAttempt(username=username[:254], ip_address=ip, terminal_id=terminal_id, method=method, succeeded=succeeded))


async def _recent_failures(db: AsyncSession, window: timedelta, **filters: object) -> int:
    query = select(func.count()).select_from(LoginAttempt).where(LoginAttempt.succeeded.is_(False), LoginAttempt.attempted_at > _now() - window)
    for column, value in filters.items():
        query = query.where(getattr(LoginAttempt, column) == value)
    return int(await db.scalar(query) or 0)


def _locked_message(user: User) -> str:
    assert user.locked_until is not None
    return f"Account locked until {user.locked_until.astimezone(UTC):%H:%M} UTC."


async def _register_failure(db: AsyncSession, user: User, ip: str | None) -> None:
    settings = get_settings()
    now = _now()
    window = timedelta(minutes=settings.login_lock_window_minutes)
    if user.first_failed_at is None or now - user.first_failed_at > window:
        user.first_failed_at, user.failed_login_count = now, 0
    user.failed_login_count += 1
    await audit.record(db, action="LOGIN_FAILED", module="AUTH", entity_type="user", entity_id=user.id, company_id=user.company_id, user_name=user.full_name, ip_address=ip)
    if user.failed_login_count >= settings.login_lock_attempts:
        user.locked_until = now + window
        await audit.record(db, action="ACCOUNT_LOCKED", module="AUTH", entity_type="user", entity_id=user.id, company_id=user.company_id, user_name=user.full_name, ip_address=ip, flagged=True)


async def login(db: AsyncSession, *, username: str, password: str, ip: str | None, device: str) -> IssuedSession:
    if ip and await _recent_failures(db, IP_WINDOW, ip_address=ip) >= IP_LIMIT:
        raise RateLimited("Too many sign-in attempts. Try again later.")
    user = await find_by_login(db, username)
    if user is None:
        await _record_attempt(db, username=username, ip=ip, terminal_id=None, method="PASSWORD", succeeded=False)
        await db.commit()
        raise NotAuthenticated(GENERIC_FAILURE)
    if user.locked_until and user.locked_until > _now():
        raise NotAuthenticated(_locked_message(user), code="ACCOUNT_LOCKED")
    if user.status != "ACTIVE" or not verify_secret(user.password_hash, password):
        await _record_attempt(db, username=username, ip=ip, terminal_id=None, method="PASSWORD", succeeded=False)
        if user.status == "ACTIVE":
            await _register_failure(db, user, ip)
        await db.commit()
        raise NotAuthenticated(GENERIC_FAILURE)
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = hash_secret(password)
    user.failed_login_count, user.first_failed_at, user.locked_until, user.last_login_at = 0, None, None, _now()
    await _record_attempt(db, username=username, ip=ip, terminal_id=None, method="PASSWORD", succeeded=True)
    issued = await _issue(db, user, device=device, ip=ip)
    await audit.record(db, action="LOGIN", module="AUTH", entity_type="user", entity_id=user.id, company_id=user.company_id, user_id=user.id, user_name=user.full_name, ip_address=ip)
    await db.commit()
    return issued


async def pin_login(db: AsyncSession, *, pin: str, terminal_id: uuid.UUID, ip: str | None) -> IssuedSession:
    terminal = await terminal_for_company(db, terminal_id)
    if terminal is None or terminal.status != "ACTIVE":
        raise NotAuthenticated("This device is not registered as a POS terminal.", code="TERMINAL_NOT_REGISTERED")
    if await _recent_failures(db, PIN_WINDOW, terminal_id=terminal_id) >= PIN_LIMIT:
        raise RateLimited("Too many PIN attempts on this terminal. Wait a few minutes.")
    user = await db.scalar(select(User).where(User.company_id == terminal.company_id, User.pin_lookup == pin_lookup(terminal.company_id, pin), User.deleted_at.is_(None)))
    if user is None or user.status != "ACTIVE" or not verify_secret(user.pin_hash, pin):
        await _record_attempt(db, username="(pin)", ip=ip, terminal_id=terminal_id, method="PIN", succeeded=False)
        await db.commit()
        raise NotAuthenticated("Incorrect PIN")
    if user.locked_until and user.locked_until > _now():
        raise NotAuthenticated(_locked_message(user), code="ACCOUNT_LOCKED")
    view = await user_view(db, user)
    if view["branch_ids"] and terminal.branch_id not in view["branch_ids"]:
        raise NotAuthenticated("You are not assigned to this branch.", code="FORBIDDEN")
    assigned = list(await db.scalars(select(TerminalCashier.user_id).where(TerminalCashier.terminal_id == terminal.id)))
    if assigned and user.id not in assigned:
        raise NotAuthenticated("You are not assigned to this terminal.", code="FORBIDDEN")
    user.last_login_at = _now()
    await _record_attempt(db, username=user.username, ip=ip, terminal_id=terminal_id, method="PIN", succeeded=True)
    issued = await _issue(db, user, device=f"Terminal {terminal.name}", ip=ip, terminal_id=terminal.id)
    await audit.record(db, action="PIN_LOGIN", module="AUTH", entity_type="user", entity_id=user.id, company_id=user.company_id, user_id=user.id, user_name=user.full_name, branch_id=terminal.branch_id, ip_address=ip)
    await db.commit()
    return issued


async def refresh(db: AsyncSession, *, refresh_token: str | None, ip: str | None) -> IssuedSession:
    if not refresh_token:
        raise NotAuthenticated("Please sign in to continue.")
    digest = token_digest(refresh_token)
    session = await db.scalar(select(UserSession).where(UserSession.refresh_token_hash == digest).with_for_update())
    if session is None:
        reused = await db.scalar(select(UserSession).where(UserSession.previous_token_hash == digest).with_for_update())
        if reused is not None and reused.revoked_at is None:
            # A rotated token came back: assume theft and end the session (refresh reuse detection).
            reused.revoked_at, reused.revoke_reason = _now(), "REFRESH_REUSE"
            user = await db.get(User, reused.user_id)
            await audit.record(db, action="REFRESH_TOKEN_REUSE", module="AUTH", entity_type="session", entity_id=reused.id, company_id=user.company_id if user else None, user_id=reused.user_id, ip_address=ip, flagged=True)
            await db.commit()
        raise NotAuthenticated("Your session has expired. Please sign in again.", code="SESSION_EXPIRED")
    now = _now()
    idle = timedelta(minutes=get_settings().session_idle_minutes)
    user = await db.get(User, session.user_id)
    if session.revoked_at or session.expires_at <= now or session.absolute_expires_at <= now or session.last_seen_at + idle <= now or user is None or user.status != "ACTIVE":
        raise NotAuthenticated("Your session has expired. Please sign in again.", code="SESSION_EXPIRED")
    new_token = new_opaque_token()
    session.previous_token_hash, session.refresh_token_hash, session.last_seen_at = digest, token_digest(new_token), now
    access, expires_in = create_access_token(user.id, session.id, user.company_id)
    body = {"access_token": access, "token_type": "bearer", "expires_in": expires_in, "user": await session_user(db, user)}
    await db.commit()
    return IssuedSession(body, new_token, session.expires_at)


async def logout(db: AsyncSession, *, session_id: uuid.UUID, user: User, ip: str | None) -> None:
    await db.execute(update(UserSession).where(UserSession.id == session_id, UserSession.revoked_at.is_(None)).values(revoked_at=_now(), revoke_reason="LOGOUT"))
    await audit.record(db, action="LOGOUT", module="AUTH", entity_type="user", entity_id=user.id, company_id=user.company_id, user_id=user.id, user_name=user.full_name, ip_address=ip)
    await db.commit()


async def revoke_user_sessions(db: AsyncSession, user_id: uuid.UUID, reason: str, keep: uuid.UUID | None = None) -> None:
    query = update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if keep:
        query = query.where(UserSession.id != keep)
    await db.execute(query.values(revoked_at=_now(), revoke_reason=reason))


def check_password(password: str, username: str) -> None:
    problems = password_problems(password, username)
    if problems:
        raise ValidationFailed("password", " ".join(problems))


async def change_password(db: AsyncSession, *, user: User, session_id: uuid.UUID, current: str, new: str) -> None:
    if not verify_secret(user.password_hash, current):
        raise ValidationFailed("current_password", "Current password is incorrect.")
    check_password(new, user.username)
    user.password_hash, user.password_changed_at = hash_secret(new), _now()
    await revoke_user_sessions(db, user.id, "PASSWORD_CHANGED", keep=session_id)
    await audit.record(db, action="PASSWORD_CHANGED", module="AUTH", entity_type="user", entity_id=user.id, company_id=user.company_id, user_id=user.id, user_name=user.full_name)
    await db.commit()


async def forgot_password(db: AsyncSession, *, email: str) -> None:
    """Always answers the same way so account existence is not revealed."""
    user = await find_by_login(db, email)
    if user is None or user.status != "ACTIVE":
        return
    token = new_opaque_token()
    db.add(PasswordResetToken(user_id=user.id, token_hash=token_digest(token), expires_at=_now() + timedelta(minutes=30)))
    # Email delivery is a worker job (Phase 8); the outbox carries what the email needs.
    db.add(OutboxEvent(event_type="PASSWORD_RESET_REQUESTED", payload={"user_id": str(user.id), "email": user.email, "token": token}))
    await audit.record(db, action="PASSWORD_RESET_REQUESTED", module="AUTH", entity_type="user", entity_id=user.id, company_id=user.company_id)
    await db.commit()


async def reset_password(db: AsyncSession, *, token: str, new: str) -> None:
    record = await db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_digest(token)).with_for_update())
    if record is None or record.used_at or record.expires_at <= _now():
        raise ValidationFailed("token", "This reset link is invalid or has expired.")
    user = await db.get(User, record.user_id)
    assert user is not None
    check_password(new, user.username)
    user.password_hash, user.password_changed_at = hash_secret(new), _now()
    user.failed_login_count, user.locked_until = 0, None
    record.used_at = _now()
    await revoke_user_sessions(db, user.id, "PASSWORD_RESET")
    await audit.record(db, action="PASSWORD_RESET", module="AUTH", entity_type="user", entity_id=user.id, company_id=user.company_id, user_id=user.id, user_name=user.full_name)
    await db.commit()
