"""Async Database session and connection pooling management."""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.config import get_settings
from src.logging_config import logger

settings = get_settings()

# Configure engine parameters based on database driver
is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine_kwargs = {"echo": False, "future": True}
if not is_sqlite:
    engine_kwargs.update({
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
    })

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session rollback due to exception: {e}")
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initializes database schema tables asynchronously."""
    from src.db.base import Base

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info(f"Database initialized successfully ({settings.DATABASE_URL.split('://')[0]})")
    except Exception as e:
        logger.warning(f"Could not automatically initialize DB tables: {e}. Ensure DB is running.")
