from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    # La identidad (tienda, sesion, cliente) sale del JWT del header Authorization, nunca del
    # body: ver app/api/v1/dependencies/auth.py y docs/memoria_largo_plazo.md.
    mensaje: str = Field(..., min_length=1, description="Texto libre del cliente")


class ChatResponse(BaseModel):
    respuesta: str
    session_id: str
    mensaje_id: str = Field(..., description="Id de esta respuesta, para votarla en POST /api/v1/feedback")
