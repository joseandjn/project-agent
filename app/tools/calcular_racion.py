from typing import Optional

from app.models.tools import RacionCalculada
from app.tools.catalog import get_producto_by_sku

# Ver data/conocimiento/guias_nutricion.md: heuristica de referencia, no validada por un
# veterinario. Reemplazar por la guia real antes de un uso productivo.
PORCENTAJE_DIARIO_POR_ETAPA = {
    "cachorro": 0.04,
    "adulto": 0.025,
    "senior": 0.02,
    "todas las edades": 0.025,
}


def calcular_racion(peso_mascota_kg: float, sku: str) -> Optional[RacionCalculada]:
    """Python puro: racion diaria, duracion del empaque y costo mensual segun las guias
    de nutricion. No usa el LLM ni el catalogo con precio de memoria: lee del catalogo."""
    producto = get_producto_by_sku(sku)
    if producto is None:
        return None

    etapa = producto["etapa"][0] if producto["etapa"] else "adulto"
    porcentaje = PORCENTAJE_DIARIO_POR_ETAPA.get(etapa.lower(), 0.025)

    racion_diaria_kg = peso_mascota_kg * porcentaje
    duracion_dias = round(producto["peso_kg"] / racion_diaria_kg) if racion_diaria_kg > 0 else None
    costo_mensual = round(racion_diaria_kg * 30 * producto["precio_por_kg"], 2)

    return RacionCalculada(
        sku=sku,
        racion_diaria_g=round(racion_diaria_kg * 1000, 1),
        duracion_dias=duracion_dias,
        costo_mensual=costo_mensual,
    )
