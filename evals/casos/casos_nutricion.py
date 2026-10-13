"""Casos de la guia nutricional contra el agente real: que tool debe usar y que dato de la
guia tiene que aparecer en la respuesta (aserciones duras, sin juez LLM). Los dos primeros
salen de la prueba con amigos de la demo (2026-10-12)."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class CasoNutricion:
    id: str
    mensajes: List[str]  # el ultimo es el que se evalua
    tools: List[List[str]]  # cada grupo: alguna de esas tools se llamo en el ultimo turno
    contiene: List[List[str]] = field(default_factory=list)  # cada grupo: alguna de las variantes


CASOS_NUTRICION: List[CasoNutricion] = [
    CasoNutricion(
        "info-nutricional",
        ["Tengo dos perros adultos de raza grande, recomiendame un alimento sin limite de presupuesto",
         "Pero no me estas dando la informacion nutricional de cada uno"],
        [["ver_ficha_producto"]],
        [["proteína", "proteina"], ["kcal"]],
    ),
    CasoNutricion("leche-gato", ["¿Mi gato puede tomar leche?"], [["consultar_guia"]], [["lactosa", "lácteos", "lacteos"]]),
    CasoNutricion("uvas-perro", ["¿Le puedo dar uvas a mi perro?"], [["consultar_guia"]], [["tóxic", "toxic", "nunca"]]),
    CasoNutricion(
        "racion-adulto",
        ["Mi perro adulto pesa 30 kg, ¿cuánto le doy al día del Vethis Adulto Raza Grande Pollo?"],
        [["calcular_racion"]],
        [["290"], ["365"]],
    ),
    CasoNutricion(
        "snacks",
        ["¿Cuántos gramos del Vethis Snack Perro Pollo le puedo dar al día a mi perra adulta de 20 kg?"],
        [["calcular_racion"]],
        [["25"]],
    ),
    CasoNutricion("peso-ideal", ["¿Cómo sé si mi perro está en su peso ideal?"], [["consultar_guia"]], [["costillas"]]),
    CasoNutricion(
        "cambio-alimento",
        ["Quiero cambiarle el alimento a mi gato, ¿cómo lo hago?"],
        [["consultar_guia"]],
        [["7 días", "7 dias", "siete", "semana", "día 7", "dia 7"]],
    ),
    CasoNutricion(
        "dieta-veterinaria",
        ["Mi veterinario le dio a mi gato el Vethis Medicado Urinario Gato, pesa 4 kg, ¿cuánto le doy?"],
        [["calcular_racion", "derivar_veterinario"]],
        [["veterinari"]],
    ),
]
