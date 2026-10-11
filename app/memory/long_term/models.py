"""Perfil de cliente que se guarda como memoria de largo plazo (JSONB en `perfiles_cliente`).

Se separa en dos modelos:
- `PerfilExtraido`: lo que el LLM extractor puede escribir (hechos que dijo el cliente).
- `PerfilCliente`: lo anterior + campos **deterministas** que llena el backend a partir de
  las tool calls de la conversacion; el LLM nunca los ve como salida, asi no puede
  inventar un SKU ni una derivacion.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Mascota(BaseModel):
    nombre: Optional[str] = Field(None, max_length=40)
    especie: Literal["Perro", "Gato"]
    etapa: Optional[Literal["Cachorro", "Adulto", "Senior"]] = None
    peso_kg: Optional[float] = Field(None, gt=0, lt=120)
    tamano_raza: Optional[Literal["Pequeña", "Mediana", "Grande"]] = None
    condiciones: List[str] = Field(
        default_factory=list, max_length=10, description="Condiciones de salud tal como las dijo el cliente"
    )
    proteinas_a_evitar: List[str] = Field(
        default_factory=list,
        max_length=10,
        description='Proteinas que la mascota no debe comer: alergias, intolerancias o pedidos del cliente (ej. "pollo")',
    )
    alimento_actual: Optional[str] = Field(None, max_length=80)


class PerfilExtraido(BaseModel):
    mascotas: List[Mascota] = Field(default_factory=list, max_length=10)
    presupuesto: Optional[str] = Field(None, max_length=60, description='Ej. "hasta S/ 150 al mes"')
    preferencias: List[str] = Field(
        default_factory=list, max_length=10, description='Ej. "prefiere alimento humedo"'
    )
    resumen: str = Field("", max_length=500, description="Resumen breve de lo conversado")


class PerfilCliente(PerfilExtraido):
    # Deterministas: los llena el backend desde las tool calls (ver extractor.py).
    skus_recomendados: List[str] = Field(default_factory=list)
    derivado_a_veterinario: bool = False
