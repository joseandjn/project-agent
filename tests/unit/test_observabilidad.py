"""Trazas de Langfuse (app/observability/langfuse.py) sin red: el cliente exporta a un
exportador de OpenTelemetry en memoria, asi se verifica que se envia (y que no)."""

import json
import uuid

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import HumanMessage
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import app.observability.langfuse as obs
from app.core.config import get_settings
from app.observability.langfuse import callbacks, enmascarar, get_langfuse, trazar

TIENDA, SESION, CLIENTE = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
THREAD = f"{TIENDA}:{SESION}"


@pytest.fixture
def exportador(monkeypatch):
    """Cliente de Langfuse real que exporta a memoria en vez de a Langfuse Cloud."""
    exportador = InMemorySpanExporter()
    cliente = Langfuse(
        # Clave distinta por test: el SDK reutiliza el cliente (y su exportador) por clave.
        public_key=f"pk-lf-test-{uuid.uuid4().hex}",
        secret_key="sk-lf-test",
        base_url="http://127.0.0.1:9",
        span_exporter=exportador,
        mask=enmascarar,
    )
    monkeypatch.setattr(obs, "_cliente", cliente)
    monkeypatch.setattr(obs, "_inicializado", True)
    yield exportador
    cliente.flush()


def _spans(exportador):
    obs._cliente.flush()
    return {s.name: s for s in exportador.get_finished_spans()}


def test_enmascarar_redacta_pii_en_estructuras_anidadas():
    datos = {
        "mensajes": [HumanMessage("mi correo es ana@mail.com y mi celular 987654321")],
        "tarjeta": ("paga con 4111 1111 1111 1111",),
        "peso": 12,
    }
    texto = json.dumps(enmascarar(data=datos), ensure_ascii=False)
    assert "ana@mail.com" not in texto and "[REDACTED_EMAIL]" in texto
    assert "987654321" not in texto and "[REDACTED_TELEFONO_PE]" in texto
    assert "4111" not in texto and "[REDACTED_CREDIT_CARD]" in texto
    assert '"peso": 12' in texto


def test_deshabilitado_es_un_no_op(monkeypatch):
    monkeypatch.setattr(obs, "_cliente", None)
    monkeypatch.setattr(obs, "_inicializado", False)
    monkeypatch.setattr(get_settings(), "langfuse_enabled", False)
    assert get_langfuse() is None
    assert callbacks() == []
    with trazar("chat", thread_id=THREAD) as traza:
        assert traza is None


def test_habilitado_sin_claves_no_inicia(monkeypatch):
    monkeypatch.setattr(obs, "_cliente", None)
    monkeypatch.setattr(obs, "_inicializado", False)
    monkeypatch.setattr(get_settings(), "langfuse_enabled", True)
    monkeypatch.setattr(get_settings(), "langfuse_public_key", None)
    assert get_langfuse() is None


async def test_traza_con_sesion_cliente_tienda_y_llm_enmascarado(exportador):
    modelo = GenericFakeChatModel(messages=iter(["Escribeme a soporte@tienda.com"]))
    with trazar("chat", thread_id=THREAD, cliente_id=CLIENTE, entrada="soy ana@mail.com") as traza:
        respuesta = await modelo.ainvoke("hola", config={"callbacks": callbacks()})
        traza.update(output=respuesta.content)

    spans = _spans(exportador)
    raiz = spans["chat"]
    attrs = dict(raiz.attributes)
    assert attrs["session.id"] == THREAD
    assert attrs["user.id"] == str(CLIENTE)
    assert attrs["langfuse.trace.metadata.tienda_id"] == str(TIENDA)
    assert f"tienda:{TIENDA}" in attrs["langfuse.trace.tags"]

    # La llamada al LLM cuelga de la traza del turno.
    hijos = [s for s in spans.values() if s.parent is not None and s.parent.span_id == raiz.context.span_id]
    assert hijos, "la llamada al LLM no quedo dentro de la traza"

    todo = json.dumps([dict(s.attributes) for s in spans.values()], ensure_ascii=False, default=str)
    assert "ana@mail.com" not in todo and "soporte@tienda.com" not in todo
    assert "[REDACTED_EMAIL]" in todo


async def test_sesion_anonima_no_envia_user_id(exportador):
    with trazar("chat", thread_id=THREAD, cliente_id=None):
        pass
    assert "user.id" not in dict(_spans(exportador)["chat"].attributes)


async def test_chat_traza_el_turno_aunque_langfuse_no_responda(exportador, monkeypatch):
    """/chat con Langfuse prendido (apuntando a un host que no responde): el turno se responde
    igual y queda una traza con la sesion del token y la entrada/salida enmascaradas."""
    import httpx

    from app.core.security import AuthContext, emitir_token
    from app.main import app

    monkeypatch.setattr(get_settings(), "jwt_secret", "secreto-de-test-de-al-menos-32-bytes!!")

    async def _fake_generate_reply(mensaje, thread_id, perfil=None):
        return "te escribo a ana@mail.com"

    monkeypatch.setattr("app.api.v1.routes.chat.generate_reply", _fake_generate_reply)
    ctx = AuthContext(tienda_id=TIENDA, session_id=SESION, cliente_id=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/chat", json={"mensaje": "hola, soy ana@mail.com"}, headers={"Authorization": f"Bearer {emitir_token(ctx)}"}
        )
    assert r.status_code == 200
    assert r.json()["respuesta"] == "te escribo a ana@mail.com"  # al cliente no se le enmascara

    attrs = dict(_spans(exportador)["chat"].attributes)
    assert attrs["session.id"] == ctx.thread_id
    assert "ana@mail.com" not in json.dumps(attrs, default=str)
    assert "[REDACTED_EMAIL]" in attrs["langfuse.observation.input"]
    assert "[REDACTED_EMAIL]" in attrs["langfuse.observation.output"]
