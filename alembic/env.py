import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from sentinelops.config import settings
from sentinelops.database import Base

# Import all models so Alembic can detect them
from sentinelops.models import log_entry, alert, incident  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from our settings — not from alembic.ini


def _normalized_asyncpg_url(url: str) -> str:
    """Removes libpq-only query params so async Alembic connections remain compatible with asyncpg."""

    parsed = make_url(url)
    query = dict(parsed.query)
    query.pop("sslmode", None)
    query.pop("channel_binding", None)
    normalized = parsed.set(query=query)
    return normalized.render_as_string(hide_password=False)


config.set_main_option("sqlalchemy.url", _normalized_asyncpg_url(settings.DATABASE_URL))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL only)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using async engine (required for asyncpg)."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
