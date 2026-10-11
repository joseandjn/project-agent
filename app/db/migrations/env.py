"""Entorno de Alembic (plantilla async). La URL sale de POSTGRES_DSN (app/core/config.py),
no de alembic.ini, para que local y docker-compose usen la misma configuracion que la app.

Uso:
    alembic upgrade head                                   # aplicar migraciones pendientes
    alembic revision --autogenerate --rev-id 0002 -m "..."  # nueva migracion desde app/db/models.py
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Modo offline (`alembic upgrade head --sql`): genera el SQL sin conectarse."""
    context.configure(
        url=get_settings().postgres_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(get_settings().postgres_dsn, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
