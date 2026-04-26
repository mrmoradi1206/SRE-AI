import os
from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .metrics import DB_POOL_CHECKINS, DB_POOL_CHECKOUTS, DB_POOL_SIZE


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_database_url() -> str:
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        return database_url
    user = os.getenv('POSTGRES_USER', 'sre_ai')
    password = os.getenv('POSTGRES_PASSWORD', 'change_me')
    host = os.getenv('POSTGRES_HOST', 'postgres')
    port = os.getenv('POSTGRES_PORT', '5432')
    database = os.getenv('POSTGRES_DB', 'sre_ai')
    return f'postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}'


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        pool_size = int(os.getenv('DB_POOL_SIZE', '10'))
        max_overflow = int(os.getenv('DB_MAX_OVERFLOW', '20'))
        _engine = create_async_engine(
            _build_database_url(),
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=int(os.getenv('DB_POOL_RECYCLE_SECONDS', '1800')),
        )
        service_name = os.getenv('SERVICE_NAME', 'unknown-service')
        DB_POOL_SIZE.labels(service_name).set(pool_size + max_overflow)
        event.listen(_engine.sync_engine.pool, 'checkout', lambda *_args, **_kwargs: DB_POOL_CHECKOUTS.labels(service_name).inc())
        event.listen(_engine.sync_engine.pool, 'checkin', lambda *_args, **_kwargs: DB_POOL_CHECKINS.labels(service_name).inc())
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
