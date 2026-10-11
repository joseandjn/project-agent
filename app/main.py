from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import api_router
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import close_engine, get_sessionmaker
from app.memory.short_term.session_memory import close_checkpointer, get_checkpointer

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
    # Pool de Postgres (tiendas/clientes). El esquema lo crea `alembic upgrade head`.
    async with get_sessionmaker()() as db:
        await db.execute(text("SELECT 1"))
    yield
    await close_checkpointer()
    await close_engine()


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
