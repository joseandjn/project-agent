"""Agente compartido: se crea **una vez por proceso** (en el lifespan de main.py) y lo usa
`POST /api/v2/chat`. `/api/v1/chat` sigue usando `generate_reply` (llm_client.py), que arma
el agente en cada request.

Lo que en v1 obliga a armar el agente por request viaja ahora en el contexto del turno
(`Contexto`, app/agent/contexto.py), que el LLM no ve:
- el `thread_id` que necesita `derivar_veterinario` lo lee la tool via `ToolRuntime`;
- el bloque `<perfil_cliente>` lo agrega un middleware de prompt dinamico.

El grafo compilado no guarda estado entre invocaciones: el historial vive en el checkpoint de
Redis (por `thread_id`) y el resto en el contexto de cada `ainvoke`, asi que lo pueden usar
varios requests a la vez.
"""

import asyncio
from typing import Optional

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, PIIDetectionError, dynamic_prompt
from langgraph.graph.state import CompiledStateGraph

from app.agent.contexto import Contexto
from app.agent.prompts.perfil_cliente import render_bloque_perfil
from app.agent.prompts.system_prompt import SYSTEM_PROMPT
from app.guardrails.pii import build_pii_guardrail, contiene_numero_de_tarjeta
from app.memory.long_term.models import PerfilCliente
from app.memory.short_term.session_memory import get_checkpointer, session_config
from app.observability.langfuse import callbacks
from app.services.config_llm import get_chat_model
from app.services.llm_client import RESPUESTA_TARJETA_BLOQUEADA
from app.tools.langchain_tools import TOOLS_CON_CONTEXTO

_agente: Optional[CompiledStateGraph] = None
_checkpointer_del_agente = None
_lock = asyncio.Lock()


@dynamic_prompt
def prompt_con_perfil(request: ModelRequest) -> str:
    """System prompt del turno: el base + el perfil del cliente del contexto (si hay)."""
    perfil = request.runtime.context.perfil
    return SYSTEM_PROMPT + (render_bloque_perfil(perfil) if perfil else "")


async def get_agente() -> CompiledStateGraph:
    """Agente compartido (singleton del proceso). Se vuelve a crear solo si cambio el
    checkpointer (p. ej. se cerro y reabrio Redis, como hacen los tests)."""
    global _agente, _checkpointer_del_agente
    checkpointer = await get_checkpointer()
    if _agente is not None and _checkpointer_del_agente is checkpointer:
        return _agente
    async with _lock:
        if _agente is None or _checkpointer_del_agente is not checkpointer:
            _agente = create_agent(
                get_chat_model(),
                tools=TOOLS_CON_CONTEXTO,
                # El prompt dinamico va primero: el PII de entrada redacta mensajes, no el prompt.
                middleware=[prompt_con_perfil, *build_pii_guardrail()],
                context_schema=Contexto,
                checkpointer=checkpointer,
            )
            _checkpointer_del_agente = checkpointer
        return _agente


def reset_agente() -> None:
    """Descarta el agente compartido (tests, o si cambia el modelo)."""
    global _agente, _checkpointer_del_agente
    _agente, _checkpointer_del_agente = None, None


async def generar_respuesta(mensaje: str, thread_id: str, perfil: Optional[PerfilCliente] = None) -> str:
    """Igual que `generate_reply` (mismo corte por tarjeta, mismo guardrail de PII, mismo
    checkpoint), pero con el agente compartido y el turno en `Contexto`."""
    # Corta antes de tocar el agente: un numero de tarjeta no debe entrar al grafo ni al
    # checkpointer (el bloqueo del middleware llega despues de persistir el input).
    if contiene_numero_de_tarjeta(mensaje):
        return RESPUESTA_TARJETA_BLOQUEADA

    agente = await get_agente()
    try:
        result = await agente.ainvoke(
            {"messages": [{"role": "user", "content": mensaje}]},
            config={**session_config(thread_id), "callbacks": callbacks()},
            context=Contexto(thread_id=thread_id, perfil=perfil),
        )
    except PIIDetectionError:
        return RESPUESTA_TARJETA_BLOQUEADA

    return result["messages"][-1].content
