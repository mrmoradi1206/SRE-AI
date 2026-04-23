import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None


def database_url() -> str:
    host = os.getenv('POSTGRES_HOST', 'postgres')
    port = os.getenv('POSTGRES_PORT', '5432')
    db = os.getenv('POSTGRES_DB', 'aiops')
    user = os.getenv('POSTGRES_USER', 'aiops')
    password = os.getenv('POSTGRES_PASSWORD', 'changeme')
    return f'postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}'


def init_engine() -> None:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(database_url(), pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    if _session_factory is None:
        init_engine()
    async with _session_factory() as session:
        yield session
