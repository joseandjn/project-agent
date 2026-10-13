"""Limites dentro de un turno del agente (ASI08 / ASI02 de docs/vulnerabilidades.md).

Los rate limits (app/core/rate_limit.py) frenan muchos mensajes; esto frena UN mensaje que
hace que el agente llame al modelo o a las tools en bucle (costo y latencia):

- `ModelCallLimitMiddleware`: maximo de llamadas al modelo por turno. Con
  `exit_behavior="error"`: el "end" de LangChain le responderia al cliente un texto en ingles;
  asi `correr_turno` atrapa el error, deshace el turno y responde en espanol.
- `ToolCallLimitMiddleware`: maximo de tools por turno y `derivar_veterinario` una sola vez
  (no escribir varias derivaciones). Con "continue" la tool bloqueada devuelve un error al
  modelo; por si solo no corta un bucle (lo corta el limite de modelo).
- `recursion_limit` del grafo: tope duro de pasos, por si todo lo anterior falla.
- Timeout del turno completo (`asyncio.wait_for`) y timeout/reintentos de cada request al
  proveedor (`build_chat_model`).
- `ModelFallbackMiddleware`: si el modelo principal falla (caida, rate limit del proveedor),
  reintenta con `LLM_FALLBACK_MODEL`.
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langgraph.errors import GraphRecursionError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

RESPUESTA_TURNO_INTERRUMPIDO = (
    "Disculpa, no pude completar tu consulta esta vez. ¿Puedes intentarlo de nuevo, "
    "quizás con una pregunta más concreta?"
)


def build_limites() -> List[AgentMiddleware]:
    """Middlewares de limites (y fallback de modelo) para `create_agent(..., middleware=...)`."""
    from app.services.config_llm import build_fallback_model

    s = get_settings()
    middlewares: List[AgentMiddleware] = [
        ModelCallLimitMiddleware(run_limit=s.agente_max_llamadas_modelo, exit_behavior="error"),
        ToolCallLimitMiddleware(run_limit=s.agente_max_llamadas_tools, exit_behavior="continue"),
        ToolCallLimitMiddleware(tool_name="derivar_veterinario", run_limit=1, exit_behavior="continue"),
    ]
    fallback = build_fallback_model(s)
    if fallback is not None:
        middlewares.append(ModelFallbackMiddleware(fallback))
    return middlewares


def config_de_turno(config: Dict[str, Any]) -> Dict[str, Any]:
    """Config del `ainvoke` con el tope duro de pasos del grafo."""
    return {**config, "recursion_limit": get_settings().agente_max_pasos}


async def correr_turno(
    invocar: Callable[[], Awaitable[str]], deshacer: Callable[[], Awaitable[None]]
) -> str:
    """Corre el turno del agente con timeout. Si se pasa de un limite o del tiempo, deshace
    el turno incompleto en la sesion (puede haber quedado una tool call sin respuesta, que
    romperia el turno siguiente) y responde un mensaje fijo."""
    try:
        return await asyncio.wait_for(invocar(), timeout=get_settings().agente_timeout_segundos)
    except (ModelCallLimitExceededError, GraphRecursionError, asyncio.TimeoutError) as exc:
        logger.warning("Turno del agente interrumpido: %s", type(exc).__name__)
        try:
            await deshacer()
        except Exception:
            logger.exception("No se pudo deshacer el turno interrumpido")
        return RESPUESTA_TURNO_INTERRUMPIDO
