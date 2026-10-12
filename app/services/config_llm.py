from functools import lru_cache
from typing import Optional

from langchain_core.language_models import BaseChatModel

from app.core.config import Settings, get_settings


def build_chat_model(settings: Settings, model: Optional[str] = None) -> BaseChatModel:
    """Modelo de chat del LLM_PROVIDER configurado. `model` reemplaza el nombre del modelo
    del proveedor (lo usa el extractor de memoria con MEMORIA_MODEL)."""
    provider = settings.llm_provider.strip().lower()

    # temperature baja: menos variabilidad al redactar la respuesta final a partir del
    # resultado de una tool (mitiga que el modelo "relea mal" un numero ya correcto).
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=model or settings.ollama_chat_model, base_url=settings.ollama_base_url, temperature=0)

    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY no esta configurado (LLM_PROVIDER=openai)")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model or settings.openai_chat_model, api_key=settings.openai_api_key, temperature=0)

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY no esta configurado (LLM_PROVIDER=anthropic)")
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model or settings.anthropic_chat_model, api_key=settings.anthropic_api_key, temperature=0)

    raise ValueError(f"LLM_PROVIDER no soportado: {settings.llm_provider!r} (usar 'ollama', 'openai' o 'anthropic')")


@lru_cache
def get_chat_model() -> BaseChatModel:
    """Modelo de chat del proceso (lo comparten /api/v1/chat y /api/v2/chat)."""
    return build_chat_model(get_settings())
