from fastapi import APIRouter, HTTPException

from app.models.chat import ChatRequest, ChatResponse
from app.services.llm_client import generate_reply

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    # El historial de la sesion lo maneja el checkpointer de Redis (thread_id == session_id):
    # aca solo se pasa el turno nuevo del cliente.
    try:
        respuesta = await generate_reply(request.mensaje, request.session_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ChatResponse(respuesta=respuesta, session_id=request.session_id)
