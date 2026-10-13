"""Consultas de ejemplo sobre el grafo de catalogo cargado por load_catalogo.py.

Uso:
    python -m graph_neo4j.queries
"""

import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]  # del .env (sin valor por defecto en el codigo)


def resumen_schema(driver) -> dict:
    query = "MATCH (n) RETURN labels(n)[0] AS etiqueta, count(*) AS total ORDER BY total DESC"
    with driver.session() as session:
        return {row["etiqueta"]: row["total"] for row in session.run(query)}


def productos_para(especie: str, etapa: str, driver) -> list[dict]:
    query = """
    MATCH (p:Producto)-[:PARA_ESPECIE]->(:Especie {nombre: $especie}),
          (p)-[:PARA_ETAPA]->(:Etapa {nombre: $etapa})
    RETURN p.nombre AS nombre, p.precio_regular AS precio, p.disponible AS disponible
    ORDER BY p.precio_regular
    """
    with driver.session() as session:
        return [row.data() for row in session.run(query, especie=especie, etapa=etapa)]


def alternativas_sin_proteina(sku: str, proteina_excluida: str, driver) -> list[dict]:
    """Productos de la misma especie que `sku`, que comparten al menos un ingrediente con el
    y no usan `proteina_excluida`.

    Sirve como aproximacion a un pedido tipo "algo parecido pero sin pollo".
    """
    query = """
    MATCH (origen:Producto {sku: $sku})-[:CONTIENE]->(ing:Ingrediente)<-[:CONTIENE]-(alt:Producto)
    WHERE alt.sku <> $sku
    MATCH (origen)-[:PARA_ESPECIE]->(esp:Especie)<-[:PARA_ESPECIE]-(alt)
    MATCH (alt)-[:PROTEINA_PRINCIPAL]->(prot:Proteina)
    WHERE prot.nombre <> $proteina_excluida
    RETURN DISTINCT alt.nombre AS nombre, prot.nombre AS proteina,
           count(ing) AS ingredientes_compartidos
    ORDER BY ingredientes_compartidos DESC
    """
    with driver.session() as session:
        return [
            row.data()
            for row in session.run(query, sku=sku, proteina_excluida=proteina_excluida)
        ]


if __name__ == "__main__":
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        print("--- Nodos por tipo ---")
        for etiqueta, total in resumen_schema(driver).items():
            print(f"{etiqueta}: {total}")

        print("\n--- Alimentos para Gato / Cachorro ---")
        for row in productos_para("Gato", "Cachorro", driver):
            print(row)

        print("\n--- Alternativas a CAT-KIT-POL-012 sin Pollo ---")
        for row in alternativas_sin_proteina("CAT-KIT-POL-012", "Pollo", driver):
            print(row)
    finally:
        driver.close()
