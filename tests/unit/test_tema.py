"""Control de tema (app/guardrails/tema.py) con un clasificador fake: categorias que pasan,
plantillas, ejecucion en paralelo con el agente y borrado del turno cuando se bloquea.
Sin LLM ni Redis (checkpointer en memoria)."""

import asyncio
import time

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver

import app.guardrails.tema as tema
import app.services.agente as agente_mod
from app.core.config import get_settings
from app.guardrails.tema import ClasificacionTema, respuesta_para, responder_con_control
from app.memory.short_term.session_memory import historial
from app.services import llm_client


class _ModeloFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class _Clasificador:
    """Imita `with_structured_output(...)`: devuelve `categoria` (tras `demora` s) y guarda la entrada."""

    def __init__(self, categoria=None, error=None, demora=0.0):
        self.categoria, self.error, self.demora, self.entradas = categoria, error, demora, []

    def with_structured_output(self, schema):
        async def _invocar(mensajes):
            self.entradas.append(mensajes[1].content)
            await asyncio.sleep(self.demora)
            if self.error:
                raise self.error
            return ClasificacionTema(categoria=self.categoria)

        return RunnableLambda(_invocar)


@pytest.fixture
def con_tema(monkeypatch):
    monkeypatch.setattr(get_settings(), "tema_guard_enabled", True)

    def _usar(clasificador):
        monkeypatch.setattr(tema, "get_tema_model", lambda: clasificador)
        return clasificador

    return _usar


def _agente(respuesta="respuesta del agente", demora=0.0, error=None):
    """`correr_agente` fake: anota si termino o fue cancelado."""
    estado = {"termino": False, "cancelado": False}

    async def correr():
        try:
            await asyncio.sleep(demora)
        except asyncio.CancelledError:
            estado["cancelado"] = True
            raise
        if error:
            raise error
        estado["termino"] = True
        return respuesta

    return correr, estado


async def _nada():
    return None


# --- responder_con_control ----------------------------------------------------------------


@pytest.mark.parametrize("categoria", ["fuera_de_dominio", "salud_humana", "malestar_emocional", "riesgo"])
async def test_bloqueadas_cancelan_el_agente_y_responden_plantilla(con_tema, categoria):
    con_tema(_Clasificador(categoria))
    correr, estado = _agente(demora=1)
    deshechos = []

    async def deshacer():
        deshechos.append(True)

    assert await responder_con_control("algo", [], correr, deshacer) == respuesta_para(categoria)
    assert estado["cancelado"] and deshechos == [True]


@pytest.mark.parametrize("categoria", ["mascotas", "conversacion"])
async def test_permitidas_devuelven_el_agente(con_tema, categoria):
    con_tema(_Clasificador(categoria))
    correr, _ = _agente()
    assert await responder_con_control("algo", [], correr, _nada) == "respuesta del agente"


async def test_corren_en_paralelo(con_tema):
    """Clasificador 0,3 s + agente 0,3 s: en paralelo tarda ~0,3 s, no ~0,6 s."""
    con_tema(_Clasificador("mascotas", demora=0.3))
    correr, _ = _agente(demora=0.3)
    inicio = time.perf_counter()
    await responder_con_control("algo", [], correr, _nada)
    assert time.perf_counter() - inicio < 0.5


async def test_fuera_de_tema_no_espera_al_agente(con_tema):
    con_tema(_Clasificador("fuera_de_dominio", demora=0.05))
    correr, _ = _agente(demora=5)
    inicio = time.perf_counter()
    await responder_con_control("algo", [], correr, _nada)
    assert time.perf_counter() - inicio < 1


async def test_si_el_agente_termino_antes_igual_se_espera_al_clasificador(con_tema):
    con_tema(_Clasificador("salud_humana", demora=0.2))
    correr, estado = _agente(demora=0)
    assert await responder_con_control("algo", [], correr, _nada) == respuesta_para("salud_humana")
    assert estado["termino"]  # termino, pero su respuesta no se uso


