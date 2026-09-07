import httpx
import pytest

from app.core.config import get_settings
from app.tools.buscar_alimentos import buscar_alimentos


def _ollama_disponible() -> bool:
    settings = get_settings()
    try:
        httpx.get(settings.ollama_base_url, timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _ollama_disponible(), reason="Ollama no esta corriendo en OLLAMA_BASE_URL")


async def test_busqueda_respeta_filtro_de_especie_y_etapa():
    resultados = await buscar_alimentos(
        "alimento para mi cachorro de raza pequena",
        especie="Perro",
        etapa_vida="Cachorro",
    )

    assert len(resultados) > 0
    for item in resultados:
        assert item.especie == "Perro"
        assert "Cachorro" in item.etapa


async def test_busqueda_excluye_medicados_por_defecto():
    resultados = await buscar_alimentos("alimento renal para mi perro", especie="Perro", limit=20)
    assert all("MED" not in item.sku for item in resultados)


async def test_busqueda_respeta_precio_max():
    precio_max = 15.0
    resultados = await buscar_alimentos("alimento para perro adulto", especie="Perro", precio_max=precio_max)

    assert len(resultados) > 0
    from app.tools.catalog import get_producto_by_sku

    for item in resultados:
        producto = get_producto_by_sku(item.sku)
        assert producto["precio_por_kg"] <= precio_max


async def test_busqueda_sin_resultados_si_filtros_no_calzan():
    resultados = await buscar_alimentos("algo", especie="Perro", etapa_vida="Cachorro", precio_max=0.01)
    assert resultados == []
