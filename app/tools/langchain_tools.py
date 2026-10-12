from typing import List, Literal, Optional

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, tool

from app.agent.contexto import Contexto

from app.tools.buscar_alimentos import buscar_alimentos as _buscar_alimentos
from app.tools.calcular_racion import calcular_racion as _calcular_racion
from app.tools.consultar_disponibilidad import consultar_disponibilidad as _consultar_disponibilidad
from app.tools.derivar_veterinario import derivar_veterinario as _derivar_veterinario

BUSCAR_ALIMENTOS_NOTA = (
    "Estas fichas NO incluyen precio, stock ni link: nunca inventes ni estimes esos "
    "datos. Si el cliente pregunto por precio, stock o link, tu siguiente paso (ahora, "
    "en este mismo turno, sin anunciarlo ni pedir permiso) es llamar a "
    "consultar_disponibilidad con el sku exacto de la ficha elegida, y recien con ese "
    "resultado responder al cliente."
)


# Tools que no dependen de la sesion: se definen una sola vez y las comparten el agente
# por request (`build_tools`) y el agente compartido (`TOOLS_CON_CONTEXTO`).


@tool
async def buscar_alimentos(
    consulta: str,
    especie: Optional[Literal["Perro", "Gato"]] = None,
    etapa_vida: Optional[Literal["Cachorro", "Adulto", "Senior", "Todas las edades"]] = None,
    precio_max: Optional[float] = None,
) -> dict:
    """Busca alimentos del catalogo por especie, etapa de vida y presupuesto.
    Devuelve fichas resumidas SIN precio: para precio, stock o link usar
    consultar_disponibilidad con el sku.

    especie SOLO puede ser "Perro" o "Gato" (nunca la etapa de vida ni la raza).
    etapa_vida SOLO puede ser "Cachorro", "Adulto", "Senior" o "Todas las edades"
    (traduce edades como "3 meses" a la etapa correspondiente: "Cachorro").
    Los tres filtros son opcionales: si el cliente no dio ese dato, OMITE el
    parametro por completo (no envies "ninguno", "n/a" ni texto similar)."""
    resultados = await _buscar_alimentos(
        consulta=consulta, especie=especie, etapa_vida=etapa_vida, precio_max=precio_max
    )
    return {"productos": [r.model_dump() for r in resultados], "nota": BUSCAR_ALIMENTOS_NOTA}


@tool
def consultar_disponibilidad(sku: str) -> dict:
    """Unica fuente valida de precio, precio por kg, stock y link del producto.
    Usar siempre antes de citarle al cliente un precio o un link."""
    resultado = _consultar_disponibilidad(sku)
    if not resultado:
        return {"error": "SKU no encontrado en el catalogo"}
    return {
        "sku": resultado.sku,
        "precio_total_de_la_presentacion_soles": resultado.precio_regular,
        "precio_por_kg_soles": resultado.precio_por_kg,
        "disponible": resultado.disponible,
        "stock_unidades": resultado.stock,
        "url_producto": resultado.url_producto,
        "nota": "No existe ninguna promocion: son dos precios distintos, no el mismo en dos formatos.",
    }


@tool
def calcular_racion(peso_mascota_kg: float, sku: str) -> dict:
    """Calcula la racion diaria, cuanto dura el empaque y el costo mensual de un
    producto para una mascota de un peso dado."""
    resultado = _calcular_racion(peso_mascota_kg, sku)
    return resultado.model_dump() if resultado else {"error": "SKU no encontrado en el catalogo"}


def build_tools(session_id: str) -> List[BaseTool]:
    """Arma las tools del agente para una sesion puntual. derivar_veterinario cierra
    sobre session_id para que el LLM nunca pueda controlarlo (regla del blueprint: el
    session_id lo inyecta Python, no el LLM)."""

    @tool
    def derivar_veterinario(motivo: str) -> dict:
        """Deriva la conversacion a un veterinario. Usar SIEMPRE que el cliente mencione
        un sintoma o condicion medica, antes de recomendar cualquier producto."""
        resultado = _derivar_veterinario(motivo=motivo, session_id=session_id)
        return resultado.model_dump()

    return [buscar_alimentos, consultar_disponibilidad, calcular_racion, derivar_veterinario]


@tool("derivar_veterinario")
def derivar_veterinario_con_contexto(motivo: str, runtime: ToolRuntime[Contexto]) -> dict:
    """Deriva la conversacion a un veterinario. Usar SIEMPRE que el cliente mencione
    un sintoma o condicion medica, antes de recomendar cualquier producto."""
    # `runtime` no forma parte del schema que ve el LLM: el thread_id sale del contexto del
    # turno (Python), igual que en build_tools sale del closure.
    resultado = _derivar_veterinario(motivo=motivo, session_id=runtime.context.thread_id)
    return resultado.model_dump()


# Tools del agente compartido (`app/services/agente.py`): las mismas, con la sesion leida
# del contexto del turno en vez de un closure.
TOOLS_CON_CONTEXTO: List[BaseTool] = [
    buscar_alimentos,
    consultar_disponibilidad,
    calcular_racion,
    derivar_veterinario_con_contexto,
]
