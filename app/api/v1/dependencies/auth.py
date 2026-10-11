"""Dependencias de autenticacion: API key de tienda (servidor a servidor) y JWT (chat)."""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthContext, TokenInvalido, hash_api_key, validar_token
from app.db.models import Tienda
from app.db.session import get_db

# auto_error=False: devolvemos 401 (no el 403 por defecto de FastAPI) con un mensaje propio.
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)


def no_autorizado(detalle: str, bearer: bool = False) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if bearer else None
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detalle, headers=headers)


async def get_tienda_por_api_key(
    api_key: Optional[str] = Depends(_api_key_header),
    db: AsyncSession = Depends(get_db),
) -> Tienda:
    if not api_key:
        raise no_autorizado("Falta el header X-API-Key")
    tienda = await db.scalar(select(Tienda).where(Tienda.api_key_hash == hash_api_key(api_key)))
    if tienda is None or not tienda.activa:
        raise no_autorizado("API key invalida")
    return tienda


async def get_auth_context(
    credenciales: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AuthContext:
    """Identidad del request de chat, sacada del JWT. No consulta la base: la revocacion de
    una tienda corta en `POST /auth/refresh`, a mas tardar al vencer el token (JWT_TTL_SECONDS)."""
    if credenciales is None:
        raise no_autorizado("Falta el token Bearer", bearer=True)
    try:
        return validar_token(credenciales.credentials)
    except TokenInvalido:
        raise no_autorizado("Token invalido o expirado", bearer=True) from None
