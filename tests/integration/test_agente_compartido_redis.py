"""Agente compartido (/api/v2/chat) contra Redis real: el historial persiste entre turnos en
el checkpoint, y si el checkpointer se cierra y se reabre el agente se vuelve a crear. El LLM
es un fake. Requiere Redis (RediSearch) en REDIS_URL; si no, se saltea."""

import asyncio
import uuid

import pytest
from langchain_core.messages import HumanMessage

import app.services.agente as agente_mod
from app.memory.long_term.consolidacion import close_redis, get_redis
from app.memory.short_term.session_memory import close_checkpointer, get_checkpointer, session_config
from app.services.agente import generar_respuesta, get_agente
from tests.unit.test_agente_compartido import _ModeloDeriva


async def _redis_listo() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False
    finally:
        await close_redis()


pytestmark = pytest.mark.skipif(not asyncio.run(_redis_listo()), reason="Redis no disponible")


@pytest.fixture
async def thread_id(monkeypatch):
    monkeypatch.setattr(agente_mod, "get_chat_model", lambda: _ModeloDeriva(prompts=[]))
    monkeypatch.setattr("app.tools.langchain_tools._derivar_veterinario", lambda motivo, session_id: _Derivacion())
    agente_mod.reset_agente()
    thread = f"test-v2:{uuid.uuid4()}"
    yield thread
    await (await get_checkpointer()).adelete_thread(thread)
    agente_mod.reset_agente()
    await close_checkpointer()


class _Derivacion:
    def model_dump(self):
        return {"id": "DER-test"}


async def _humanos(thread: str):
    agente = await get_agente()
    estado = await agente.aget_state(session_config(thread))
    return [m.content for m in estado.values["messages"] if isinstance(m, HumanMessage)]


async def test_historial_persiste_y_sobrevive_a_reabrir_redis(thread_id):
    await generar_respuesta("primer mensaje", thread_id)
    primero = await get_agente()

    # Se cierra el checkpointer (como en un reinicio de la conexion): el agente se recrea
    # con el nuevo y el historial sigue en Redis.
    await close_checkpointer()
    await generar_respuesta("segundo mensaje", thread_id)
    assert await get_agente() is not primero
    assert await _humanos(thread_id) == ["primer mensaje", "segundo mensaje"]
