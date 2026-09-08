from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import api_router
from app.core.config import get_settings
from app.memory.short_term.session_memory import close_checkpointer, get_checkpointer

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializa el checkpointer de Redis (memoria de corto plazo): conecta y crea los
    # indices RediSearch. Si Redis no esta disponible, el arranque falla aca.
    await get_checkpointer()
    # TODO: inicializar pool de Postgres+pgvector cuando se conecte la memoria de largo plazo
    yield
    await close_checkpointer()


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
