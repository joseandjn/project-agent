"""Lo que exponen las tools del agente sobre nutricion (app/tools/langchain_tools.py).

La tienda sale del `thread_id` de la sesion (Python), nunca del LLM: cada cliente recibe la
guia activa de SU tienda.
"""

from typing import Any, Dict, Literal, Optional

from app.nutricion.racion import calcular_racion
from app.nutricion.repo import guia_activa, tienda_de
from app.tools.catalog import get_producto_por_sku_o_nombre

Tema = Literal[
    "toxicos", "premios", "condicion_corporal", "transicion", "como_elegir", "energia", "condiciones_que_derivan"
]


async def racion_para(thread_id: str, peso_mascota_kg: float, sku: str, etapa_vida: Optional[str] = None) -> Dict[str, Any]:
    producto = get_producto_por_sku_o_nombre(sku)
    if not producto:
        return {"error": "SKU no encontrado en el catalogo"}
    guia, origen = await guia_activa(tienda_de(thread_id))
    return {**calcular_racion(guia, producto, peso_mascota_kg, etapa_vida), "origen_guia": origen}


async def consultar_guia(thread_id: str, especie: str, tema: Tema) -> Dict[str, Any]:
    guia, origen = await guia_activa(tienda_de(thread_id))
    base = {"tema": tema, "especie": especie, "aviso": guia.meta.aviso, "origen_guia": origen}

    if tema == "toxicos":
        reglas = [r for r in guia.toxicos if especie in r.especie]
        return {**base, "no_dar_nunca": [i for r in reglas for i in r.ingredientes],
                "nota": " ".join(r.nota for r in reglas if r.nota) or None,
                "fuentes": guia.citas([f for r in reglas for f in r.fuente])}
    if tema == "premios":
        reglas = [r for r in guia.premios if especie in r.especie]
        riesgos = [r for r in guia.riesgos_premios if especie in r.especie]
        return {**base, "reglas": [r.regla for r in reglas], "riesgos": [r.riesgo for r in riesgos],
                "fuentes": guia.citas(sorted({f for r in reglas + riesgos for f in r.fuente}))}
    if tema == "condicion_corporal":
        cc = guia.condicion_corporal
        r = next((x for x in cc.por_especie if especie in x.especie), None)
        if r is None:
            return {**base, "error": "La guia no tiene condicion corporal para esa especie"}
        return {**base, "escala": cc.escala, "ideal": list(r.ideal), "senales_ideal": r.senales_ideal,
                "nota": r.nota, "regla_asesor": cc.regla_asesor, "deriva_veterinario": cc.deriva_veterinario,
                "fuentes": guia.citas(r.fuente)}
    if tema == "transicion":
        t = guia.transicion
        return {**base, "dias": t.dias, "pasos": t.pasos, "nota": t.nota, "fuentes": guia.citas(t.fuente)}
    if tema == "como_elegir":
        return {**base, "reglas": [r.regla for r in guia.seleccion_alimento],
                "fuentes": guia.citas(sorted({f for r in guia.seleccion_alimento for f in r.fuente}))}
    if tema == "energia":
        reglas = [r for r in guia.energia if especie in r.especie]
        return {**base, "reglas": [{"etapas": r.etapas, "formula": r.formula, "nota": r.nota} for r in reglas],
                "fuentes": guia.citas(sorted({f for r in reglas for f in r.fuente}))}
    if tema == "condiciones_que_derivan":
        return {**base, "condiciones": guia.condiciones_derivar,
                "regla": "Ante cualquiera de estas condiciones, derivar al veterinario y no recomendar una dieta."}
    return {**base, "error": f"Tema desconocido: {tema}"}


def ficha_producto(sku: str) -> Dict[str, Any]:
    producto = get_producto_por_sku_o_nombre(sku)
    if not producto:
        return {"error": "SKU no encontrado en el catalogo"}
    analisis = dict(producto.get("analisis") or {})
    es_demo = analisis.pop("es_demo", False)
    return {
        "sku": producto["sku"],
        "nombre": producto["nombre"],
        "presentacion": producto["presentacion"],
        "especie": producto["especie"],
        "etapa": producto["etapa"],
        "tamano_raza": producto["tamano_raza"],
        "tipo_alimento": producto["tipo_alimento"],
        "proteina_principal": producto["proteina_principal"],
        "ingredientes": producto["ingredientes"],
        "descripcion": producto["documento_busqueda"],
        "analisis_garantizado": analisis,
        "nota": "Valores de demostracion (catalogo ficticio)." if es_demo else None,
    }
