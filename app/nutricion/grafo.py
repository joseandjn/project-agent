"""Guias nutricionales en Neo4j (docs/guia_nutricional_neo4j.md).

Modelo:

    (:Tienda {id})-[:TIENE_GUIA]->(:Guia {tienda_id, version, estado, contenido, ...})
    (:Tienda)-[:GUIA_ACTIVA]->(:Guia)                 # una sola: activar es mover esta relacion
    (:Guia)-[:DEFINE]->(regla)                        # ReglaEnergia, ReglaPremio, RiesgoPremio,
                                                      # ReglaToxicos, ReglaCondicionCorporal,
                                                      # ReglaSeleccion, ReglaTransicion, ReglaCondicion
    (regla)-[:PARA_ESPECIE]->(:Especie)               # mismos nodos que el grafo del catalogo
    (regla)-[:PARA_ETAPA]->(:Etapa)
    (:ReglaToxicos)-[:PROHIBE]->(:Ingrediente)
    (:ReglaCondicion)-[:SOBRE]->(:Condicion)
    (regla)-[:SUSTENTADA_EN]->(:Fuente {id, titulo, url})

Lectura: `Guia.contenido` guarda el contenido canonico validado (JSON). El agente lee la
version activa de su tienda en una consulta y la valida de nuevo con Pydantic; los nodos de
reglas sirven para consultas cruzadas (p. ej. reglas por especie, ingredientes prohibidos).
Cargar la misma version de nuevo reemplaza sus reglas (idempotente).
"""

import json
from typing import Any, Dict, List, Optional

from app.nutricion.guia import Guia

CONSTRAINTS = [
    "CREATE CONSTRAINT tienda_id IF NOT EXISTS FOR (n:Tienda) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT guia_version IF NOT EXISTS FOR (n:Guia) REQUIRE (n.tienda_id, n.version) IS UNIQUE",
    "CREATE CONSTRAINT fuente_id IF NOT EXISTS FOR (n:Fuente) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT condicion_nombre IF NOT EXISTS FOR (n:Condicion) REQUIRE n.nombre IS UNIQUE",
    # Vocabulario compartido con el grafo del catalogo (graph_neo4j/load_catalogo.py).
    "CREATE CONSTRAINT especie_nombre IF NOT EXISTS FOR (n:Especie) REQUIRE n.nombre IS UNIQUE",
    "CREATE CONSTRAINT etapa_nombre IF NOT EXISTS FOR (n:Etapa) REQUIRE n.nombre IS UNIQUE",
    "CREATE CONSTRAINT ingrediente_nombre IF NOT EXISTS FOR (n:Ingrediente) REQUIRE n.nombre IS UNIQUE",
]

_GUIA = """
MERGE (t:Tienda {id: $tienda_id}) SET t.nombre = $tienda_nombre
MERGE (g:Guia {tienda_id: $tienda_id, version: $version})
SET g.estado = $estado, g.aprobada_por = $aprobada_por, g.aviso = $aviso,
    g.contenido = $contenido, g.cargada_en = datetime()
MERGE (t)-[:TIENE_GUIA]->(g)
WITH g
OPTIONAL MATCH (g)-[:DEFINE]->(r)
DETACH DELETE r
"""

_FUENTES = """
UNWIND $fuentes AS f
MERGE (n:Fuente {id: f.id}) SET n.titulo = f.titulo, n.url = f.url
"""

_ACTIVAR = """
MATCH (t:Tienda {id: $tienda_id})
OPTIONAL MATCH (t)-[a:GUIA_ACTIVA]->()
DELETE a
WITH t
MATCH (g:Guia {tienda_id: $tienda_id, version: $version})
MERGE (t)-[:GUIA_ACTIVA]->(g)
"""

LEER_ACTIVA = """
MATCH (:Tienda {id: $tienda_id})-[:GUIA_ACTIVA]->(g:Guia)
RETURN g.contenido AS contenido, g.version AS version
"""

ETIQUETAS = {
    "ReglaEnergia", "ReglaPremio", "RiesgoPremio", "ReglaToxicos", "ReglaCondicionCorporal",
    "ReglaSeleccion", "ReglaTransicion", "ReglaCondicion",
}


