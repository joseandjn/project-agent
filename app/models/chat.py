from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    mensaje: str = Field(..., min_length=1, description="Texto libre del cliente")
    session_id: str = Field(..., min_length=1, description="Identificador de sesion asignado por el sitio web")
    cliente_id: Optional[str] = Field(default=None, description="Identificador del cliente, si esta autenticado")


class ChatResponse(BaseModel):
    respuesta: str
    session_id: str
