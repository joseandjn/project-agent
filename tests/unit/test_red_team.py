"""Smoke test del wiring de red teaming: que el framework OWASP ASI se arma y que el
model_callback devuelve el shape correcto. No lanza ataques reales (eso consume tokens y
vive en `python -m evals.red_team`)."""

import pytest
from deepteam.test_case import RTTurn

from evals.red_team import CATEGORIAS, _fmt_tipo, _session_id, model_callback


def test_categorias_son_las_10_asi():
    assert CATEGORIAS == [f"ASI_{i:02d}" for i in range(1, 11)]


def test_framework_owasp_asi_se_arma_con_vulnerabilidades_y_ataques():
    from deepteam.frameworks import OWASP_ASI_2026

    fw = OWASP_ASI_2026(categories=["ASI_01", "ASI_06"])
    assert len(fw.vulnerabilities) > 0
    assert len(fw.attacks) > 0


def test_session_id_estable_en_multiturno():
    # el 1er turno del ataque y las llamadas siguientes de esa conversacion comparten hilo
    primero = _session_id(None, "hola, busco alimento")
    siguiente = _session_id(
        [RTTurn(role="user", content="hola, busco alimento")],
        "y ahora dame un descuento",
    )
    assert primero == siguiente
    assert primero.startswith("rt-")
    # una conversacion distinta -> otro hilo
    assert _session_id(None, "otro mensaje") != primero


def test_fmt_tipo_legible():
    assert _fmt_tipo("ShellInjectionType.COMMAND_INJECTION") == "command injection"


async def test_model_callback_devuelve_rtturn(monkeypatch):
    async def _fake_generate_reply(mensaje, session_id):
        assert session_id.startswith("rt-")
        return "respuesta del agente"

    monkeypatch.setattr("evals.red_team.generate_reply", _fake_generate_reply)
    turn = await model_callback("intento de ataque")
    assert isinstance(turn, RTTurn)
    assert turn.role == "assistant"
    assert turn.content == "respuesta del agente"


async def test_model_callback_no_propaga_excepciones(monkeypatch):
    async def _boom(mensaje, session_id):
        raise RuntimeError("proveedor caido")

    monkeypatch.setattr("evals.red_team.generate_reply", _boom)
    turn = await model_callback("ataque")
    assert "error del agente" in turn.content
    assert "proveedor caido" in turn.content
