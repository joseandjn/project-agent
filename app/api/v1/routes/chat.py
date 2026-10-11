from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies.auth import get_auth_context
from app.core.security import AuthContext
from app.models.chat import ChatRequest, ChatResponse
from app.services.llm_client import generate_reply

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, ctx: AuthContext = Depends(get_auth_context)) -> ChatResponse:
    # El historial de la sesion lo maneja el checkpointer de Redis (thread_id con namespace de
    # tienda, sacado del JWT): aca solo se pasa el turno nuevo del cliente.
    try:
        respuesta = await generate_reply(request.mensaje, ctx.thread_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ChatResponse(respuesta=respuesta, session_id=str(ctx.session_id))
