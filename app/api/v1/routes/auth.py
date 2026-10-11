"""Emision de tokens para el chat. Lo llama el **backend** de la tienda (nunca el navegador:
la API key no debe salir de su servidor). Diseño: docs/memoria_largo_plazo.md, Fase 1."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies.auth import get_auth_context, get_tienda_por_api_key, no_autorizado
from app.core.config import get_settings
from app.core.security import AuthContext, emitir_token
from app.db.models import Cliente, Tienda
from app.db.session import get_db
from app.models.auth import TokenRequest, TokenResponse

router = APIRouter(prefix="/auth")


def _respuesta(ctx: AuthContext) -> TokenResponse:
    return TokenResponse(
        access_token=emitir_token(ctx),
        expires_in=get_settings().jwt_ttl_seconds,
        session_id=str(ctx.session_id),
    )


async def _cliente_id(db: AsyncSession, tienda_id: uuid.UUID, external_id: str) -> uuid.UUID:
    """Upsert del cliente por (tienda, external_id); devuelve su id interno.
    El DO UPDATE no cambia nada: esta para que RETURNING devuelva el id tambien si ya existia."""
    stmt = (
        insert(Cliente)
        .values(id=uuid.uuid4(), tienda_id=tienda_id, external_id=external_id)
        .on_conflict_do_update(
            constraint="uq_clientes_tienda_external",
            set_={"external_id": external_id},
        )
        .returning(Cliente.id)
    )
    cliente_id = await db.scalar(stmt)
    await db.commit()
    return cliente_id


@router.post("/token", response_model=TokenResponse)
async def emitir(
    request: TokenRequest,
    tienda: Tienda = Depends(get_tienda_por_api_key),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Abre una sesion de chat nueva. Con `external_user_id` la sesion queda asociada al
    cliente (memoria de largo plazo); sin el, es anonima."""
    cliente_id = None
    if request.external_user_id is not None:
        cliente_id = await _cliente_id(db, tienda.id, request.external_user_id)
    return _respuesta(AuthContext(tienda_id=tienda.id, session_id=uuid.uuid4(), cliente_id=cliente_id))


@router.post("/refresh", response_model=TokenResponse)
async def refrescar(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Renueva un token vigente: misma sesion y mismo cliente, nuevo `exp`. Si la tienda fue
    desactivada, no renueva (asi la revocacion se aplica a mas tardar en JWT_TTL_SECONDS)."""
    activa = await db.scalar(select(Tienda.activa).where(Tienda.id == ctx.tienda_id))
    if not activa:
        raise no_autorizado("Tienda inactiva", bearer=True)
    return _respuesta(ctx)
