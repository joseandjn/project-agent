from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies.auth import get_auth_context
from app.core.security import AuthContext
from app.db.session import get_db
from app.memory.long_term.consolidacion import consolidar, debe_consolidar, registrar_turno
from app.memory.long_term.repo import leer_perfil
from app.models.chat import ChatRequest, ChatResponse
from app.observability.langfuse import trazar
from app.services.llm_client import generate_reply

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    # El historial de la sesion lo maneja el checkpointer de Redis (thread_id con namespace de
    # tienda, sacado del JWT): aca solo se pasa el turno nuevo del cliente. Si el cliente esta
    # autenticado, su perfil (memoria de largo plazo) se agrega al system prompt.
    perfil = None if ctx.anonimo else await leer_perfil(db, ctx.cliente_id)
    # Una traza de Langfuse por turno (no-op si esta deshabilitado); el texto se enmascara.
    with trazar("chat", thread_id=ctx.thread_id, cliente_id=ctx.cliente_id, entrada=request.mensaje) as traza:
        try:
            respuesta = await generate_reply(request.mensaje, ctx.thread_id, perfil)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if traza is not None:
            traza.update(output=respuesta)

    # Cada N turnos se consolida la memoria en segundo plano (despues de responder).
    if not ctx.anonimo and debe_consolidar(await registrar_turno(ctx)):
        background_tasks.add_task(consolidar, ctx.thread_id)

    return ChatResponse(respuesta=respuesta, session_id=str(ctx.session_id))
