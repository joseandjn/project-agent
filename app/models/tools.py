from typing import List, Optional

from pydantic import BaseModel


class ScoreDesglose(BaseModel):
    afinidad_semantica: float
    confianza_feedback: float
    ajuste_presupuesto: float
    total: float


class AlimentoResumen(BaseModel):
    sku: str
    nombre: str
    presentacion: str
    especie: str
    etapa: List[str]
    proteina_principal: str
    score: ScoreDesglose


class Disponibilidad(BaseModel):
    sku: str
    precio_regular: float
    precio_por_kg: float
    disponible: bool
    stock: int
    url_producto: str


class RacionCalculada(BaseModel):
    sku: str
    racion_diaria_g: float
    duracion_dias: Optional[int]
    costo_mensual: float


class DerivacionVeterinario(BaseModel):
    id: str
    session_id: str
    motivo: str
    fecha: str
