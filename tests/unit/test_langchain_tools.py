import pytest
from pydantic import ValidationError

from app.tools.langchain_tools import build_tools


def _tools_by_name(session_id="test-session"):
    return {t.name: t for t in build_tools(session_id)}


async def test_calcular_racion_coacciona_peso_string_a_numero():
    """Regresion: Ollama puede devolver peso_mascota_kg como '4' (string). El schema
    auto-generado por @tool debe coaccionarlo a float."""
    tools = _tools_by_name()
    resultado = await tools["calcular_racion"].ainvoke({"peso_mascota_kg": "4", "sku": "DOG-CACH-PEQ-POL-001"})
    assert resultado["racion_diaria_g"] == 160.0


async def test_calcular_racion_argumento_invalido_lanza_validation_error():
    tools = _tools_by_name()
    with pytest.raises(ValidationError):
        await tools["calcular_racion"].ainvoke({"peso_mascota_kg": "no-es-numero", "sku": "DOG-CACH-PEQ-POL-001"})


async def test_consultar_disponibilidad_sku_inexistente_retorna_error_sin_crashear():
    tools = _tools_by_name()
    resultado = await tools["consultar_disponibilidad"].ainvoke({"sku": "SKU-QUE-NO-EXISTE"})
    assert "error" in resultado


async def test_derivar_veterinario_usa_el_session_id_inyectado_no_uno_del_llm(tmp_path, monkeypatch):
    """El session_id SIEMPRE lo inyecta Python via closure: la tool ni siquiera expone
    ese parametro en su schema, asi que el LLM no puede sobreescribirlo."""
    from app.tools import derivar_veterinario as mod

    monkeypatch.setattr(mod, "DERIVACIONES_DIR", tmp_path)

    tools = _tools_by_name(session_id="id-real-de-la-sesion")
    assert "session_id" not in tools["derivar_veterinario"].args

    resultado = await tools["derivar_veterinario"].ainvoke({"motivo": "sintoma reportado"})
    assert resultado["session_id"] == "id-real-de-la-sesion"
