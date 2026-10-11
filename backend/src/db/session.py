"""Async Database session and connection pooling management."""

from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from src.config import get_settings
from src.logging_config import logger

settings = get_settings()

# Default persistent SQLite storage location (anchored to backend directory)
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SQLITE_PATH = BACKEND_ROOT / "platform_data.db"
FALLBACK_SQLITE_URL = f"sqlite+aiosqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"


def get_active_sqlite_path() -> Path:
    """Returns absolute path to persistent SQLite database."""
    return DEFAULT_SQLITE_PATH


# Configure engine parameters based on database driver
is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine_kwargs = {"echo": False, "future": True}
if not is_sqlite:
    engine_kwargs.update({
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
    })

engine: AsyncEngine = create_async_engine(
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
    """Initializes database schema tables asynchronously with persistent fallback."""
    global engine, AsyncSessionLocal
    from src.db.base import Base
    import src.models.entities  # Ensure all models are registered on Base.metadata

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info(f"Database initialized successfully ({settings.DATABASE_URL.split('://')[0]})")
    except Exception as e:
        logger.warning(
            f"Configured database ({settings.DATABASE_URL.split('://')[0]}) is unavailable: {e}. "
            f"Activating persistent local SQLite fallback at: {DEFAULT_SQLITE_PATH}"
        )
        # Create and bind persistent SQLite fallback engine
        engine = create_async_engine(
            FALLBACK_SQLITE_URL,
            echo=False,
            future=True,
        )
        AsyncSessionLocal = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info(f"Persistent SQLite database initialized successfully at {DEFAULT_SQLITE_PATH}")
