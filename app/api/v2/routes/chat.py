"""`POST /api/v2/chat`: mismo contrato, autenticacion y memoria que `/api/v1/chat`, pero con
el **agente compartido** (app/services/agente.py), creado una vez al arrancar en lugar de en
cada request. `/api/v1/chat` no cambia."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies.auth import get_auth_context
from app.core.security import AuthContext
from app.db.session import get_db
from app.feedback.registro import contar_mensajes, registrar_mensaje
from app.memory.long_term.consolidacion import consolidar, debe_consolidar, registrar_turno
from app.memory.long_term.repo import leer_perfil
from app.models.chat import ChatRequest, ChatResponse
from app.observability.langfuse import trazar
from app.services.agente import generar_respuesta

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    perfil = None if ctx.anonimo else await leer_perfil(db, ctx.cliente_id)
    # Traza "chat_v2" para comparar en Langfuse contra "chat" (v1).
    # mensaje_id: id de esta respuesta para el feedback; tambien fija el id de la traza.
    mensaje_id = uuid.uuid4()
    antes = await contar_mensajes(ctx.thread_id)
    with trazar(
        "chat_v2", thread_id=ctx.thread_id, cliente_id=ctx.cliente_id, entrada=request.mensaje, mensaje_id=mensaje_id
    ) as traza:
        try:
            respuesta = await generar_respuesta(request.mensaje, ctx.thread_id, perfil)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if traza is not None:
            traza.update(output=respuesta)

    # Registra la respuesta (sesion + SKUs del turno) para que se pueda votar.
    await registrar_mensaje(ctx, mensaje_id, desde=antes)

    # Cada N turnos se consolida la memoria en segundo plano (despues de responder).
    if not ctx.anonimo and debe_consolidar(await registrar_turno(ctx)):
        background_tasks.add_task(consolidar, ctx.thread_id)

    return ChatResponse(respuesta=respuesta, session_id=str(ctx.session_id), mensaje_id=str(mensaje_id))
