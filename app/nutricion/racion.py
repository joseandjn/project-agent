"""Racion diaria segun la guia de la tienda (funciones puras, sin Neo4j).

- Adultos y seniors: energia diaria de la guia (WSAVA / NRC 2006) / kcal por kg del producto.
- Cachorros y gatitos: % del peso corporal (regla de demo de la guia).
- Premios: maximo de gramos por dia para no superar el % de calorias de la guia.
- Dietas veterinarias: no se calcula; la cantidad la indica el veterinario.
Todo se devuelve como rango, con la fuente y el aviso de la guia.
"""

from typing import Any, Dict, Optional

from app.nutricion.guia import Guia


def _redondear(g: float) -> int:
    return int(5 * round(g / 5))  # a 5 g: una racion no se mide al gramo


def _etapa_por_defecto(producto: Dict[str, Any]) -> str:
    etapas = [e for e in producto["etapa"] if e != "Todas las edades"]
    return etapas[0] if etapas else "Adulto"


def calcular_racion(guia: Guia, producto: Dict[str, Any], peso_kg: float, etapa: Optional[str] = None) -> Dict[str, Any]:
    analisis = producto.get("analisis") or {}
    base = {"sku": producto["sku"], "aviso": guia.meta.aviso}

    if analisis.get("dieta_veterinaria"):
        return {
            **base,
            "dieta_veterinaria": True,
            "deriva_veterinario": True,
            "mensaje": "Es una dieta veterinaria: la cantidad diaria la indica el veterinario que la prescribe.",
        }

    especie = producto["especie"]
    etapa = etapa or _etapa_por_defecto(producto)
    kcal_kg = analisis.get("kcal_por_kg")

    if analisis.get("categoria") == "premio":
        regla = guia.regla_energia(especie, "Adulto")
        pct = guia.max_pct_premios(especie)
        if not (regla and regla.metodo == "kcal" and pct and kcal_kg):
            return {**base, "error": "La guia no permite calcular la cantidad de premios para esta mascota"}
        kcal_premios = regla.kcal_diarias(peso_kg)[0] * pct / 100  # sobre el minimo: conservador
        return {
            **base,
            "es_premio": True,
            "max_gramos_dia": _redondear(kcal_premios / kcal_kg * 1000),
            "max_kcal_dia": round(kcal_premios),
            "regla": f"Los premios no deben superar el {pct:g}% de las calorias diarias y nunca reemplazan una comida.",
            "fuentes": guia.citas([f for r in guia.premios if especie in r.especie for f in r.fuente]),
        }

    regla = guia.regla_energia(especie, etapa)
    if regla is None:
        return {**base, "error": f"La guia no tiene una regla de racion para {especie} {etapa}"}

    if regla.metodo == "kcal":
        if not kcal_kg:
            return {**base, "error": "El producto no tiene informacion de calorias"}
        kcal = regla.kcal_diarias(peso_kg)
        gramos = (kcal[0] / kcal_kg * 1000, kcal[1] / kcal_kg * 1000)
        extra = {"kcal_dia": [round(kcal[0]), round(kcal[1])]}
    else:
        g = peso_kg * regla.pct_peso / 100 * 1000
        gramos = (g, g)
        extra = {"kcal_dia": None}

    empaque_g = producto["peso_kg"] * 1000
    return {
        **base,
        **extra,
        "etapa": etapa,
        "racion_diaria_g": [_redondear(gramos[0]), _redondear(gramos[1])],
        "duracion_dias": [int(empaque_g // gramos[1]), int(empaque_g // gramos[0])],
        "costo_mensual_soles": [
            round(gramos[0] * 30 / 1000 * producto["precio_por_kg"], 2),
            round(gramos[1] * 30 / 1000 * producto["precio_por_kg"], 2),
        ],
        "metodo": regla.formula,
        "nota": regla.nota,
        "fuentes": guia.citas(regla.fuente),
    }
