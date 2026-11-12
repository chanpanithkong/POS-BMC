"""Reference data: permissions, currencies and stock location types. Safe to run repeatedly.

Business data such as companies, users and roles comes from scripts/bootstrap.py.
Run:  .venv\\Scripts\\python.exe -m scripts.seed
"""

import asyncio
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import PERMISSIONS
from app.db.session import dispose_engine, session_factory
from app.models import Currency, LocationType, Permission

CURRENCIES = [
    # KHR cash rounding of 100 riel is illustrative in the SRS (BR-PAY-006) and configurable.
    {"code": "USD", "name": "US Dollar", "symbol": "$", "decimals": 2, "cash_rounding_increment": Decimal("0.01")},
    {"code": "KHR", "name": "Cambodian Riel", "symbol": "៛", "decimals": 0, "cash_rounding_increment": Decimal("100")},
]

LOCATION_TYPES = [
    ("SELLABLE", "Sellable shelf", True, False),
    ("STORAGE", "Storage", False, False),
    ("RECEIVING", "Receiving", False, False),
    ("DAMAGED", "Damaged", False, False),
    ("EXPIRED", "Expired", False, False),
    ("QUARANTINE", "Quarantine", False, False),
    ("RETURNS", "Returns", False, False),
    ("IN_TRANSIT", "In transit", False, True),
]


async def seed_reference_data(session: AsyncSession) -> None:
    await session.execute(
        insert(Permission)
        .values([{"code": code, "module": code.split(".")[0], "description": text} for code, text in PERMISSIONS.items()])
        .on_conflict_do_update(index_elements=["code"], set_={"description": insert(Permission).excluded.description})
    )
    await session.execute(insert(Currency).values(CURRENCIES).on_conflict_do_nothing(index_elements=["code"]))
    await session.execute(
        insert(LocationType)
        .values([{"code": c, "name": n, "default_available_for_sale": s, "is_system": sys_} for c, n, s, sys_ in LOCATION_TYPES])
        .on_conflict_do_nothing(index_elements=["code"])
    )


async def main() -> None:
    async with session_factory()() as session:
        await seed_reference_data(session)
        await session.commit()
    await dispose_engine()
    print(f"Seeded {len(PERMISSIONS)} permissions, {len(CURRENCIES)} currencies, {len(LOCATION_TYPES)} location types.")


if __name__ == "__main__":
    asyncio.run(main())
