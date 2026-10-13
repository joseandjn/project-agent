"""Guias nutricionales contra Neo4j real: carga, lectura de la version activa por tienda,
cambio de version e idempotencia. Requiere Neo4j (NEO4J_URI en .env); si no, se saltea.
Usa tiendas con UUID aleatorio y las borra al terminar."""

import uuid
from pathlib import Path

import pytest

from app.core.config import Settings, get_settings
from app.nutricion import repo
from app.nutricion.grafo import guardar_guia
from app.nutricion.guia import cargar_yaml

GUIA = cargar_yaml(Path(__file__).resolve().parents[2] / "data" / "guias" / "tienda_demo.yaml")
_cfg = Settings()  # lee .env directo (el conftest apaga NEO4J_URI en get_settings())


def _driver():
    from neo4j import GraphDatabase

    return GraphDatabase.driver(_cfg.neo4j_uri, auth=(_cfg.neo4j_user, _cfg.neo4j_password or ""), connection_timeout=3)


def _neo4j_listo() -> bool:
    if not _cfg.neo4j_uri:
        return False
    try:
        with _driver() as d:
            d.verify_connectivity()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _neo4j_listo(), reason="Neo4j no disponible")


@pytest.fixture
async def neo4j(monkeypatch):
    monkeypatch.setattr(get_settings(), "neo4j_uri", _cfg.neo4j_uri)
    monkeypatch.setattr(get_settings(), "neo4j_password", _cfg.neo4j_password)
    monkeypatch.setattr(get_settings(), "guia_cache_segundos", 0)
    tiendas = []
    driver = _driver()

    def nueva_tienda():
        tiendas.append(str(uuid.uuid4()))
        return tiendas[-1]

    yield driver, nueva_tienda
    with driver.session() as s:
        s.run(
            "MATCH (t:Tienda) WHERE t.id IN $ids OPTIONAL MATCH (t)-[:TIENE_GUIA]->(g)-[:DEFINE]->(r) "
            "DETACH DELETE r, g, t",
            ids=tiendas,
        )
    driver.close()
    await repo.close_neo4j()


def _con_racion_cachorro(pct: float, version: int):
    datos = GUIA.model_dump()
    datos["meta"]["version"] = version
    for r in datos["energia"]:
        if r["metodo"] == "porcentaje_peso":
            r["pct_peso"] = pct
    return type(GUIA).model_validate(datos)


def _reglas_activas(driver, tienda):
    with driver.session() as s:
        return s.run(
            "MATCH (:Tienda {id: $t})-[:GUIA_ACTIVA]->(:Guia)-[:DEFINE]->(r) RETURN count(r) AS n", t=tienda
        ).single()["n"]


async def test_carga_y_lectura_por_tienda(neo4j):
    driver, nueva_tienda = neo4j
    tienda = nueva_tienda()
    n = guardar_guia(driver, tienda, "Tienda Test", GUIA)
    guia, origen = await repo.guia_activa(tienda)
    assert origen == "neo4j" and guia == GUIA
    assert _reglas_activas(driver, tienda) == n


async def test_recargar_la_misma_version_no_duplica(neo4j):
    driver, nueva_tienda = neo4j
    tienda = nueva_tienda()
    n = guardar_guia(driver, tienda, "Tienda Test", GUIA)
    guardar_guia(driver, tienda, "Tienda Test", GUIA)
    assert _reglas_activas(driver, tienda) == n


async def test_activar_otra_version_y_tiendas_separadas(neo4j):
    driver, nueva_tienda = neo4j
    a, b = nueva_tienda(), nueva_tienda()
    guardar_guia(driver, a, "Tienda A", GUIA)
    guardar_guia(driver, b, "Tienda B", _con_racion_cachorro(5, version=1))

    assert (await repo.guia_activa(a))[0].regla_energia("Perro", "Cachorro").pct_peso == 4
    assert (await repo.guia_activa(b))[0].regla_energia("Perro", "Cachorro").pct_peso == 5

    # Version 2 de la tienda A: se guarda sin activar y despues se activa.
    guardar_guia(driver, a, "Tienda A", _con_racion_cachorro(3.5, version=2), activar=False)
    assert (await repo.guia_activa(a))[0].meta.version == 1
    guardar_guia(driver, a, "Tienda A", _con_racion_cachorro(3.5, version=2))
    guia_a = (await repo.guia_activa(a))[0]
    assert guia_a.meta.version == 2 and guia_a.regla_energia("Perro", "Cachorro").pct_peso == 3.5
    assert (await repo.guia_activa(b))[0].regla_energia("Perro", "Cachorro").pct_peso == 5


async def test_borrador_no_se_puede_activar(neo4j):
    driver, nueva_tienda = neo4j
    datos = GUIA.model_dump()
    datos["meta"]["estado"] = "borrador"
    with pytest.raises(ValueError, match="aprobada"):
        guardar_guia(driver, nueva_tienda(), "Tienda Test", type(GUIA).model_validate(datos))


async def test_tienda_sin_guia_usa_la_por_defecto(neo4j):
    _, nueva_tienda = neo4j
    guia, origen = await repo.guia_activa(nueva_tienda())
    assert origen == "por_defecto" and guia.meta.tienda == "Tienda Demo"
