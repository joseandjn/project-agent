"""Memoria de corto plazo: el estado de la conversacion vive en un checkpoint de LangGraph
por sesion, guardado en Redis.

En vez de serializar el historial a mano (un JSON por `session_id`), se delega en el
checkpointer de LangGraph `langgraph-checkpoint-redis`: el agente persiste y recarga solo
el estado del grafo usando `thread_id == session_id`. El TTL de sesion
(`SESSION_TTL_SECONDS`) se aplica a las claves del checkpoint y se refresca en cada lectura,
asi la sesion sigue viva mientras el cliente conversa.

Referencia: https://redis.io/blog/langgraph-redis-build-smarter-ai-agents-with-memory-persistence/

Nota: requiere Redis con el modulo RediSearch (imagen `redis:8` o `redis-stack`).
"""

import asyncio
from typing import Any, Dict, Optional

from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from app.core.config import get_settings

_checkpointer: Optional[AsyncRedisSaver] = None
_lock = asyncio.Lock()


def session_config(session_id: str) -> Dict[str, Any]:
    """Config que le dice a LangGraph que hilo (conversacion) cargar/guardar.
    El `session_id` lo asigna el sitio web; aca se usa tal cual como `thread_id`."""
    return {"configurable": {"thread_id": session_id}}


async def get_checkpointer() -> AsyncRedisSaver:
    """Devuelve el checkpointer de Redis (singleton del proceso), creandolo la primera vez.

    Se construye directo (sin el context manager `from_conn_string`) para poder vivir toda
    la vida del proceso; `main.py` lo inicializa en el lifespan y lo cierra al apagar, pero
    esta funcion tambien sirve para scripts sueltos (p. ej. `evals/`) sin lifespan."""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    async with _lock:
        if _checkpointer is None:
            settings = get_settings()
            ttl_minutes = max(1, settings.session_ttl_seconds // 60)
            saver = AsyncRedisSaver(
                redis_url=settings.redis_url,
                ttl={"default_ttl": ttl_minutes, "refresh_on_read": True},
            )
            await saver.asetup()  # crea los indices RediSearch (idempotente)
            _checkpointer = saver
        return _checkpointer


async def close_checkpointer() -> None:
    """Cierra la conexion a Redis del checkpointer. Lo llama el lifespan al apagar."""
    global _checkpointer
    if _checkpointer is not None:
        try:
            await _checkpointer._redis.aclose()
        finally:
            _checkpointer = None
