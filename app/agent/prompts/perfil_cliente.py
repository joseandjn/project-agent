"""Bloque del perfil del cliente (memoria de largo plazo) que se agrega al system prompt."""

from typing import List

from app.memory.long_term.models import Mascota, PerfilCliente


def _limpio(texto: str) -> str:
    # Sin "<" ni ">": un valor guardado no puede cerrar el bloque ni abrir otra etiqueta.
    return texto.replace("<", "").replace(">", "").strip()


def _mascota(m: Mascota) -> str:
    partes = [m.especie]
    if m.etapa:
        partes.append(m.etapa.lower())
    if m.peso_kg:
        partes.append(f"~{m.peso_kg:g} kg")
    if m.tamano_raza:
        partes.append(f"raza {m.tamano_raza.lower()}")
    linea = f"- Mascota: {_limpio(m.nombre)} ({', '.join(partes)})" if m.nombre else f"- Mascota: {', '.join(partes)}"
    if m.condiciones:
        linea += f". Condiciones: {', '.join(_limpio(c) for c in m.condiciones)}"
    if m.proteinas_a_evitar:
        linea += f". Evitar: {', '.join(_limpio(p) for p in m.proteinas_a_evitar)}"
    if m.alimento_actual:
        linea += f". Come actualmente: {_limpio(m.alimento_actual)}"
    return linea + "."


def render_bloque_perfil(perfil: PerfilCliente) -> str:
    lineas: List[str] = [_mascota(m) for m in perfil.mascotas]
    if perfil.presupuesto:
        lineas.append(f"- Presupuesto: {_limpio(perfil.presupuesto)}.")
    if perfil.preferencias:
        lineas.append(f"- Preferencias: {', '.join(_limpio(p) for p in perfil.preferencias)}.")
    if perfil.skus_recomendados:
        lineas.append(f"- Productos que ya consulto: {', '.join(perfil.skus_recomendados)}.")
    if perfil.derivado_a_veterinario:
        lineas.append("- En una conversacion anterior se lo derivo al veterinario.")
    if perfil.resumen:
        lineas.append(f"- Resumen: {_limpio(perfil.resumen)}")
    if not lineas:
        return ""
    return (
        "\n<perfil_cliente>\n"
        "(datos guardados de conversaciones anteriores; pueden estar desactualizados)\n"
        + "\n".join(lineas)
        + "\n</perfil_cliente>\n"
    )
