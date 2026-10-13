from functools import lru_cache
from typing import Optional

from langchain_core.language_models import BaseChatModel

from app.core.config import Settings, get_settings


def build_chat_model(settings: Settings, model: Optional[str] = None, provider: Optional[str] = None) -> BaseChatModel:
    """Modelo de chat del LLM_PROVIDER configurado. `model` reemplaza el nombre del modelo
    del proveedor (lo usa el extractor de memoria con MEMORIA_MODEL); `provider` reemplaza el
    proveedor (lo usa el modelo de respaldo, LLM_FALLBACK_MODEL="proveedor:modelo").

    Cada request tiene timeout (LLM_TIMEOUT_SEGUNDOS) y reintentos (LLM_MAX_REINTENTOS): sin
    timeout, un proveedor colgado deja el turno esperando (el de OpenAI es de 10 min)."""
    provider = (provider or settings.llm_provider).strip().lower()
    timeout, reintentos = settings.llm_timeout_segundos, settings.llm_max_reintentos

    # temperature baja: menos variabilidad al redactar la respuesta final a partir del
    # resultado de una tool (mitiga que el modelo "relea mal" un numero ya correcto).
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model or settings.ollama_chat_model,
            base_url=settings.ollama_base_url,
            temperature=0,
            client_kwargs={"timeout": timeout},
        )

    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY no esta configurado (LLM_PROVIDER=openai)")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or settings.openai_chat_model,
            api_key=settings.openai_api_key,
            temperature=0,
            request_timeout=timeout,
            max_retries=reintentos,
        )

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY no esta configurado (LLM_PROVIDER=anthropic)")
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model or settings.anthropic_chat_model,
            api_key=settings.anthropic_api_key,
            temperature=0,
            default_request_timeout=timeout,
            max_retries=reintentos,
        )

    raise ValueError(f"LLM_PROVIDER no soportado: {settings.llm_provider!r} (usar 'ollama', 'openai' o 'anthropic')")


def build_fallback_model(settings: Settings) -> Optional[BaseChatModel]:
    """Modelo de respaldo para ModelFallbackMiddleware, o None si LLM_FALLBACK_MODEL esta vacio.
    Formato: "modelo" (mismo proveedor) o "proveedor:modelo" (p. ej. "anthropic:claude-...")."""
    valor = (settings.llm_fallback_model or "").strip()
    if not valor:
        return None
    # "llama3.1:8b" tambien lleva ":"; solo es proveedor si lo de antes es uno conocido.
    prefijo, _, resto = valor.partition(":")
    if prefijo in ("ollama", "openai", "anthropic"):
        return build_chat_model(settings, model=resto, provider=prefijo)
    return build_chat_model(settings, model=valor)


@lru_cache
def get_chat_model() -> BaseChatModel:
    """Modelo de chat del proceso (lo comparten /api/v1/chat y /api/v2/chat)."""
    return build_chat_model(get_settings())
