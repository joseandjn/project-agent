"""Trazas en Langfuse Cloud (docs/observabilidad_langfuse.md).

- **Una traza por turno** de `/chat` y una por consolidacion de memoria, con
  `session_id = thread_id`, `user_id = cliente_id` (UUID interno; nada si es anonimo) y la
  tienda como metadato y tag. Las llamadas al LLM y a las tools cuelgan de la traza via el
  `CallbackHandler` de LangChain.
- **Datos personales:** todo lo que se envia pasa por `enmascarar` (email, telefono y
  tarjeta), porque Langfuse Cloud es un servicio externo.
- **Nunca rompe el chat:** sin `LANGFUSE_ENABLED=true` y las dos claves, todo esto es un no-op;
  si el SDK falla al arrancar, se loguea y se sigue sin trazas. El envio es en segundo plano.
"""

import logging
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional

from langchain_core.callbacks import BaseCallbackHandler
from pydantic import BaseModel

from app.core.config import get_settings
from app.guardrails.pii import redactar_pii

logger = logging.getLogger(__name__)

_cliente = None
_inicializado = False

# Mismo formato que PIIMiddleware(strategy="redact").
_TARJETA_REDACTADA = "[REDACTED_CREDIT_CARD]"


def _redactar_texto(texto: str) -> str:
    from langchain.agents.middleware.pii import detect_credit_card

    for match in sorted(detect_credit_card(texto), key=lambda m: m["start"], reverse=True):
        texto = texto[: match["start"]] + _TARJETA_REDACTADA + texto[match["end"] :]
    return redactar_pii(texto)


def enmascarar(*, data: Any, **kwargs: Any) -> Any:
    """`mask` del cliente de Langfuse: redacta PII en todo string, recorriendo dicts, listas y
    modelos Pydantic (los mensajes de LangChain lo son). Devuelve algo serializable a JSON."""
    if isinstance(data, str):
        return _redactar_texto(data)
    if isinstance(data, dict):
        return {k: enmascarar(data=v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [enmascarar(data=v) for v in data]
    if isinstance(data, BaseModel):
        return enmascarar(data=data.model_dump(mode="json"))
    return data


def get_langfuse():
    """Cliente de Langfuse (singleton del proceso), o None si esta deshabilitado."""
    global _cliente, _inicializado
    if _inicializado:
        return _cliente
    _inicializado = True
    settings = get_settings()
    if not (settings.langfuse_enabled and settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    try:
        from langfuse import Langfuse

        _cliente = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_host,
            environment=settings.environment,
            sample_rate=settings.langfuse_sample_rate,
            mask=enmascarar,
        )
    except Exception:
        logger.exception("No se pudo iniciar Langfuse: se sigue sin trazas")
        _cliente = None
    return _cliente


def cerrar_langfuse() -> None:
    """Envia lo pendiente y cierra el cliente (lifespan de main.py)."""
    global _cliente, _inicializado
    if _cliente is not None:
        try:
            _cliente.shutdown()
        except Exception:
            logger.exception("Fallo el cierre de Langfuse")
    _cliente, _inicializado = None, False


def callbacks() -> List[BaseCallbackHandler]:
    """Callbacks de LangChain para pasar en el `config` del agente o del extractor. Cuelgan
    de la traza activa (la que abre `trazar`)."""
    if get_langfuse() is None:
        return []
    from langfuse.langchain import CallbackHandler

    return [CallbackHandler()]


def id_de_traza(mensaje_id: uuid.UUID) -> str:
    """Id de traza de Langfuse derivado del `mensaje_id` del turno: el feedback se liga a la
    traza sin guardar un mapeo (docs/feedback_cliente.md). No necesita el cliente."""
    from langfuse import Langfuse

    return Langfuse.create_trace_id(seed=str(mensaje_id))


@contextmanager
def trazar(
    nombre: str,
    *,
    thread_id: str,
    cliente_id: Optional[uuid.UUID] = None,
    entrada: Any = None,
    mensaje_id: Optional[uuid.UUID] = None,
) -> Iterator[Optional[Any]]:
    """Abre la traza de un turno o de una consolidacion. Devuelve la observacion raiz (para
    `.update(output=...)`) o None si Langfuse esta deshabilitado.

    `thread_id` es `{tienda_id}:{session_id}` (AuthContext.thread_id): de ahi sale la tienda.
    Con `mensaje_id`, el id de la traza es `id_de_traza(mensaje_id)`."""
    lf = get_langfuse()
    if lf is None:
        yield None
        return

    from langfuse import propagate_attributes

    tienda_id = thread_id.split(":", 1)[0]
    contexto = {"trace_id": id_de_traza(mensaje_id)} if mensaje_id else None
    with lf.start_as_current_observation(
        name=nombre, as_type="agent", input=entrada, trace_context=contexto
    ) as observacion:
        with propagate_attributes(
            session_id=thread_id,
            user_id=str(cliente_id) if cliente_id else None,
            metadata={"tienda_id": tienda_id},
            tags=[f"tienda:{tienda_id}"],
        ):
            yield observacion


def registrar_feedback(mensaje_id: uuid.UUID, valor: str, motivo: Optional[str]) -> None:
    """Score `feedback_cliente` (1 positivo / 0 negativo, motivo en el comentario) en la traza
    del turno. Mismo `score_id` por mensaje: si el cliente cambia el voto, se reemplaza.
    Nunca levanta: el voto ya quedo guardado en Postgres."""
    lf = get_langfuse()
    if lf is None:
        return
    try:
        lf.create_score(
            name="feedback_cliente",
            value=1 if valor == "positivo" else 0,
            data_type="BOOLEAN",
            trace_id=id_de_traza(mensaje_id),
            score_id=f"feedback-{mensaje_id}",
            comment=motivo,
        )
    except Exception:
        logger.exception("No se pudo enviar el feedback a Langfuse")
