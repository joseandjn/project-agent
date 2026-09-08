from functools import lru_cache

from langchain.agents import create_agent
from langchain.agents.middleware import PIIDetectionError
from langchain_core.language_models import BaseChatModel

from app.agent.prompts.system_prompt import SYSTEM_PROMPT
from app.core.config import Settings, get_settings
from app.guardrails.pii import build_pii_guardrail, contiene_numero_de_tarjeta
from app.memory.short_term.session_memory import get_checkpointer, session_config
from app.tools.langchain_tools import build_tools

# Respuesta fija cuando el guardrail de PII bloquea un numero de tarjeta en el chat.
_RESPUESTA_TARJETA_BLOQUEADA = (
    "Por tu seguridad no proceso numeros de tarjeta por el chat. Puedo ayudarte a elegir "
    "el alimento y te comparto el link del producto; el pago se completa en la tienda web."
)


def _build_chat_model(settings: Settings) -> BaseChatModel:
    provider = settings.llm_provider.strip().lower()

    # temperature baja: menos variabilidad al redactar la respuesta final a partir del
    # resultado de una tool (mitiga que el modelo "relea mal" un numero ya correcto).
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=settings.ollama_chat_model, base_url=settings.ollama_base_url, temperature=0)

    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY no esta configurado (LLM_PROVIDER=openai)")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=settings.openai_chat_model, api_key=settings.openai_api_key, temperature=0)

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY no esta configurado (LLM_PROVIDER=anthropic)")
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=settings.anthropic_chat_model, api_key=settings.anthropic_api_key, temperature=0)

    raise ValueError(f"LLM_PROVIDER no soportado: {settings.llm_provider!r} (usar 'ollama', 'openai' o 'anthropic')")


@lru_cache
def get_chat_model() -> BaseChatModel:
    return _build_chat_model(get_settings())


async def generate_reply(mensaje: str, session_id: str) -> str:
    """Corre el agente sobre un turno del cliente. El historial NO se pasa a mano: el
    checkpointer de Redis lo recarga a partir del `thread_id == session_id` y guarda el
    estado nuevo al terminar (memoria de corto plazo, ver session_memory.py)."""
    # Corta antes de tocar el agente: un numero de tarjeta no debe entrar al grafo ni al
    # checkpointer (el bloqueo del middleware llega despues de persistir el input).
    if contiene_numero_de_tarjeta(mensaje):
        return _RESPUESTA_TARJETA_BLOQUEADA

    model = get_chat_model()
    tools = build_tools(session_id)
    checkpointer = await get_checkpointer()
    agent = create_agent(
        model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        middleware=build_pii_guardrail(),  # redacta email/telefono, bloquea tarjeta
    )

    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": mensaje}]},
            config=session_config(session_id),
        )
    except PIIDetectionError:
        return _RESPUESTA_TARJETA_BLOQUEADA

    return result["messages"][-1].content
