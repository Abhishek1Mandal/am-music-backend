from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


# ============================================================
# Database Engine
# ============================================================

engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout,
    pool_recycle=settings.database_pool_recycle,
)


# ============================================================
# Session Factory
# ============================================================

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ============================================================
# Base Model
# ============================================================

class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.
    """

    pass


# ============================================================
# Database Dependency
# ============================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides an async database session.

    The session is automatically closed after the request.
    """

    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ============================================================
# Database Shutdown
# ============================================================

async def close_database() -> None:
    """
    Dispose of the SQLAlchemy connection pool.

    Should be called when the FastAPI application shuts down.
    """

    await engine.dispose()