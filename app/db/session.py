"""Conexion a Postgres: un engine async (SQLAlchemy + asyncpg) por proceso.

Igual que el checkpointer de Redis, `main.py` lo inicializa en el lifespan y lo cierra al
apagar; `get_db` es la dependencia de FastAPI que entrega una sesion por request.
"""

from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Devuelve el sessionmaker (singleton del proceso), creando el engine la primera vez.
    Sirve tambien para scripts sueltos sin lifespan (p. ej. `scripts/crear_tienda.py`)."""
    global _engine, _sessionmaker
    if _sessionmaker is None:
        _engine = create_async_engine(get_settings().postgres_dsn, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def close_engine() -> None:
    """Cierra el pool de conexiones. Lo llama el lifespan al apagar."""
    global _engine, _sessionmaker
    if _engine is not None:
        try:
            await _engine.dispose()
        finally:
            _engine = None
            _sessionmaker = None
