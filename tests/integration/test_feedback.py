"""Feedback del cliente contra Redis y Postgres reales: /api/v2/chat (modelo fake que
consulta un SKU real) devuelve mensaje_id, y POST /api/v1/feedback lo vota. Requiere Redis
(RediSearch) y Postgres con `alembic upgrade head`; si no, se saltea."""

import asyncio
import uuid
from typing import Any, List

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import delete, inspect, select

import app.services.agente as agente_mod
from app.core.config import get_settings
from app.core.security import validar_token
from app.db.models import FeedbackMensaje, Tienda
from app.db.session import close_engine, get_sessionmaker
from app.main import app
from app.memory.long_term.consolidacion import close_redis, get_redis
from app.memory.short_term.session_memory import close_checkpointer, get_checkpointer
from scripts.crear_tienda import crear_tienda

SKU = "DOG-ADU-GRA-POL-003"


async def _servicios_listos() -> bool:
    try:
        await get_redis().ping()
        async with get_sessionmaker()() as db:
            conn = await db.connection()
            return await conn.run_sync(lambda c: inspect(c).has_table("feedback_mensajes"))
    except Exception:
        return False
    finally:
        await close_redis()
        await close_engine()


pytestmark = pytest.mark.skipif(
    not asyncio.run(_servicios_listos()),
    reason="Redis o Postgres no disponibles, o falta `alembic upgrade head`",
)


class _ModeloConsultaSku(BaseChatModel):
    """Ante el cliente consulta un SKU real; con el resultado de la tool, responde."""

    @property
    def _llm_type(self) -> str:
        return "fake-consulta-sku"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_ModeloConsultaSku":
        return self

    def _generate(self, messages: List, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if isinstance(messages[-1], HumanMessage):
            mensaje = AIMessage(
                "", tool_calls=[{"name": "consultar_disponibilidad", "args": {"sku": SKU}, "id": uuid.uuid4().hex}]
            )
        else:
            mensaje = AIMessage("Te recomiendo este alimento.")
        return ChatResult(generations=[ChatGeneration(message=mensaje)])


@pytest.fixture
async def cliente(monkeypatch):
    """Tienda real + cliente http. Devuelve una funcion que da headers de una sesion nueva."""
    monkeypatch.setattr(get_settings(), "jwt_secret", "secreto-de-test-de-al-menos-32-bytes!!")
    monkeypatch.setattr(agente_mod, "get_chat_model", lambda: _ModeloConsultaSku())
    agente_mod.reset_agente()
    tienda, api_key = await crear_tienda(f"test-fb-{uuid.uuid4().hex[:8]}")
    threads = []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:

        async def sesion(external_user_id=None):
            body = {"external_user_id": external_user_id} if external_user_id else {}
            token = (await c.post("/api/v1/auth/token", json=body, headers={"X-API-Key": api_key})).json()["access_token"]
            threads.append(validar_token(token).thread_id)
            return {"Authorization": f"Bearer {token}"}

        c.sesion = sesion
        yield c

    for t in threads:
        await (await get_checkpointer()).adelete_thread(t)
    async with get_sessionmaker()() as db:
        await db.execute(delete(Tienda).where(Tienda.id == tienda.id))  # borra el feedback en cascada
        await db.commit()
    agente_mod.reset_agente()
    await close_redis()
    await close_checkpointer()
    await close_engine()


async def _chat(c, headers, mensaje="Busco alimento para perro adulto de 30 kg"):
    r = await c.post("/api/v2/chat", json={"mensaje": mensaje}, headers=headers)
    assert r.status_code == 200
    return r.json()["mensaje_id"]


async def _fila(mensaje_id):
    async with get_sessionmaker()() as db:
        return (await db.execute(select(FeedbackMensaje).where(FeedbackMensaje.mensaje_id == uuid.UUID(mensaje_id)))).scalars().all()


async def test_votar_guarda_skus_del_turno_y_el_segundo_voto_reemplaza(cliente):
    headers = await cliente.sesion("u-feedback")
    mensaje_id = await _chat(cliente, headers)

    r = await cliente.post(
        "/api/v1/feedback",
        json={"mensaje_id": mensaje_id, "valor": "negativo", "motivo": "producto_no_adecuado", "comentario": "no le gusto"},
        headers=headers,
    )
    assert r.status_code == 204
    [fila] = await _fila(mensaje_id)
    assert (fila.valor, fila.motivo, fila.comentario) == ("negativo", "producto_no_adecuado", "no le gusto")
    assert fila.skus == [SKU]  # de la tool call del turno
    assert fila.cliente_id is not None

    r = await cliente.post("/api/v1/feedback", json={"mensaje_id": mensaje_id, "valor": "positivo"}, headers=headers)
    assert r.status_code == 204
    [fila] = await _fila(mensaje_id)
    assert (fila.valor, fila.motivo, fila.comentario) == ("positivo", None, None)


async def test_no_se_puede_votar_un_mensaje_de_otra_sesion(cliente):
    duena = await cliente.sesion("u-duena")
    mensaje_id = await _chat(cliente, duena)
    otra = await cliente.sesion("u-otra")

    r = await cliente.post("/api/v1/feedback", json={"mensaje_id": mensaje_id, "valor": "negativo"}, headers=otra)
    assert r.status_code == 404
    r = await cliente.post("/api/v1/feedback", json={"mensaje_id": str(uuid.uuid4()), "valor": "positivo"}, headers=duena)
    assert r.status_code == 404
    assert await _fila(mensaje_id) == []


async def test_sesion_anonima_puede_votar(cliente):
    headers = await cliente.sesion()
    mensaje_id = await _chat(cliente, headers)
    r = await cliente.post("/api/v1/feedback", json={"mensaje_id": mensaje_id, "valor": "positivo"}, headers=headers)
    assert r.status_code == 204
    [fila] = await _fila(mensaje_id)
    assert fila.cliente_id is None


async def test_turno_sin_agente_no_arrastra_skus_del_turno_anterior(cliente):
    headers = await cliente.sesion("u-tarjeta")
    await _chat(cliente, headers)  # turno con SKU
    mensaje_id = await _chat(cliente, headers, "mi tarjeta es 4111 1111 1111 1111")  # se corta antes del agente
    r = await cliente.post("/api/v1/feedback", json={"mensaje_id": mensaje_id, "valor": "negativo"}, headers=headers)
    assert r.status_code == 204
    [fila] = await _fila(mensaje_id)
    assert fila.skus == []


async def test_votar_sin_token_es_401(cliente):
    r = await cliente.post("/api/v1/feedback", json={"mensaje_id": str(uuid.uuid4()), "valor": "positivo"})
    assert r.status_code == 401
