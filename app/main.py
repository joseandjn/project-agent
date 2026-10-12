import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import api_router
from app.api.v2.routes import api_router_v2
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import close_engine, get_sessionmaker
from app.memory.long_term.consolidacion import close_redis, sweeper
from app.memory.short_term.session_memory import close_checkpointer, get_checkpointer
from app.observability.langfuse import cerrar_langfuse, get_langfuse
from app.services.agente import get_agente, reset_agente

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Sin secreto no se pueden emitir ni validar tokens: mejor fallar al arrancar que en
    # cada request.
    # 32 bytes = minimo recomendado para HS256 (RFC 7518 §3.2).
    if not settings.jwt_secret or len(settings.jwt_secret.encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET no esta configurado o tiene menos de 32 bytes (ver .env.example)")
    # Inicializa el checkpointer de Redis (memoria de corto plazo): conecta y crea los
    # indices RediSearch. Si Redis no esta disponible, el arranque falla aca.
    await get_checkpointer()
    # Pool de Postgres (tiendas, clientes, perfiles). El esquema lo crea `alembic upgrade head`.
    async with get_sessionmaker()() as db:
        await db.execute(text("SELECT 1"))
    # Agente compartido de /api/v2/chat: se crea una sola vez (necesita el checkpointer).
    await get_agente()
    # Trazas en Langfuse Cloud (None si LANGFUSE_ENABLED no esta prendido).
    get_langfuse()
    # Consolida la memoria de largo plazo de las sesiones inactivas antes de que venza su TTL.
    tarea_sweeper = asyncio.create_task(sweeper())
    yield
    tarea_sweeper.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tarea_sweeper
    await close_redis()
    reset_agente()
    await close_checkpointer()
    await close_engine()
    cerrar_langfuse()  # envia las trazas pendientes


app = FastAPI(
    title=settings.app_name,
    description="Backend del agente conversacional asesor de tienda veterinaria",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,  # configurable via ALLOWED_ORIGINS en .env
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
app.include_router(api_router_v2, prefix="/api/v2")
