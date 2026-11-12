"""Async engine and the per-request session.

Services own transaction boundaries: they call `await session.commit()` once at
the end of a command. The dependency below only guarantees rollback and close,
so a failed command never leaves partial writes (NFR-REL-001).
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def configure_engine(url: str | None = None) -> AsyncEngine:
    global _engine, _sessionmaker
    # Sessions run in UTC so timestamps read back are UTC regardless of the server's TimeZone setting.
    _engine = create_async_engine(url or get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=10, connect_args={"options": "-c timezone=UTC"})
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    return _engine or configure_engine()


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        configure_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker = None, None


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
