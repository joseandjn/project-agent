"""`POST /api/v1/feedback`: el cliente vota una respuesta del agente (docs/feedback_cliente.md).
Sirve para respuestas de /api/v1/chat y /api/v2/chat. La sesion sale del JWT."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies.auth import get_auth_context
from app.core.security import AuthContext
from app.db.session import get_db
from app.feedback.registro import guardar_feedback
from app.models.feedback import FeedbackRequest

router = APIRouter()


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def feedback(
    request: FeedbackRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Un voto por mensaje: si se vuelve a votar, reemplaza al anterior."""
    if not await guardar_feedback(db, ctx, request):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mensaje no encontrado para esta sesion, o ya no admite feedback",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
