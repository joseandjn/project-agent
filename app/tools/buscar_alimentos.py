from typing import List, Optional

from app.models.tools import AlimentoResumen, ScoreDesglose
from app.tools.catalog import get_catalog
from app.tools.embeddings import cosine_similarity, embed_text, get_catalog_embeddings
from app.tools.scoring import calcular_confianza_feedback


def _cumple_filtros_duros(
    producto: dict,
    especie: Optional[str],
    etapa_vida: Optional[str],
    precio_max: Optional[float],
    incluir_medicados: bool,
) -> bool:
    if not incluir_medicados and producto["tipo_alimento"] == "Medicado":
        return False
    if especie and producto["especie"].lower() != especie.lower():
        return False
    if etapa_vida and etapa_vida.lower() not in [e.lower() for e in producto["etapa"]]:
        return False
    if precio_max is not None and producto["precio_por_kg"] > precio_max:
        return False
    return True


def _ajuste_presupuesto(precio_por_kg: float, precio_max: Optional[float]) -> float:
    if precio_max is None or precio_max <= 0:
        return 0.5
    return max(0.0, min(1.0, 1 - (precio_por_kg / precio_max)))


async def buscar_alimentos(
    consulta: str,
    especie: Optional[str] = None,
    etapa_vida: Optional[str] = None,
    precio_max: Optional[float] = None,
    incluir_medicados: bool = False,
    limit: int = 5,
) -> List[AlimentoResumen]:
    """Busqueda semantica + filtros duros sobre el catalogo. Fichas resumidas SIN precio:
    el precio solo lo devuelve consultar_disponibilidad (unica fuente citable)."""
    candidatos = [
        producto
        for producto in get_catalog()
        if _cumple_filtros_duros(producto, especie, etapa_vida, precio_max, incluir_medicados)
    ]
    if not candidatos:
        return []

    query_vector = await embed_text(consulta)
    catalog_vectors = await get_catalog_embeddings()
    confianza_por_sku = calcular_confianza_feedback()

    resultados = []
    for producto in candidatos:
        afinidad = cosine_similarity(query_vector, catalog_vectors[producto["sku"]])
        confianza = confianza_por_sku.get(producto["sku"], 0.5)
        ajuste = _ajuste_presupuesto(producto["precio_por_kg"], precio_max)
        total = 0.5 * afinidad + 0.3 * confianza + 0.2 * ajuste

        resultados.append(
            AlimentoResumen(
                sku=producto["sku"],
                nombre=producto["nombre"],
                presentacion=producto["presentacion"],
                especie=producto["especie"],
                etapa=producto["etapa"],
                proteina_principal=producto["proteina_principal"],
                score=ScoreDesglose(
                    afinidad_semantica=round(afinidad, 3),
                    confianza_feedback=round(confianza, 3),
                    ajuste_presupuesto=round(ajuste, 3),
                    total=round(total, 3),
                ),
            )
        )

    resultados.sort(key=lambda r: r.score.total, reverse=True)
    return resultados[:limit]