async def test_bloqueado_aunque_el_agente_falle(con_tema):
    con_tema(_Clasificador("riesgo"))
    correr, _ = _agente(error=RuntimeError("boom"))
    assert await responder_con_control("algo", [], correr, _nada) == respuesta_para("riesgo")


async def test_si_el_clasificador_falla_pasa_al_agente(con_tema):
    con_tema(_Clasificador(error=RuntimeError("timeout")))
    correr, _ = _agente()
    assert await responder_con_control("algo", [], correr, _nada) == "respuesta del agente"


async def test_si_falla_el_deshacer_igual_responde_la_plantilla(con_tema):
    con_tema(_Clasificador("fuera_de_dominio"))
    correr, _ = _agente()

    async def deshacer_roto():
        raise RuntimeError("redis caido")

    assert await responder_con_control("algo", [], correr, deshacer_roto) == respuesta_para("fuera_de_dominio")


async def test_deshabilitado_no_clasifica(con_tema, monkeypatch):
    clasificador = con_tema(_Clasificador("fuera_de_dominio"))
    monkeypatch.setattr(get_settings(), "tema_guard_enabled", False)
    correr, _ = _agente()
    assert await responder_con_control("algo", [], correr, _nada) == "respuesta del agente"
    assert clasificador.entradas == []


async def test_el_clasificador_ve_los_turnos_previos(con_tema):
    clasificador = con_tema(_Clasificador("conversacion"))
    correr, _ = _agente()
    await responder_con_control("20 kg", [HumanMessage("Tengo un perro"), AIMessage("¿Cuánto pesa?")], correr, _nada)
    entrada = clasificador.entradas[0]
    assert "Cliente: Tengo un perro" in entrada and "Asesor: ¿Cuánto pesa?" in entrada
    assert "<ultimo_mensaje>\n20 kg\n</ultimo_mensaje>" in entrada


def test_plantillas_de_malestar_y_riesgo_incluyen_lineas_de_ayuda(monkeypatch):
    monkeypatch.setattr(get_settings(), "tema_ayuda_salud_mental", "LINEA-X")
    monkeypatch.setattr(get_settings(), "tema_ayuda_emergencia", "EMERGENCIA-Y")
    assert "LINEA-X" in respuesta_para("malestar_emocional")
    assert "LINEA-X" in respuesta_para("riesgo") and "EMERGENCIA-Y" in respuesta_para("riesgo")


# --- Integrado en v1 y v2: el turno bloqueado no queda en la sesion -------------------------


@pytest.fixture
def checkpointer(monkeypatch):
    saver = InMemorySaver()

    async def _get():
        return saver

    monkeypatch.setattr(llm_client, "get_checkpointer", _get)
    monkeypatch.setattr(agente_mod, "get_checkpointer", _get)
    agente_mod.reset_agente()
    yield saver
    agente_mod.reset_agente()


async def _humanos(saver, thread):
    return [m.content for m in await historial(saver, thread) if isinstance(m, HumanMessage)]


@pytest.mark.parametrize("version", ["v1", "v2"])
async def test_turno_bloqueado_se_borra_de_la_sesion(con_tema, checkpointer, monkeypatch, version):
    monkeypatch.setattr(llm_client, "get_chat_model", lambda: _ModeloFake(messages=iter(["r1", "r2", "r3"])))
    monkeypatch.setattr(agente_mod, "get_chat_model", lambda: _ModeloFake(messages=iter(["r1", "r2", "r3"])))
    responder = llm_client.generate_reply if version == "v1" else agente_mod.generar_respuesta
    thread = f"t:{version}"

    con_tema(_Clasificador("mascotas"))
    assert await responder("tengo un perro", thread) == "r1"
    # El agente fake responde al instante: el turno fuera de tema llega a guardarse y se borra.
    con_tema(_Clasificador("malestar_emocional", demora=0.1))
    assert await responder("ando muy triste", thread) == respuesta_para("malestar_emocional")
    assert await _humanos(checkpointer, thread) == ["tengo un perro"]

    con_tema(_Clasificador("mascotas"))
    await responder("pesa 20 kg", thread)
    assert await _humanos(checkpointer, thread) == ["tengo un perro", "pesa 20 kg"]
