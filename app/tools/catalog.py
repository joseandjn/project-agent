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
