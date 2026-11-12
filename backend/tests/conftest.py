"""Shared fixtures.

Database tests run only against TEST_DB_NAME (default pims_test_db). The suite
refuses to start if that name equals DB_NAME or does not contain "test", so it
can never migrate or write to the development database. Tests isolate data by
creating a fresh company per test instead of truncating (audit_logs is
append-only, even for tests).
"""

import asyncio
import secrets
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

import httpx
import psycopg
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from alembic.config import Config
from app.core.config import BACKEND_DIR, get_settings
from app.core.security import hash_secret, pin_lookup
from app.db import session as db_session
from app.main import create_app
from app.models import Branch, Company, PosTerminal, Role, User, UserBranchAccess, UserRole, Warehouse, WarehouseLocation
from app.services.bootstrap import create_company
from scripts.seed import seed_reference_data


def _test_url() -> str:
    settings = get_settings()
    name = settings.test_db_name
    if name == settings.db_name or "test" not in name.lower():
        raise RuntimeError(f"Refusing to run: TEST_DB_NAME '{name}' must differ from DB_NAME and contain 'test'.")
    return settings.url_for(name)


def _database_available(url: str) -> str | None:
    if not get_settings().db_password.get_secret_value():
        return "DB_PASSWORD is empty in backend/.env"
    try:
        with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"), connect_timeout=3):
            return None
    except psycopg.Error as exc:
        return f"test database unavailable: {exc.__class__.__name__}"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    needs_db = [item for item in items if "db" in item.keywords]
    if not needs_db:
        return
    reason = _database_available(_test_url())
    if reason:
        for item in needs_db:
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    # psycopg async cannot use the Windows Proactor loop.
    return asyncio.WindowsSelectorEventLoopPolicy() if sys.platform == "win32" else asyncio.DefaultEventLoopPolicy()


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = url
    return cfg


@pytest.fixture(scope="session")
def test_db_url() -> str:
    return _test_url()


@pytest.fixture(scope="session")
async def migrated(test_db_url: str) -> AsyncIterator[str]:
    """Rebuilds the test schema from the migrations, then seeds reference data."""
    cfg = alembic_config(test_db_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    db_session.configure_engine(test_db_url)
    async with db_session.session_factory()() as s:
        await seed_reference_data(s)
        await s.commit()
    yield test_db_url
    await db_session.dispose_engine()


@pytest.fixture
async def db(migrated: str) -> AsyncIterator[AsyncSession]:
    async with db_session.session_factory()() as s:
        yield s


@pytest.fixture
async def client(migrated: str) -> AsyncIterator[httpx.AsyncClient]:
    # A distinct client address per test keeps the per-IP sign-in limiter independent between tests.
    ip = f"10.{secrets.randbelow(250)}.{secrets.randbelow(250)}.{secrets.randbelow(250) + 1}"
    transport = httpx.ASGITransport(app=create_app(), client=(ip, 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def new_password() -> str:
    return "T3st-" + secrets.token_urlsafe(18)


@dataclass
class Account:
    user: User
    password: str
    pin: str | None = None


@dataclass
class World:
    """A fresh company with two branches and helpers to add users."""

    company: Company
    branch_a: Branch
    branch_b: Branch
    roles: dict[str, Role]
    terminal: PosTerminal
    db: AsyncSession
    accounts: list[Account] = field(default_factory=list)

    async def user(self, *role_codes: str, branches: list[Branch] | None = None, pin: str | None = None) -> Account:
        suffix = secrets.token_hex(4)
        password = new_password()
        user = User(
            company_id=self.company.id, username=f"u{suffix}", email=f"u{suffix}@example.test", full_name=f"Test {' '.join(role_codes)} {suffix}",
            password_hash=hash_secret(password),
            pin_hash=hash_secret(pin) if pin else None, pin_lookup=pin_lookup(self.company.id, pin) if pin else None,
        )
        self.db.add(user)
        await self.db.flush()
        self.db.add_all(UserRole(user_id=user.id, role_id=self.roles[c].id) for c in role_codes)
        self.db.add_all(UserBranchAccess(user_id=user.id, branch_id=b.id) for b in branches or [])
        await self.db.commit()
        account = Account(user, password, pin)
        self.accounts.append(account)
        return account


@pytest.fixture
async def world(db: AsyncSession) -> World:
    tag = secrets.token_hex(3)
    company = await create_company(db, legal_name=f"Test Co {tag}", trading_name=f"Test {tag}")
    branch_a = Branch(company_id=company.id, code="A", name_en="Branch A")
    branch_b = Branch(company_id=company.id, code="B", name_en="Branch B")
    db.add_all([branch_a, branch_b])
    await db.flush()
    warehouse = Warehouse(company_id=company.id, branch_id=branch_a.id, code="WA", name="Store A")
    db.add(warehouse)
    await db.flush()
    location = WarehouseLocation(company_id=company.id, warehouse_id=warehouse.id, code="SHELF", name="Shelf", location_type="SELLABLE", is_available_for_sale=True)
    db.add(location)
    await db.flush()
    terminal = PosTerminal(company_id=company.id, branch_id=branch_a.id, code="T1", name="Till 1", default_location_id=location.id)
    db.add(terminal)
    await db.commit()
    roles = {r.code: r for r in await db.scalars(select(Role).where(Role.company_id == company.id))}
    return World(company, branch_a, branch_b, roles, terminal, db)


LoginFn = Callable[[Account], Awaitable[dict[str, str]]]


@pytest.fixture
def login(client: httpx.AsyncClient) -> LoginFn:
    async def do(account: Account) -> dict[str, str]:
        response = await client.post("/api/v1/auth/login", json={"username": account.user.username, "password": account.password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return do


def random_uuid() -> uuid.UUID:
    return uuid.uuid4()
