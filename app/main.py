from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import api_router
from app.core.config import get_settings
from app.db.redis_client import get_redis_client

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = get_redis_client()
    await redis_client.ping()
    # TODO: inicializar pool de Postgres+pgvector cuando se conecte la memoria de largo plazo
    yield
    await redis_client.aclose()


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
