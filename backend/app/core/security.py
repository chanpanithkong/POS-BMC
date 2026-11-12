"""Password and PIN hashing (Argon2id), access tokens (JWT) and opaque token helpers."""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id with library defaults (FR-AUTH-004)

# Shortest password the policy accepts (proposed 12 characters, SRS 6.1).
PASSWORD_MIN_LENGTH = 12


def hash_secret(value: str) -> str:
    return _hasher.hash(value)


def verify_secret(stored_hash: str | None, value: str) -> bool:
    if not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, value)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def password_problems(password: str, username: str = "") -> list[str]:
    problems = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
    if username and username.lower() in password.lower():
        problems.append("Password must not contain the username.")
    if len(set(password)) < 5:
        problems.append("Password is too repetitive.")
    return problems


def pin_problems(pin: str) -> list[str]:
    if not pin.isdigit() or not 4 <= len(pin) <= 6:
        return ["PIN must be 4 to 6 digits."]
    if pin in "0123456789" or pin in "9876543210" or len(set(pin)) == 1:
        return ["PIN must not be sequential or repeated."]
    return []


def pin_lookup(company_id: uuid.UUID, pin: str) -> str:
    """Deterministic keyed digest so a PIN can be found without storing it (the Argon2 hash is still verified)."""
    key = get_settings().secret_key.get_secret_value().encode()
    return hmac.new(key, f"{company_id}:{pin}".encode(), hashlib.sha256).hexdigest()


def new_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    company_id: uuid.UUID
    expires_at: datetime


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID, company_id: uuid.UUID) -> tuple[str, int]:
    settings = get_settings()
    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "sid": str(session_id), "cid": str(company_id), "iat": now, "exp": now + lifetime, "typ": "access"}
    token = jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> AccessClaims | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key.get_secret_value(), algorithms=[settings.jwt_algorithm], options={"require": ["exp", "sub", "sid", "cid"]})
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    return AccessClaims(uuid.UUID(payload["sub"]), uuid.UUID(payload["sid"]), uuid.UUID(payload["cid"]), datetime.fromtimestamp(payload["exp"], UTC))
