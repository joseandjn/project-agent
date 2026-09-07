import httpx
import pytest

from app.tools.langchain_tools import build_tools
from app.core.config import get_settings


def _ollama_disponible() -> bool:
    settings = get_settings()
    try:
        httpx.get(settings.ollama_base_url, timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _ollama_disponible(), reason="Ollama no esta corriendo en OLLAMA_BASE_URL")


async def test_buscar_alimentos_tool_incluye_nota_de_no_inventar_precio():
    tools = {t.name: t for t in build_tools(session_id="test-session")}
    resultado = await tools["buscar_alimentos"].ainvoke({"consulta": "alimento para perro", "especie": "Perro"})

    assert "productos" in resultado
    assert "nota" in resultado
    assert len(resultado["productos"]) > 0
