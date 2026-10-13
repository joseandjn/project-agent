"""Carga la guia nutricional de una tienda a Neo4j y la deja activa.

    python -m scripts.cargar_guia --tienda <tienda_id> data/guias/tienda_demo.yaml
    python -m scripts.cargar_guia --tienda <tienda_id> guia.yaml --sin-activar   # solo la guarda

Valida el YAML con el esquema (app/nutricion/guia.py) antes de tocar el grafo. Recargar la
misma version reemplaza sus reglas. La API toma la guia nueva en GUIA_CACHE_SEGUNDOS.
"""

import argparse
import sys
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.nutricion.grafo import guardar_guia
from app.nutricion.guia import cargar_yaml


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga una guia nutricional a Neo4j")
    parser.add_argument("guia", type=Path, help="YAML de la guia")
    parser.add_argument("--tienda", required=True, help="UUID de la tienda (tabla tiendas)")
    parser.add_argument("--sin-activar", action="store_true", help="Guardar la version sin activarla")
    args = parser.parse_args()

    tienda_id = str(uuid.UUID(args.tienda))  # valida el formato
    guia = cargar_yaml(args.guia)  # valida el contenido: si falla, no se toca Neo4j
    s = get_settings()
    if not s.neo4j_uri:
        print("NEO4J_URI no esta configurado", file=sys.stderr)
        return 1

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password or ""))
    try:
        n = guardar_guia(driver, tienda_id, guia.meta.tienda, guia, activar=not args.sin_activar)
    finally:
        driver.close()
    estado = "guardada" if args.sin_activar else "guardada y activa"
    print(f"Guia '{guia.meta.tienda}' v{guia.meta.version} {estado} para la tienda {tienda_id}: {n} reglas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
