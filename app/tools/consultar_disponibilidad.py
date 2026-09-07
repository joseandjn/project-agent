from typing import Optional

from app.models.tools import Disponibilidad
from app.tools.catalog import get_producto_by_sku


def consultar_disponibilidad(sku: str) -> Optional[Disponibilidad]:
    """Unica fuente citable de precio, precio por kg, stock y link del producto.
    El LLM nunca debe redactar estos datos de memoria: solo puede citar lo que esta tool
    devuelve. Python puro, sin llamadas a LLM."""
    producto = get_producto_by_sku(sku)
    if producto is None:
        return None

    return Disponibilidad(
        sku=producto["sku"],
        precio_regular=producto["precio_regular"],
        precio_por_kg=producto["precio_por_kg"],
        disponible=producto["disponible"],
        stock=producto["stock"],
        url_producto=producto["url_producto"],
    )
