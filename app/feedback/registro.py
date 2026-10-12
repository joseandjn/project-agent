"""Feedback del cliente sobre las respuestas del agente (docs/feedback_cliente.md, Fase 1).

1. Cada turno de /chat genera un `mensaje_id`. Al responder, `registrar_mensaje` guarda en
   Redis (con TTL `FEEDBACK_VENTANA_SEGUNDOS`) a que sesion pertenece y que SKUs consulto el
   agente en ese turno, sacados de las tool calls del checkpoint.
2. `POST /api/v1/feedback` solo acepta un `mensaje_id` registrado para la misma sesion del
   token (otra sesion u otra tienda => 404) y guarda el voto en Postgres: uno por mensaje,
   el ultimo reemplaza al anterior. Tambien lo manda a Langfuse como score de la traza.
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import AuthContext
from app.db.models import FeedbackMensaje
from app.memory.long_term.consolidacion import get_redis
from app.memory.long_term.extractor import datos_de_tools
from app.memory.short_term.session_memory import get_checkpointer, session_config
from app.models.feedback import FeedbackRequest
from app.observability.langfuse import registrar_feedback

logger = logging.getLogger(__name__)


def _mensaje_key(mensaje_id: uuid.UUID) -> str:
    return f"vethis:fb:mensaje:{mensaje_id}"


async def _mensajes(thread_id: str) -> List[Any]:
    checkpoint = await (await get_checkpointer()).aget_tuple(session_config(thread_id))
    return checkpoint.checkpoint["channel_values"].get("messages", []) if checkpoint else []


async def contar_mensajes(thread_id: str) -> Optional[int]:
    """Cuantos mensajes tiene la sesion antes del turno (para saber cuales son del turno).
    None si no se pudo leer: el chat sigue, ese mensaje no admitira feedback."""
    try:
        return len(await _mensajes(thread_id))
    except Exception:
        logger.exception("No se pudo leer el checkpoint de %s para el feedback", thread_id)
        return None


async def registrar_mensaje(ctx: AuthContext, mensaje_id: uuid.UUID, desde: Optional[int]) -> None:
    """Registra la respuesta para que se pueda votar. Nunca levanta."""
    if desde is None:
        return
    try:
        # Mensajes del turno = los que se agregaron al checkpoint durante el turno (si el
        # turno no paso por el agente, p. ej. tarjeta bloqueada, no hay ninguno).
        nuevos = (await _mensajes(ctx.thread_id))[desde:]
        skus, _ = datos_de_tools(nuevos)
        datos = {
            "thread_id": ctx.thread_id,
            "tienda_id": str(ctx.tienda_id),
            "cliente_id": str(ctx.cliente_id) if ctx.cliente_id else None,
            "skus": skus,
        }
        await get_redis().set(_mensaje_key(mensaje_id), json.dumps(datos), ex=get_settings().feedback_ventana_segundos)
    except Exception:
        logger.exception("No se pudo registrar el mensaje %s para feedback", mensaje_id)


async def _mensaje_registrado(ctx: AuthContext, mensaje_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    crudo = await get_redis().get(_mensaje_key(mensaje_id))
    if crudo is None:
        return None
    datos = json.loads(crudo)
    # Otra sesion (u otra tienda: el thread_id lleva la tienda) => como si no existiera.
    return datos if datos["thread_id"] == ctx.thread_id else None


async def guardar_feedback(db: AsyncSession, ctx: AuthContext, req: FeedbackRequest) -> bool:
    """Guarda (o reemplaza) el voto. False si el mensaje no existe para esta sesion o ya
    vencio la ventana para votar."""
    datos = await _mensaje_registrado(ctx, req.mensaje_id)
    if datos is None:
        return False

    nuevos_valores = {"valor": req.valor, "motivo": req.motivo, "comentario": req.comentario}
    stmt = insert(FeedbackMensaje).values(
        tienda_id=ctx.tienda_id,
        cliente_id=ctx.cliente_id,
        thread_id=ctx.thread_id,
        mensaje_id=req.mensaje_id,
        skus=datos["skus"],
        **nuevos_valores,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[FeedbackMensaje.mensaje_id],
        set_={**nuevos_valores, "actualizado_en": func.now()},
    )
    await db.execute(stmt)
    await db.commit()

    registrar_feedback(req.mensaje_id, req.valor, req.motivo)
    return True
