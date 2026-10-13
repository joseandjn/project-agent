"""Dependencias de rate limit por ruta (docs/rate_limits.md). Cada una resuelve la identidad
(JWT) una sola vez (FastAPI cachea `get_auth_context` dentro del request) y cuenta el
request en sus reglas; si alguna se pasa, 429 con Retry-After."""

from fastapi import Depends

from app.api.v1.dependencies.auth import get_auth_context
from app.core.config import get_settings
from app.core.rate_limit import DIA, MINUTO, Regla, consumir
from app.core.security import AuthContext


async def limitar_chat(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """Turnos de chat (v1 y v2): por sesion, por cliente (todas sus sesiones) y por tienda
    (por minuto y por dia: tope de costo de LLM)."""
    s = get_settings()
    tienda = str(ctx.tienda_id)
    reglas = [
        Regla("chat:sesion", ctx.thread_id, s.rl_chat_sesion_por_minuto, MINUTO),
        Regla("chat:tienda", tienda, s.rl_chat_tienda_por_minuto, MINUTO),
        Regla("chat:tienda:dia", tienda, s.rl_chat_tienda_por_dia, DIA),
    ]
    if ctx.cliente_id:
        reglas.append(Regla("chat:cliente", str(ctx.cliente_id), s.rl_chat_cliente_por_minuto, MINUTO))
    await consumir(reglas)
    return ctx


async def limitar_refresh(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    await consumir([Regla("refresh:sesion", ctx.thread_id, get_settings().rl_refresh_sesion_por_minuto, MINUTO)])
    return ctx


async def limitar_feedback(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    await consumir([Regla("feedback:sesion", ctx.thread_id, get_settings().rl_feedback_sesion_por_minuto, MINUTO)])
    return ctx


async def limitar_memoria(ctx: AuthContext) -> None:
    """Para GET/DELETE /memoria (sesiones de cliente)."""
    if ctx.cliente_id:
        await consumir([Regla("memoria:cliente", str(ctx.cliente_id), get_settings().rl_memoria_cliente_por_minuto, MINUTO)])
