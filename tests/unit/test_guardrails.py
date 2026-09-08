"""El guardrail de PII se prueba end-to-end contra un agente con modelo falso: no necesita
LLM real ni Redis (sin checkpointer)."""

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import PIIDetectionError
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from app.guardrails.pii import build_pii_guardrail, contiene_numero_de_tarjeta


def _agente(respuestas):
    model = GenericFakeChatModel(messages=iter(respuestas))
    return create_agent(model, tools=[], system_prompt="x", middleware=build_pii_guardrail())


async def test_redacta_email_y_telefono_en_la_entrada():
    agente = _agente(["ok"])
    result = await agente.ainvoke(
        {"messages": [{"role": "user", "content": "escribime a juan@mail.com o al 987654321"}]}
    )
    entrada = result["messages"][0].content
    assert "juan@mail.com" not in entrada
    assert "987654321" not in entrada
    assert "[REDACTED_EMAIL]" in entrada
    assert "[REDACTED_TELEFONO_PE]" in entrada


@pytest.mark.parametrize(
    "texto, es_tarjeta",
    [
        ("pago con la tarjeta 4111 1111 1111 1111", True),
        ("tarjeta 4539148803436467", True),
        ("perro adulto de 12 kg, presupuesto 200", False),
        ("llamame al 987654321", False),
        ("mi dni es 45678912", False),
    ],
)
def test_deteccion_de_tarjeta(texto, es_tarjeta):
    assert contiene_numero_de_tarjeta(texto) is es_tarjeta


async def test_middleware_bloquea_tarjeta_como_red_de_seguridad():
    agente = _agente(["ok"])
    with pytest.raises(PIIDetectionError):
        await agente.ainvoke(
            {"messages": [{"role": "user", "content": "pago con la tarjeta 4111 1111 1111 1111"}]}
        )


async def test_generate_reply_devuelve_mensaje_seguro_ante_tarjeta(monkeypatch):
    """generate_reply no propaga PIIDetectionError: responde con el texto fijo."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client, "get_chat_model", lambda: GenericFakeChatModel(messages=iter(["ok"])))

    async def _sin_checkpointer():
        return None

    monkeypatch.setattr(llm_client, "get_checkpointer", _sin_checkpointer)

    respuesta = await llm_client.generate_reply("mi tarjeta es 4111 1111 1111 1111", "s1")
    assert "tarjeta" in respuesta.lower()
    assert respuesta == llm_client._RESPUESTA_TARJETA_BLOQUEADA
