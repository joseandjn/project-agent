import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.guardrails.pii import contiene_numero_de_tarjeta, redactar_pii

# Lista cerrada (docs/feedback_cliente.md). Solo `producto_no_adecuado` es una senal sobre el
# producto; el resto es sobre la respuesta o el presupuesto.
Motivo = Literal["producto_no_adecuado", "muy_caro", "no_entendi", "no_era_lo_que_buscaba", "otro"]


class FeedbackRequest(BaseModel):
    mensaje_id: uuid.UUID = Field(..., description="El `mensaje_id` que devolvio /chat")
    valor: Literal["positivo", "negativo"]
    motivo: Optional[Motivo] = Field(None, description="Opcional, solo con valor negativo")
    comentario: Optional[str] = Field(None, max_length=500, description="Texto libre opcional")

    @model_validator(mode="after")
    def _validar(self) -> "FeedbackRequest":
        if self.motivo and self.valor != "negativo":
            raise ValueError("motivo solo se acepta con valor 'negativo'")
        if self.comentario is not None:
            if contiene_numero_de_tarjeta(self.comentario):
                raise ValueError("el comentario no puede incluir datos de tarjeta")
            # Email y telefono se redactan: el comentario se guarda y va a Langfuse.
            self.comentario = redactar_pii(self.comentario.strip()) or None
        return self
