"""Carga el catalogo de alimentos (data/catalogo/alimentos.json) como grafo en Neo4j.

Modelo:
    (:Producto)-[:PARA_ESPECIE]->(:Especie)
    (:Producto)-[:PARA_ETAPA]->(:Etapa)
    (:Producto)-[:PARA_TAMANO]->(:TamanoRaza)
    (:Producto)-[:PROTEINA_PRINCIPAL]->(:Proteina)
    (:Producto)-[:ES_TIPO]->(:TipoAlimento)
    (:Producto)-[:CONTIENE]->(:Ingrediente)

Uso:
    docker compose up -d neo4j
    python -m graph_neo4j.load_catalogo
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

CATALOGO_PATH = Path(__file__).resolve().parent.parent / "data" / "catalogo" / "alimentos.json"

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "vethis1234")

CONSTRAINTS = [
    "CREATE CONSTRAINT producto_sku IF NOT EXISTS FOR (n:Producto) REQUIRE n.sku IS UNIQUE",
    "CREATE CONSTRAINT especie_nombre IF NOT EXISTS FOR (n:Especie) REQUIRE n.nombre IS UNIQUE",
    "CREATE CONSTRAINT etapa_nombre IF NOT EXISTS FOR (n:Etapa) REQUIRE n.nombre IS UNIQUE",
    "CREATE CONSTRAINT tamano_nombre IF NOT EXISTS FOR (n:TamanoRaza) REQUIRE n.nombre IS UNIQUE",
    "CREATE CONSTRAINT proteina_nombre IF NOT EXISTS FOR (n:Proteina) REQUIRE n.nombre IS UNIQUE",
    "CREATE CONSTRAINT tipo_nombre IF NOT EXISTS FOR (n:TipoAlimento) REQUIRE n.nombre IS UNIQUE",
    "CREATE CONSTRAINT ingrediente_nombre IF NOT EXISTS FOR (n:Ingrediente) REQUIRE n.nombre IS UNIQUE",
]

WIPE = """
MATCH (n)
WHERE n:Producto OR n:Especie OR n:Etapa OR n:TamanoRaza
   OR n:Proteina OR n:TipoAlimento OR n:Ingrediente
DETACH DELETE n
"""

MERGE_PRODUCTO = """
MERGE (p:Producto {sku: $sku})
SET p.nombre = $nombre,
    p.presentacion = $presentacion,
    p.peso_kg = $peso_kg,
    p.precio_por_kg = $precio_por_kg,
    p.precio_regular = $precio_regular,
    p.disponible = $disponible,
    p.stock = $stock,
    p.url_producto = $url_producto
WITH p
MERGE (esp:Especie {nombre: $especie})
MERGE (p)-[:PARA_ESPECIE]->(esp)
WITH p
MERGE (tam:TamanoRaza {nombre: $tamano_raza})
MERGE (p)-[:PARA_TAMANO]->(tam)
WITH p
MERGE (prot:Proteina {nombre: $proteina_principal})
MERGE (p)-[:PROTEINA_PRINCIPAL]->(prot)
WITH p
MERGE (tipo:TipoAlimento {nombre: $tipo_alimento})
MERGE (p)-[:ES_TIPO]->(tipo)
WITH p
UNWIND $etapas AS etapa_nombre
MERGE (et:Etapa {nombre: etapa_nombre})
MERGE (p)-[:PARA_ETAPA]->(et)
WITH DISTINCT p
UNWIND $ingredientes AS ing_nombre
MERGE (ing:Ingrediente {nombre: ing_nombre})
MERGE (p)-[:CONTIENE]->(ing)
"""


def _params(producto: dict) -> dict:
    return {
        "sku": producto["sku"],
        "nombre": producto["nombre"],
        "presentacion": producto["presentacion"],
        "especie": producto["especie"],
        "etapas": producto["etapa"],
        "tipo_alimento": producto["tipo_alimento"],
        "tamano_raza": producto["tamano_raza"],
        "proteina_principal": producto["proteina_principal"],
        "ingredientes": producto["ingredientes"],
        "peso_kg": producto["peso_kg"],
        "precio_por_kg": producto["precio_por_kg"],
        "precio_regular": producto["precio_regular"],
        "disponible": producto["disponible"],
        "stock": producto["stock"],
        "url_producto": producto["url_producto"],
    }


def cargar_catalogo(wipe: bool = True) -> int:
    alimentos = json.loads(CATALOGO_PATH.read_text(encoding="utf-8"))

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            if wipe:
                session.run(WIPE)
            for constraint in CONSTRAINTS:
                session.run(constraint)
            for producto in alimentos:
                session.run(MERGE_PRODUCTO, **_params(producto))
    finally:
        driver.close()

    return len(alimentos)


if __name__ == "__main__":
    total = cargar_catalogo()
    print(f"Catalogo cargado en Neo4j: {total} productos ({NEO4J_URI}).")
    print("Explora el grafo en http://localhost:7474")
