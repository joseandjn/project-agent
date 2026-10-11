"""Emision y validacion del JWT propio + hash de API keys de tienda.

El backend de cada tienda pide un token con su API key (`POST /api/v1/auth/token`); el
navegador solo ve el JWT. `session_id` y `cliente_id` salen de este token, nunca del body
del chat (cierra ASI03/ASI06 de docs/vulnerabilidades.md).

HS256: solo nosotros firmamos y verificamos. Si algun tercero necesita verificar los
tokens, migrar a RS256 + JWKS. Diseño: docs/memoria_largo_plazo.md.
"""

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import jwt

from app.core.config import get_settings

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "vethis-agent"
JWT_AUDIENCE = "vethis-chat"
API_KEY_PREFIX = "vth_"


class TokenInvalido(Exception):
    """El token no se pudo validar (firma, expiracion, issuer/audience o claims)."""


@dataclass(frozen=True)
class AuthContext:
    """Identidad de un request de chat, siempre derivada del JWT."""

    tienda_id: uuid.UUID
    session_id: uuid.UUID
    cliente_id: Optional[uuid.UUID]  # None => sesion anonima (sin memoria de largo plazo)

    @property
    def anonimo(self) -> bool:
        return self.cliente_id is None

    @property
    def thread_id(self) -> str:
        """Clave del checkpoint en Redis: con namespace de tienda para aislar sesiones."""
        return f"{self.tienda_id}:{self.session_id}"


def generar_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _secret() -> str:
    secret = get_settings().jwt_secret
    if not secret:
        raise RuntimeError("JWT_SECRET no esta configurado")
    return secret


def emitir_token(ctx: AuthContext) -> str:
    ahora = int(time.time())
    claims = {
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": ahora,
        "exp": ahora + get_settings().jwt_ttl_seconds,
        "tid": str(ctx.tienda_id),
        "sid": str(ctx.session_id),
        "anon": ctx.anonimo,
    }
    if ctx.cliente_id is not None:
        claims["sub"] = str(ctx.cliente_id)
    return jwt.encode(claims, _secret(), algorithm=JWT_ALGORITHM)


def validar_token(token: str) -> AuthContext:
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[JWT_ALGORITHM],  # lista fija: nunca aceptar el "alg" que trae el token
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "tid", "sid", "anon"]},
        )
        anonimo = claims["anon"]
        sub = claims.get("sub")
        # `anon` y `sub` tienen que ser coherentes: no se acepta un token ambiguo.
        if anonimo is not (sub is None):
            raise TokenInvalido("claims anon/sub inconsistentes")
        return AuthContext(
            tienda_id=uuid.UUID(claims["tid"]),
            session_id=uuid.UUID(claims["sid"]),
            cliente_id=uuid.UUID(sub) if sub is not None else None,
        )
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise TokenInvalido(str(exc)) from exc
