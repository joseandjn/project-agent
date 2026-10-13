"""Guia nutricional de una tienda: formato canonico (docs/guia_nutricional_neo4j.md).

Se escribe en YAML (data/guias/*.yaml), se valida con estos modelos y se carga a Neo4j
(scripts/cargar_guia.py). Cada regla cita una fuente definida en `fuentes`.
"""

from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

Especie = Literal["Perro", "Gato"]
Etapa = Literal["Cachorro", "Adulto", "Senior", "Todas las edades"]


def _lista(v):
    """`fuente`/`especie` pueden venir como valor suelto o lista: siempre lista."""
    return v if isinstance(v, list) else [v]


class Fuente(BaseModel):
    titulo: str
    url: Optional[str] = None


class Potencia(BaseModel):
    """factor x peso_kg ^ exponente"""

    factor: float
    exponente: float

    def evaluar(self, peso_kg: float) -> float:
        return self.factor * peso_kg**self.exponente


class ReglaEnergia(BaseModel):
    especie: List[Especie]
    etapas: List[Etapa]
    metodo: Literal["kcal", "porcentaje_peso"]
    formula: Optional[str] = None
    kcal_min: Optional[Potencia] = None
    kcal_max: Optional[Potencia] = None
    # "menor_y_mayor": las dos formulas se cruzan (gato < ~2,6 kg): el rango va del menor al mayor.
    rango: Literal["min_max", "menor_y_mayor"] = "min_max"
    pct_peso: Optional[float] = Field(None, gt=0, lt=100)
    nota: str = ""
    verificacion: Optional[str] = None
    fuente: List[str]

    _listas = field_validator("especie", "fuente", mode="before")(_lista)

    @model_validator(mode="after")
    def _segun_metodo(self) -> "ReglaEnergia":
        if self.metodo == "kcal" and not (self.kcal_min and self.kcal_max):
            raise ValueError("metodo 'kcal' requiere kcal_min y kcal_max")
        if self.metodo == "porcentaje_peso" and self.pct_peso is None:
            raise ValueError("metodo 'porcentaje_peso' requiere pct_peso")
        return self

    def kcal_diarias(self, peso_kg: float) -> Tuple[float, float]:
        a, b = self.kcal_min.evaluar(peso_kg), self.kcal_max.evaluar(peso_kg)
        return (min(a, b), max(a, b)) if self.rango == "menor_y_mayor" else (a, b)


class ReglaPremio(BaseModel):
    especie: List[Especie]
    regla: str
    max_porcentaje_kcal: Optional[float] = None
    deriva_veterinario: bool = False
    fuente: List[str]

    _listas = field_validator("especie", "fuente", mode="before")(_lista)


class RiesgoPremio(BaseModel):
    especie: List[Especie]
    riesgo: str
    fuente: List[str]

    _listas = field_validator("especie", "fuente", mode="before")(_lista)


class Toxicos(BaseModel):
    especie: List[Especie]
    ingredientes: List[str] = Field(..., min_length=1)
    nota: Optional[str] = None
    fuente: List[str]

    _listas = field_validator("especie", "fuente", mode="before")(_lista)


class CondicionCorporalEspecie(BaseModel):
    especie: List[Especie]
    ideal: Tuple[int, int]
    nota: Optional[str] = None
    senales_ideal: str
    fuente: List[str]

    _listas = field_validator("especie", "fuente", mode="before")(_lista)


class CondicionCorporal(BaseModel):
    escala: str
    por_especie: List[CondicionCorporalEspecie]
    regla_asesor: str
    deriva_veterinario: bool = True
    fuente_regla: List[str]

    _listas = field_validator("fuente_regla", mode="before")(_lista)


class ReglaSeleccion(BaseModel):
    regla: str
    fuente: List[str]

    _listas = field_validator("fuente", mode="before")(_lista)


class Transicion(BaseModel):
    dias: int = Field(..., gt=0)
    pasos: List[str]
    nota: Optional[str] = None
    fuente: List[str]

    _listas = field_validator("fuente", mode="before")(_lista)


class Meta(BaseModel):
    tienda: str
    version: int = Field(..., ge=1)
    estado: Literal["borrador", "aprobada"]
    aprobada_por: Optional[str] = None
    idioma: str = "es"
    aviso: str


class Guia(BaseModel):
    meta: Meta
    fuentes: Dict[str, Fuente]
    energia: List[ReglaEnergia]
    premios: List[ReglaPremio]
    riesgos_premios: List[RiesgoPremio]
    toxicos: List[Toxicos]
    condicion_corporal: CondicionCorporal
    seleccion_alimento: List[ReglaSeleccion]
    transicion: Transicion
    condiciones_derivar: List[str]
    fuente_condiciones_derivar: List[str]

    _listas = field_validator("fuente_condiciones_derivar", mode="before")(_lista)

    @model_validator(mode="after")
    def _fuentes_definidas(self) -> "Guia":
        citadas = set(self.fuente_condiciones_derivar) | set(self.condicion_corporal.fuente_regla)
        for grupo in (self.energia, self.premios, self.riesgos_premios, self.toxicos,
                      self.condicion_corporal.por_especie, self.seleccion_alimento, [self.transicion]):
            for regla in grupo:
                citadas |= set(regla.fuente)
        faltan = citadas - set(self.fuentes)
        if faltan:
            raise ValueError(f"fuentes citadas sin definir en `fuentes`: {sorted(faltan)}")
        return self

    # --- Consultas ---------------------------------------------------------------------

    def regla_energia(self, especie: str, etapa: str) -> Optional[ReglaEnergia]:
        return next((r for r in self.energia if especie in r.especie and etapa in r.etapas), None)

    def max_pct_premios(self, especie: str) -> Optional[float]:
        return next(
            (r.max_porcentaje_kcal for r in self.premios if especie in r.especie and r.max_porcentaje_kcal),
            None,
        )

    def citas(self, ids: List[str]) -> List[str]:
        return [self.fuentes[i].titulo for i in ids if i in self.fuentes]


def cargar_yaml(ruta: Path) -> Guia:
    with open(ruta, encoding="utf-8") as f:
        return Guia.model_validate(yaml.safe_load(f))
