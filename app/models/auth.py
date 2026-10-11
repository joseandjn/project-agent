from typing import Optional

from pydantic import BaseModel, Field


class TokenRequest(BaseModel):
    external_user_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Id del usuario en el sistema de la tienda. Omitido o null => sesion anonima.",
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Segundos de validez del token")
    session_id: str
