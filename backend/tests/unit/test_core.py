"""Pure unit tests: no database."""

import time
import uuid

import jwt
import pytest

from app.core.config import Settings, get_settings
from app.core.permissions import DEFAULT_ROLES, FRONTEND_KEY_MAP, PERMISSIONS, SOD_CONFLICTS
from app.core.security import create_access_token, decode_access_token, hash_secret, password_problems, pin_lookup, pin_problems, token_digest, verify_secret
from app.services.users import sod_conflicts
from app.utils.ids import uuid7


def test_uuid7_is_version_7_and_time_ordered():
    ids = [uuid7() for _ in range(20000)]
    assert all(i.version == 7 for i in ids)
    assert ids == sorted(ids, key=lambda u: u.bytes)


def test_argon2_hash_round_trip():
    stored = hash_secret("correct horse battery")
    assert stored.startswith("$argon2id$")
    assert verify_secret(stored, "correct horse battery")
    assert not verify_secret(stored, "wrong")
    assert not verify_secret(None, "anything")
    assert not verify_secret("not-a-hash", "anything")


@pytest.mark.parametrize(("password", "ok"), [("short", False), ("aaaaaaaaaaaaaa", False), ("Kh7!m3r-Riel-2026", True), ("alice-Kh7!m3r-Riel", False)])
def test_password_policy(password: str, ok: bool):
    assert (password_problems(password, "alice") == []) is ok


@pytest.mark.parametrize(("pin", "ok"), [("1234", False), ("1111", False), ("12a4", False), ("123", False), ("4821", True), ("905173", True)])
def test_pin_policy(pin: str, ok: bool):
    assert (pin_problems(pin) == []) is ok


def test_pin_lookup_is_keyed_per_company():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert pin_lookup(a, "4821") == pin_lookup(a, "4821")
    assert pin_lookup(a, "4821") != pin_lookup(b, "4821")


def test_access_token_round_trip_and_expiry():
    user, session, company = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token, seconds = create_access_token(user, session, company)
    claims = decode_access_token(token)
    assert claims and claims.user_id == user and claims.session_id == session and claims.company_id == company
    assert seconds == get_settings().access_token_expire_minutes * 60
    expired = jwt.encode({"sub": str(user), "sid": str(session), "cid": str(company), "typ": "access", "exp": int(time.time()) - 5}, get_settings().secret_key.get_secret_value(), algorithm="HS256")
    assert decode_access_token(expired) is None
    forged = jwt.encode({"sub": str(user), "sid": str(session), "cid": str(company), "typ": "access", "exp": int(time.time()) + 60}, "x" * 40, algorithm="HS256")
    assert decode_access_token(forged) is None
    assert decode_access_token(token + "x") is None


def test_token_digest_is_stable_and_not_the_token():
    assert token_digest("abc") == token_digest("abc") != "abc"


def test_every_role_permission_is_in_the_catalogue():
    for code, role in DEFAULT_ROLES.items():
        unknown = set(role.permissions) - set(PERMISSIONS)
        assert not unknown, f"{code}: {unknown}"


def test_twelve_default_roles():
    assert len(DEFAULT_ROLES) == 12


def test_frontend_key_map_targets_exist():
    for frontend_key, codes in FRONTEND_KEY_MAP.items():
        for code in [codes] if isinstance(codes, str) else codes:
            assert code in PERMISSIONS, f"{frontend_key} -> {code}"


def test_sod_pairs_exist_and_are_detected():
    for a, b, _ in SOD_CONFLICTS:
        assert a in PERMISSIONS and b in PERMISSIONS
    a, b, label = SOD_CONFLICTS[0]
    assert sod_conflicts({a, b}) == [label]
    assert sod_conflicts({a}) == []


def test_owner_cannot_manage_roles_by_default():
    owner = DEFAULT_ROLES["OWNER"]
    assert "users.role.manage" not in owner.permissions


def test_short_secret_key_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SECRET_KEY", "too-short")
    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_database_password_is_url_encoded_and_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    monkeypatch.setenv("DB_PASSWORD", "p@ss:w/rd")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert "p%40ss%3Aw%2Frd" in settings.url_for("pims_test_db")
    assert "p@ss" not in repr(settings)
