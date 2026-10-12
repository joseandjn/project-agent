from typing import Optional

from langchain.agents import create_agent
from langchain.agents.middleware import PIIDetectionError

from app.agent.prompts.perfil_cliente import render_bloque_perfil
from app.agent.prompts.system_prompt import SYSTEM_PROMPT
from app.guardrails.pii import build_pii_guardrail, contiene_numero_de_tarjeta
from app.memory.long_term.models import PerfilCliente
from app.memory.short_term.session_memory import get_checkpointer, session_config
from app.observability.langfuse import callbacks
from app.services.config_llm import get_chat_model
from app.tools.langchain_tools import build_tools

# Respuesta fija cuando el guardrail de PII bloquea un numero de tarjeta en el chat.
RESPUESTA_TARJETA_BLOQUEADA = (
    "Por tu seguridad no proceso numeros de tarjeta por el chat. Puedo ayudarte a elegir "
    "el alimento y te comparto el link del producto; el pago se completa en la tienda web."
)

async def generate_reply(mensaje: str, thread_id: str, perfil: Optional[PerfilCliente] = None) -> str:
    """Corre el agente sobre un turno del cliente. El historial NO se pasa a mano: el
    checkpointer de Redis lo recarga a partir del `thread_id` y guarda el estado nuevo al
    terminar (memoria de corto plazo, ver session_memory.py). En `/chat` el `thread_id` es
    `AuthContext.thread_id` (sacado del JWT); los evals pasan uno propio.

    `perfil` es la memoria de largo plazo del cliente (si esta autenticado y tiene una):
    se agrega al system prompt como un bloque delimitado de datos."""
    # Corta antes de tocar el agente: un numero de tarjeta no debe entrar al grafo ni al
    # checkpointer (el bloqueo del middleware llega despues de persistir el input).
    if contiene_numero_de_tarjeta(mensaje):
        return RESPUESTA_TARJETA_BLOQUEADA

    model = get_chat_model()
    tools = build_tools(thread_id)
    checkpointer = await get_checkpointer()
    agent = create_agent(
        model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT + (render_bloque_perfil(perfil) if perfil else ""),
        checkpointer=checkpointer,
        middleware=build_pii_guardrail(),  # redacta email/telefono, bloquea tarjeta
    )

    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": mensaje}]},
            # callbacks: las llamadas al LLM y a las tools cuelgan de la traza de Langfuse que
            # abre /chat (vacio si Langfuse esta deshabilitado).
            config={**session_config(thread_id), "callbacks": callbacks()},
        )
    except PIIDetectionError:
        return RESPUESTA_TARJETA_BLOQUEADA

    return result["messages"][-1].content
