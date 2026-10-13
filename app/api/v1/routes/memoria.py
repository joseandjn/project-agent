"""Acceso del cliente a su propia memoria de largo plazo (Ley 29733: acceso y supresion).
Solo para sesiones autenticadas; el cliente sale del JWT, nunca de un parametro."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies.auth import get_auth_context
from app.api.v1.dependencies.rate_limit import limitar_memoria
from app.core.security import AuthContext
from app.db.session import get_db
from app.memory.long_term.consolidacion import olvidar_sesiones_abiertas
from app.memory.long_term.models import PerfilCliente
from app.memory.long_term.repo import borrar_perfil, leer_perfil

router = APIRouter(prefix="/memoria")


async def _cliente(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if ctx.anonimo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sesion anonima: no hay memoria guardada")
    await limitar_memoria(ctx)
    return ctx


@router.get("", response_model=PerfilCliente)
async def ver(ctx: AuthContext = Depends(_cliente), db: AsyncSession = Depends(get_db)) -> PerfilCliente:
    perfil = await leer_perfil(db, ctx.cliente_id)
    if perfil is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todavia no hay memoria guardada")
    return perfil


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def borrar(ctx: AuthContext = Depends(_cliente), db: AsyncSession = Depends(get_db)) -> Response:
    """Borra el perfil y su historial de versiones. Lo que el cliente dijo hasta ahora en
    sesiones todavia abiertas tampoco se guarda despues."""
    await olvidar_sesiones_abiertas(ctx.cliente_id)
    await borrar_perfil(db, ctx.cliente_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
