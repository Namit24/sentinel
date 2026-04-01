import logging
import ssl

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from sentinelops.config import settings

logger = logging.getLogger(__name__)

connect_args = {
    "ssl": ssl.create_default_context(),
}


def _normalized_asyncpg_url(url: str) -> str:
    """Removes libpq-only query params so asyncpg can connect cleanly to Neon pooled endpoints."""

    parsed = make_url(url)
    query = dict(parsed.query)
    query.pop("sslmode", None)
    query.pop("channel_binding", None)
    normalized = parsed.set(query=query)
    return normalized.render_as_string(hide_password=False)

engine = create_async_engine(
    _normalized_asyncpg_url(settings.DATABASE_URL),
    echo=settings.ENVIRONMENT == "development",
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args=connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


async def get_db() -> AsyncSession:
    """
    FastAPI dependency that yields a DB session per request.
    Always closes the session after the request, even on error.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()