def _reglas(guia: Guia) -> List[Dict[str, Any]]:
    """Cada regla de la guia como {etiqueta, props, especies, etapas, fuentes, prohibe, sobre}."""
    reglas: List[Dict[str, Any]] = []

    def agregar(etiqueta, props, fuentes, especies=(), etapas=(), prohibe=(), sobre=None):
        reglas.append({
            "etiqueta": etiqueta,
            "props": {k: v for k, v in props.items() if v is not None},
            "especies": list(especies), "etapas": list(etapas), "fuentes": list(fuentes),
            "prohibe": list(prohibe), "sobre": sobre,
        })

    for r in guia.energia:
        agregar("ReglaEnergia", {
            "metodo": r.metodo, "formula": r.formula, "pct_peso": r.pct_peso, "rango": r.rango, "nota": r.nota,
            "kcal_min_factor": r.kcal_min.factor if r.kcal_min else None,
            "kcal_min_exponente": r.kcal_min.exponente if r.kcal_min else None,
            "kcal_max_factor": r.kcal_max.factor if r.kcal_max else None,
            "kcal_max_exponente": r.kcal_max.exponente if r.kcal_max else None,
        }, r.fuente, r.especie, r.etapas)
    for r in guia.premios:
        agregar("ReglaPremio", {"regla": r.regla, "max_porcentaje_kcal": r.max_porcentaje_kcal,
                                "deriva_veterinario": r.deriva_veterinario}, r.fuente, r.especie)
    for r in guia.riesgos_premios:
        agregar("RiesgoPremio", {"riesgo": r.riesgo}, r.fuente, r.especie)
    for r in guia.toxicos:
        agregar("ReglaToxicos", {"nota": r.nota}, r.fuente, r.especie,
                prohibe=[i.strip().capitalize() for i in r.ingredientes])
    cc = guia.condicion_corporal
    for r in cc.por_especie:
        agregar("ReglaCondicionCorporal", {"escala": cc.escala, "ideal_min": r.ideal[0], "ideal_max": r.ideal[1],
                                           "senales_ideal": r.senales_ideal, "nota": r.nota,
                                           "regla_asesor": cc.regla_asesor, "deriva_veterinario": cc.deriva_veterinario},
                r.fuente + cc.fuente_regla, r.especie)
    for r in guia.seleccion_alimento:
        agregar("ReglaSeleccion", {"regla": r.regla}, r.fuente)
    t = guia.transicion
    agregar("ReglaTransicion", {"dias": t.dias, "pasos": t.pasos, "nota": t.nota}, t.fuente)
    for c in guia.condiciones_derivar:
        agregar("ReglaCondicion", {"deriva_veterinario": True}, guia.fuente_condiciones_derivar, sobre=c)
    return reglas


def _crear_regla(tx, tienda_id: str, version: int, regla: Dict[str, Any]) -> None:
    etiqueta = regla["etiqueta"]
    if etiqueta not in ETIQUETAS:  # la etiqueta va interpolada: solo valores conocidos
        raise ValueError(f"Etiqueta de regla desconocida: {etiqueta}")
    tx.run(
        f"""
        MATCH (g:Guia {{tienda_id: $tienda_id, version: $version}})
        CREATE (g)-[:DEFINE]->(r:{etiqueta})
        SET r = $props
        WITH r
        CALL (r) {{ UNWIND $especies AS e MERGE (n:Especie {{nombre: e}}) MERGE (r)-[:PARA_ESPECIE]->(n) }}
        CALL (r) {{ UNWIND $etapas AS e MERGE (n:Etapa {{nombre: e}}) MERGE (r)-[:PARA_ETAPA]->(n) }}
        CALL (r) {{ UNWIND $fuentes AS f MATCH (n:Fuente {{id: f}}) MERGE (r)-[:SUSTENTADA_EN]->(n) }}
        CALL (r) {{ UNWIND $prohibe AS i MERGE (n:Ingrediente {{nombre: i}}) MERGE (r)-[:PROHIBE]->(n) }}
        CALL (r) {{ WITH r WHERE $sobre IS NOT NULL MERGE (n:Condicion {{nombre: $sobre}}) MERGE (r)-[:SOBRE]->(n) }}
        """,
        tienda_id=tienda_id, version=version, props=regla["props"], especies=regla["especies"],
        etapas=regla["etapas"], fuentes=regla["fuentes"], prohibe=regla["prohibe"], sobre=regla["sobre"],
    )


def guardar_guia(driver, tienda_id: str, tienda_nombre: str, guia: Guia, activar: bool = True) -> int:
    """Carga (o recarga) una version de la guia de una tienda y, si `activar`, la deja activa.
    Usa el driver sincrono de neo4j. Devuelve cuantas reglas creo."""
    if guia.meta.estado != "aprobada" and activar:
        raise ValueError("Solo se puede activar una guia con estado 'aprobada'")
    reglas = _reglas(guia)
    with driver.session() as s:
        for c in CONSTRAINTS:
            s.run(c)

        def _tx(tx):
            tx.run(_GUIA, tienda_id=tienda_id, tienda_nombre=tienda_nombre, version=guia.meta.version,
                   estado=guia.meta.estado, aprobada_por=guia.meta.aprobada_por, aviso=guia.meta.aviso,
                   contenido=guia.model_dump_json())
            tx.run(_FUENTES, fuentes=[{"id": k, "titulo": f.titulo, "url": f.url} for k, f in guia.fuentes.items()])
            for regla in reglas:
                _crear_regla(tx, tienda_id, guia.meta.version, regla)
            if activar:
                tx.run(_ACTIVAR, tienda_id=tienda_id, version=guia.meta.version)

        s.execute_write(_tx)  # todo o nada: no queda una version a medio cargar
    return len(reglas)


def guia_desde_registro(contenido: Optional[str]) -> Optional[Guia]:
    return Guia.model_validate(json.loads(contenido)) if contenido else None
