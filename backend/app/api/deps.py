"""Request dependencies: database session, current principal, permission checks."""

import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotAuthenticated
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import UserSession
from app.services.principal import Principal, load_principal

DbSession = Annotated[AsyncSession, Depends(get_db)]
_bearer = HTTPBearer(auto_error=False, description="Access token from POST /auth/login")


def _terminal_id(value: str | None) -> uuid.UUID | None:
    """An unknown or malformed X-Terminal-Id means "not a registered terminal": back-office calls
    still work, and POS calls get TERMINAL_NOT_REGISTERED instead of a validation error everywhere."""
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


async def current_principal(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    x_terminal_id: Annotated[str | None, Header()] = None,
) -> Principal:
    if credentials is None:
        raise NotAuthenticated("Please sign in to continue.")
    claims = decode_access_token(credentials.credentials)
    if claims is None:
        raise NotAuthenticated("Your session has expired. Please sign in again.", code="SESSION_EXPIRED")
    session = await db.get(UserSession, claims.session_id)
    now = datetime.now(UTC)
    idle = timedelta(minutes=get_settings().session_idle_minutes)
    if session is None or session.revoked_at or session.absolute_expires_at <= now or session.last_seen_at + idle <= now:
        raise NotAuthenticated("Your session has expired. Please sign in again.", code="SESSION_EXPIRED")
    principal = await load_principal(db, claims.user_id, claims.session_id, terminal_id=_terminal_id(x_terminal_id))
    if principal is None:
        raise NotAuthenticated("Your account is not active.", code="SESSION_EXPIRED")
    if now - session.last_seen_at > timedelta(minutes=1):
        session.last_seen_at = now
        await db.commit()
    request.state.principal = principal
    return principal


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require(*any_of: str) -> Callable[..., Coroutine[Any, Any, Principal]]:
    """Dependency: the signed-in user must hold at least one of these permissions (FR-AUTH-009)."""

    async def check(principal: CurrentPrincipal) -> Principal:
        principal.require(*any_of)
        return principal

    check.__doc__ = f"Requires one of: {', '.join(any_of)}"
    return check


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
