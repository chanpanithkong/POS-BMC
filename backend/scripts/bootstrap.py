"""Secure first-run bootstrap: creates the company and the first System Administrator and Business Owner.

Passwords are never hardcoded. You type them (hidden), or the script generates
strong random ones and prints them once. Refuses to run if users already exist.

Run:  .venv\\Scripts\\python.exe -m scripts.bootstrap
"""

import asyncio
import getpass
import secrets
import sys

from sqlalchemy import func, select

from app.core.runtime import use_selector_loop
from app.core.security import hash_secret, password_problems
from app.db.session import dispose_engine, session_factory
from app.models import Role, User, UserRole
from app.services import audit
from app.services.bootstrap import create_company
from scripts.seed import seed_reference_data


def ask(prompt: str, default: str = "") -> str:
    value = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return value or default


def ask_password(label: str, username: str) -> str:
    if not sys.stdin.isatty():
        return secrets.token_urlsafe(18)
    while True:
        first = getpass.getpass(f"Password for {label} (blank to generate): ")
        if not first:
            return secrets.token_urlsafe(18)
        problems = password_problems(first, username)
        if problems:
            print(" ".join(problems))
            continue
        if getpass.getpass("Repeat password: ") == first:
            return first
        print("Passwords did not match.")


async def main() -> int:
    async with session_factory()() as session:
        await seed_reference_data(session)
        if await session.scalar(select(func.count()).select_from(User)):
            print("Users already exist. Bootstrap only runs on an empty system; manage users through the API.")
            return 1
        legal = ask("Company legal name", "ABC Retail Co., Ltd.")
        trading = ask("Company trading name", "ABC Mart")
        company = await create_company(session, legal_name=legal, trading_name=trading)
        created = []
        for role_code, default_user in (("SYSADMIN", "admin"), ("OWNER", "owner")):
            username = ask(f"{role_code} username", default_user)
            email = ask(f"{role_code} email", f"{username}@example.com")
            password = ask_password(username, username)
            user = User(company_id=company.id, username=username, email=email.lower(), full_name=username.title(), password_hash=hash_secret(password))
            session.add(user)
            await session.flush()
            role = await session.scalar(select(Role).where(Role.company_id == company.id, Role.code == role_code))
            session.add(UserRole(user_id=user.id, role_id=role.id))  # type: ignore[union-attr]
            await audit.record(session, action="BOOTSTRAP_USER_CREATED", module="AUTH", entity_type="user", entity_id=user.id, company_id=company.id, after={"username": username, "role": role_code})
            created.append((username, password))
        await session.commit()
    await dispose_engine()
    print("\nBootstrap complete. Store these credentials safely; they are not shown again:")
    for username, password in created:
        print(f"  {username}: {password}")
    print("Change them after first sign-in.")
    return 0


if __name__ == "__main__":
    use_selector_loop()
    sys.exit(asyncio.run(main()))
