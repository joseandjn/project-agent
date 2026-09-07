from fastapi import APIRouter, HTTPException

from app.memory.short_term.session_memory import append_exchange, get_history
from app.models.chat import ChatRequest, ChatResponse
from app.services.llm_client import generate_reply

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    history = await get_history(request.session_id)
    messages = [*history, {"role": "user", "content": request.mensaje}]

    try:
        respuesta = await generate_reply(messages, request.session_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    await append_exchange(request.session_id, request.mensaje, respuesta)
    return ChatResponse(respuesta=respuesta, session_id=request.session_id)
