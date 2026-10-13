import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "catalogo" / "alimentos.json"


@lru_cache
def get_catalog() -> List[Dict[str, Any]]:
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_producto_by_sku(sku: str) -> Optional[Dict[str, Any]]:
    for producto in get_catalog():
        if producto["sku"] == sku:
            return producto
    return None


def get_producto_por_sku_o_nombre(valor: str) -> Optional[Dict[str, Any]]:
    """Por SKU o por nombre exacto (sin distinguir mayusculas): el LLM a veces pasa el nombre
    del producto en lugar del SKU. Los nombres del catalogo son unicos."""
    if producto := get_producto_by_sku(valor.strip()):
        return producto
    nombre = valor.strip().casefold()
    return next((p for p in get_catalog() if p["nombre"].casefold() == nombre), None)
