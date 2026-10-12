"""Agente compartido de `/api/v2/chat` (app/services/agente.py): se crea una vez y lo usan
varios requests a la vez, asi que lo de cada turno (sesion, perfil) tiene que viajar en el
contexto y no mezclarse. Sin Redis ni LLM: checkpointer en memoria y un modelo fake."""

import asyncio
import uuid
from typing import Any, List

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

import app.services.agente as agente_mod
from app.agent.prompts.system_prompt import SYSTEM_PROMPT
from app.core.config import get_settings
from app.core.security import AuthContext, emitir_token
from app.main import app
from app.memory.long_term.models import Mascota, PerfilCliente
from app.models.tools import DerivacionVeterinario
from app.services.agente import generar_respuesta, get_agente
from app.services.llm_client import RESPUESTA_TARJETA_BLOQUEADA


class _ModeloDeriva(BaseChatModel):
    """Ante un mensaje del cliente pide `derivar_veterinario`; con el resultado de la tool,
    responde. Guarda el system prompt de cada llamada para ver que perfil recibio."""

    prompts: List[str] = []

    @property
    def _llm_type(self) -> str:
        return "fake-deriva"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_ModeloDeriva":
        return self

    def _responder(self, messages: List[BaseMessage]) -> ChatResult:
        sistema = next((m.content for m in messages if isinstance(m, SystemMessage)), "")
        self.prompts.append(sistema)
        if isinstance(messages[-1], HumanMessage):
            mensaje = AIMessage(
                "",
                tool_calls=[{"name": "derivar_veterinario", "args": {"motivo": messages[-1].content}, "id": uuid.uuid4().hex}],
            )
        else:
            mensaje = AIMessage("Te derive con el veterinario.")
        return ChatResult(generations=[ChatGeneration(message=mensaje)])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._responder(messages)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        await asyncio.sleep(0.01)  # deja que los turnos simultaneos se intercalen
        return self._responder(messages)


@pytest.fixture
def modelo(monkeypatch):
    modelo = _ModeloDeriva(prompts=[])
    checkpointer = InMemorySaver()

    async def _get_checkpointer():
        return checkpointer

    monkeypatch.setattr(agente_mod, "get_chat_model", lambda: modelo)
    monkeypatch.setattr(agente_mod, "get_checkpointer", _get_checkpointer)
    agente_mod.reset_agente()
    yield modelo
    agente_mod.reset_agente()


@pytest.fixture
def derivaciones(monkeypatch):
    """Reemplaza la escritura de DER-*.json: registra (motivo, session_id)."""
    registro = []

    def _fake(motivo, session_id):
        registro.append((motivo, session_id))
        return DerivacionVeterinario(id="DER-test", session_id=session_id, motivo=motivo, fecha="2026-10-12")

    monkeypatch.setattr("app.tools.langchain_tools._derivar_veterinario", _fake)
    return registro


async def test_el_agente_se_crea_una_sola_vez(modelo, derivaciones, monkeypatch):
    creados = []
    original = agente_mod.create_agent

    def _contar(*args, **kwargs):
        creados.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(agente_mod, "create_agent", _contar)
    for i in range(3):
        await generar_respuesta(f"vomita {i}", f"t:{i}")
    assert len(creados) == 1
    assert await get_agente() is await get_agente()


async def test_se_recrea_si_cambia_el_checkpointer(modelo, monkeypatch):
    primero = await get_agente()
    otro = InMemorySaver()

    async def _otro_checkpointer():
        return otro

    monkeypatch.setattr(agente_mod, "get_checkpointer", _otro_checkpointer)
    assert await get_agente() is not primero


async def test_sesiones_simultaneas_no_se_mezclan(modelo, derivaciones):
    """Dos clientes a la vez sobre el mismo agente: cada derivacion lleva su propio thread_id
    y cada system prompt su propio perfil."""
    # Nombres que no aparecen en SYSTEM_PROMPT (que usa "Rocky" como ejemplo).
    firulais = PerfilCliente(mascotas=[Mascota(nombre="Firulais", especie="Perro")])
    pelusa = PerfilCliente(mascotas=[Mascota(nombre="Pelusa", especie="Gato")])
    turnos = [("tA:s1", "firulais vomita", firulais), ("tB:s2", "pelusa no come", pelusa)] * 5

    await asyncio.gather(*(generar_respuesta(m, t, p) for t, m, p in turnos))

    assert len(derivaciones) == len(turnos)
    for motivo, session_id in derivaciones:
        esperado = "tA:s1" if motivo.startswith("firulais") else "tB:s2"
        assert session_id == esperado, f"{motivo!r} quedo en la sesion {session_id}"

    con_firulais = [p for p in modelo.prompts if "Firulais" in p]
    con_pelusa = [p for p in modelo.prompts if "Pelusa" in p]
    assert con_firulais and con_pelusa
    assert not [p for p in modelo.prompts if "Firulais" in p and "Pelusa" in p]


async def test_el_prompt_incluye_el_perfil_solo_si_hay(modelo, derivaciones):
    await generar_respuesta("hola", "t:anonimo")
    assert modelo.prompts[0] == SYSTEM_PROMPT

    perfil = PerfilCliente(mascotas=[Mascota(nombre="Toby", especie="Perro")])
    await generar_respuesta("hola", "t:cliente", perfil)
    assert modelo.prompts[-1].startswith(SYSTEM_PROMPT) and "<perfil_cliente>" in modelo.prompts[-1]


async def test_el_historial_sigue_por_sesion(modelo, derivaciones):
    agente = await get_agente()
    await generar_respuesta("primer mensaje", "t:hist")
    await generar_respuesta("segundo mensaje", "t:hist")
    estado = await agente.aget_state({"configurable": {"thread_id": "t:hist"}})
    humanos = [m.content for m in estado.values["messages"] if isinstance(m, HumanMessage)]
    assert humanos == ["primer mensaje", "segundo mensaje"]


async def test_tarjeta_se_corta_antes_del_agente(modelo):
    assert await generar_respuesta("mi tarjeta es 4111 1111 1111 1111", "t:x") == RESPUESTA_TARJETA_BLOQUEADA
    assert modelo.prompts == []


# --- Ruta /api/v2/chat -------------------------------------------------------------------


@pytest.fixture
def llamadas_v2(monkeypatch):
    monkeypatch.setattr(get_settings(), "jwt_secret", "secreto-de-test-de-al-menos-32-bytes!!")
    registro = []

    async def _fake(mensaje, thread_id, perfil=None):
        registro.append((mensaje, thread_id))
        return "respuesta v2"

    monkeypatch.setattr("app.api.v2.routes.chat.generar_respuesta", _fake)
    return registro


async def _post_v2(json, headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.post("/api/v2/chat", json=json, headers=headers or {})


async def test_v2_sin_token_responde_401(llamadas_v2):
    assert (await _post_v2({"mensaje": "hola"})).status_code == 401
    assert llamadas_v2 == []


async def test_v2_la_sesion_sale_del_token(llamadas_v2):
    ctx = AuthContext(tienda_id=uuid.uuid4(), session_id=uuid.uuid4(), cliente_id=None)
    r = await _post_v2({"mensaje": "hola"}, {"Authorization": f"Bearer {emitir_token(ctx)}"})
    assert r.status_code == 200
    assert r.json() == {"respuesta": "respuesta v2", "session_id": str(ctx.session_id)}
    assert llamadas_v2 == [("hola", ctx.thread_id)]
