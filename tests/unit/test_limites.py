"""Limites por turno (app/guardrails/limites.py) con modelos fake: un modelo que entra en
bucle, uno lento, uno que deriva dos veces y uno que falla (fallback). Verifica que el turno
cortado se borra de la sesion y que el siguiente turno funciona. Sin LLM ni Redis."""

import asyncio
import uuid
from typing import Any, List

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

import app.services.agente as agente_mod
from app.core.config import Settings, get_settings
from app.guardrails.limites import RESPUESTA_TURNO_INTERRUMPIDO
from app.memory.short_term.session_memory import historial
from app.models.tools import DerivacionVeterinario
from app.services import config_llm, llm_client


class _Modelo(BaseChatModel):
    """`modo`: "bucle" (siempre pide una tool), "lento" (tarda), "doble_derivacion" (pide
    derivar dos veces y despues responde), "roto" (falla), "ok" (responde)."""

    modo: str = "ok"
    texto: str = "respuesta ok"

    @property
    def _llm_type(self) -> str:
        return f"fake-{self.modo}"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_Modelo":
        return self

    def _llamada(self, nombre, args):
        return {"name": nombre, "args": args, "id": uuid.uuid4().hex}

    def _responder(self, messages: List) -> ChatResult:
        if self.modo == "roto":
            raise RuntimeError("proveedor caido")
        if self.modo == "bucle":
            msg = AIMessage("", tool_calls=[self._llamada("consultar_disponibilidad", {"sku": "DOG-ADU-GRA-POL-003"})])
        elif self.modo == "doble_derivacion" and isinstance(messages[-1], HumanMessage):
            msg = AIMessage("", tool_calls=[self._llamada("derivar_veterinario", {"motivo": "a"}), self._llamada("derivar_veterinario", {"motivo": "b"})])
        else:
            msg = AIMessage(self.texto)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._responder(messages)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.modo == "lento":
            await asyncio.sleep(5)
        return self._responder(messages)


@pytest.fixture
def entorno(monkeypatch):
    """Checkpointer en memoria para v1 y v2, derivaciones sin escribir archivos."""
    saver = InMemorySaver()

    async def _get():
        return saver

    monkeypatch.setattr(llm_client, "get_checkpointer", _get)
    monkeypatch.setattr(agente_mod, "get_checkpointer", _get)
    derivaciones = []

    def _derivar(motivo, session_id):
        derivaciones.append(motivo)
        return DerivacionVeterinario(id="DER-test", session_id=session_id, motivo=motivo, fecha="2026-10-13")

    monkeypatch.setattr("app.tools.langchain_tools._derivar_veterinario", _derivar)

    def usar(modelo, version):
        monkeypatch.setattr(llm_client, "get_chat_model", lambda: modelo)
        monkeypatch.setattr(agente_mod, "get_chat_model", lambda: modelo)
        agente_mod.reset_agente()
        return llm_client.generate_reply if version == "v1" else agente_mod.generar_respuesta

    yield {"saver": saver, "usar": usar, "derivaciones": derivaciones}
    agente_mod.reset_agente()


VERSIONES = ["v1", "v2"]


@pytest.mark.parametrize("version", VERSIONES)
async def test_bucle_de_tools_se_corta_y_el_turno_se_borra(entorno, version):
    responder = entorno["usar"](_Modelo(modo="ok", texto="hola"), version)
    thread = f"t:bucle:{version}"
    await responder("primer mensaje", thread)

    responder = entorno["usar"](_Modelo(modo="bucle"), version)
    assert await responder("busca", thread) == RESPUESTA_TURNO_INTERRUMPIDO
    mensajes = await historial(entorno["saver"], thread)
    assert [m.content for m in mensajes if isinstance(m, HumanMessage)] == ["primer mensaje"]
    assert not any(isinstance(m, ToolMessage) for m in mensajes)  # no quedan tool calls colgadas

    # El turno siguiente funciona (no hay una tool call sin respuesta en el historial).
    responder = entorno["usar"](_Modelo(modo="ok", texto="sigo aqui"), version)
    assert await responder("hola de nuevo", thread) == "sigo aqui"


@pytest.mark.parametrize("version", VERSIONES)
async def test_turno_lento_se_corta_por_timeout(entorno, monkeypatch, version):
    monkeypatch.setattr(get_settings(), "agente_timeout_segundos", 0.3)
    responder = entorno["usar"](_Modelo(modo="lento"), version)
    thread = f"t:lento:{version}"
    assert await responder("hola", thread) == RESPUESTA_TURNO_INTERRUMPIDO
    assert await historial(entorno["saver"], thread) == []


@pytest.mark.parametrize("version", VERSIONES)
async def test_derivar_veterinario_una_sola_vez_por_turno(entorno, version):
    responder = entorno["usar"](_Modelo(modo="doble_derivacion", texto="te derive"), version)
    assert await responder("mi perro vomita", f"t:deriva:{version}") == "te derive"
    assert entorno["derivaciones"] == ["a"]


@pytest.mark.parametrize("version", VERSIONES)
async def test_si_el_modelo_falla_responde_el_de_respaldo(entorno, monkeypatch, version):
    monkeypatch.setattr(config_llm, "build_fallback_model", lambda s: _Modelo(modo="ok", texto="soy el respaldo"))
    responder = entorno["usar"](_Modelo(modo="roto"), version)
    assert await responder("hola", f"t:fallback:{version}") == "soy el respaldo"


def test_modelo_de_respaldo_formato():
    s = Settings(_env_file=None, llm_provider="ollama", openai_api_key="sk-test")
    assert config_llm.build_fallback_model(s) is None
    s.llm_fallback_model = "llama3.2:3b"  # ":" de la etiqueta de Ollama, no un proveedor
    assert (m := config_llm.build_fallback_model(s)).model == "llama3.2:3b" and type(m).__name__ == "ChatOllama"
    s.llm_fallback_model = "openai:gpt-4.1-mini"
    assert (m := config_llm.build_fallback_model(s)).model_name == "gpt-4.1-mini" and type(m).__name__ == "ChatOpenAI"


def test_requests_al_proveedor_con_timeout_y_reintentos():
    s = Settings(_env_file=None, llm_provider="openai", openai_api_key="sk-test", llm_timeout_segundos=12, llm_max_reintentos=1)
    m = config_llm.build_chat_model(s)
    assert (m.request_timeout, m.max_retries) == (12, 1)


def test_config_rechaza_un_tope_de_pasos_que_cortaria_turnos_normales():
    with pytest.raises(ValueError, match="AGENTE_MAX_PASOS"):
        Settings(_env_file=None, agente_max_pasos=25, agente_max_llamadas_modelo=6)
    Settings(_env_file=None)  # los valores por defecto son coherentes
