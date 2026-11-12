"""Authentication endpoints (FR-AUTH-001, 002, 007, 008, 011, 014)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.api.deps import CurrentPrincipal, DbSession, client_ip
from app.core.config import get_settings
from app.core.exceptions import NotFound
from app.models import User, UserSession
from app.schemas.auth import (
    ApprovalGrant,
    ApprovalRequest,
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    PinLoginRequest,
    ResetPasswordRequest,
    SessionOut,
    SessionUser,
    UpdateMeRequest,
)
from app.schemas.common import ListResponse, error_responses
from app.services import approvals, audit
from app.services import auth as service
from app.services.auth import IssuedSession

router = APIRouter(prefix="/auth", tags=["Authentication"])
COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, issued: IssuedSession) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.refresh_cookie_name, issued.refresh_token, expires=issued.refresh_expires_at.astimezone(UTC), path=COOKIE_PATH,
        httponly=True, secure=settings.refresh_cookie_secure, samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.refresh_cookie_name, path=COOKIE_PATH, httponly=True, secure=settings.refresh_cookie_secure, samesite="lax")


def _refresh_cookie(request: Request) -> str | None:
    return request.cookies.get(get_settings().refresh_cookie_name)


@router.post("/login", response_model=AuthResponse, summary="Sign in with username or email and password", responses=error_responses(401, 422, 429),
             description="Returns a 15-minute access token and sets the rotating refresh token as an HttpOnly cookie. Five failures in 15 minutes lock the account for 15 minutes.")
async def login(body: LoginRequest, request: Request, response: Response, db: DbSession) -> dict:
    issued = await service.login(db, username=body.username, password=body.password, ip=client_ip(request), device=request.headers.get("user-agent", "")[:200])
    _set_refresh_cookie(response, issued)
    return issued.body


@router.post("/pin", response_model=AuthResponse, include_in_schema=False)
@router.post("/pin-login", response_model=AuthResponse, summary="Cashier PIN sign-in on a registered terminal", responses=error_responses(401, 422, 429))
async def pin_login(body: PinLoginRequest, request: Request, response: Response, db: DbSession) -> dict:
    issued = await service.pin_login(db, pin=body.pin, terminal_id=body.terminal_id, ip=client_ip(request))
    _set_refresh_cookie(response, issued)
    return issued.body


@router.post("/refresh", response_model=AuthResponse, summary="Rotate the refresh token and issue a new access token", responses=error_responses(401),
             description="Reads the refresh cookie. Reusing an already-rotated token ends the session and is flagged in the audit log.")
async def refresh(request: Request, response: Response, db: DbSession) -> dict:
    try:
        issued = await service.refresh(db, refresh_token=_refresh_cookie(request), ip=client_ip(request))
    except Exception:
        _clear_refresh_cookie(response)
        raise
    _set_refresh_cookie(response, issued)
    return issued.body


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out and revoke this session", responses=error_responses(401))
async def logout(request: Request, response: Response, principal: CurrentPrincipal, db: DbSession) -> Response:
    user = await db.get(User, principal.user_id)
    assert user is not None
    await service.logout(db, session_id=principal.session_id, user=user, ip=client_ip(request))
    response.status_code = status.HTTP_204_NO_CONTENT
    _clear_refresh_cookie(response)
    return response


@router.get("/me", response_model=SessionUser, summary="Current user with roles, permissions, limits and scope", responses=error_responses(401))
async def me(principal: CurrentPrincipal, db: DbSession) -> dict:
    user = await db.get(User, principal.user_id)
    assert user is not None
    return await service.session_user(db, user)


@router.patch("/me", response_model=SessionUser, summary="Update own name, phone or language", responses=error_responses(401, 422))
async def update_me(body: UpdateMeRequest, principal: CurrentPrincipal, db: DbSession) -> dict:
    user = await db.get(User, principal.user_id)
    assert user is not None
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(user, field, value)
    await audit.record(db, action="PROFILE_UPDATED", module="AUTH", entity_type="user", entity_id=user.id, company_id=user.company_id, user_id=user.id, user_name=user.full_name, after=changes)
    await db.commit()
    return await service.session_user(db, user)


@router.post("/change-password", response_model=MessageResponse, summary="Change own password; other sessions are signed out", responses=error_responses(401, 422))
async def change_password(body: ChangePasswordRequest, principal: CurrentPrincipal, db: DbSession) -> dict:
    user = await db.get(User, principal.user_id)
    assert user is not None
    await service.change_password(db, user=user, session_id=principal.session_id, current=body.current_password, new=body.new_password)
    return {"message": "Password changed. Other sessions have been signed out."}


@router.post("/forgot-password", response_model=MessageResponse, summary="Request a password reset link", responses=error_responses(422),
             description="Always returns the same message so it does not reveal whether an account exists. Delivery is handled by the notification worker.")
async def forgot_password(body: ForgotPasswordRequest, db: DbSession) -> dict:
    await service.forgot_password(db, email=body.email)
    return {"message": "If an account exists for this email, a reset link has been sent."}


@router.post("/reset-password", response_model=MessageResponse, summary="Set a new password with a reset token", responses=error_responses(422))
async def reset_password(body: ResetPasswordRequest, db: DbSession) -> dict:
    await service.reset_password(db, token=body.token, new=body.new_password)
    return {"message": "Password updated. Please sign in."}


@router.post("/approvals/verify", response_model=ApprovalGrant, summary="Supervisor PIN approval for a guarded action", responses=error_responses(401, 403, 422),
             description="The approver must hold the matching permission and limit, and be a different user unless reduced separation-of-duties mode is on. Returns a single-use token valid for two minutes.")
async def verify_approval(body: ApprovalRequest, principal: CurrentPrincipal, db: DbSession) -> dict:
    return await approvals.verify_pin(db, principal, pin=body.pin, action=body.action, amount=body.amount)


async def _session_rows(db: DbSession, principal: CurrentPrincipal, all_users: bool) -> list[dict]:
    query = select(UserSession, User.full_name).join(User, User.id == UserSession.user_id).where(UserSession.revoked_at.is_(None), User.company_id == principal.company_id)
    if not all_users:
        query = query.where(UserSession.user_id == principal.user_id)
    rows = await db.execute(query.order_by(UserSession.last_seen_at.desc()))
    return [{**{c: getattr(s, c) for c in ("id", "user_id", "device", "ip_address", "created_at", "last_seen_at", "expires_at")}, "user_name": name, "current": s.id == principal.session_id} for s, name in rows]


@router.get("/sessions", response_model=ListResponse[SessionOut], summary="Active sessions; administrators see every user's", responses=error_responses(401))
async def list_sessions(principal: CurrentPrincipal, db: DbSession, all_users: bool = False) -> dict:
    if all_users:
        principal.require("users.user.manage")
    rows = await _session_rows(db, principal, all_users)
    return {"items": rows, "total": len(rows)}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a session", responses=error_responses(401, 403, 404))
async def revoke_session(session_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> Response:
    session = await db.get(UserSession, session_id)
    owner = await db.get(User, session.user_id) if session else None
    if session is None or owner is None or owner.company_id != principal.company_id:
        raise NotFound("Session")
    if session.user_id != principal.user_id:
        principal.require("users.user.manage")
    if session.revoked_at is None:
        session.revoked_at, session.revoke_reason = datetime.now(UTC), "REVOKED"
        await audit.record(db, action="SESSION_REVOKED", module="AUTH", entity_type="session", entity_id=session.id, company_id=principal.company_id, user_id=principal.user_id, user_name=principal.full_name, after={"user_id": str(session.user_id)})
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



approvals_router = APIRouter(tags=["Authentication"])
approvals_router.add_api_route("/approvals/verify", verify_approval, methods=["POST"], response_model=ApprovalGrant, include_in_schema=False)
