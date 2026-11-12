from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.db.session import session_factory

router = APIRouter(tags=["Platform"])


class Health(BaseModel):
    status: str
    database: str


@router.get("/health", response_model=Health, summary="Liveness and database check", description="Public. Returns 200 even when the database is down, with `database` set to `unavailable`, so load balancers can tell the two apart.")
async def health() -> Health:
    try:
        async with session_factory()() as session:
            await session.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    return Health(status="ok", database=database)
