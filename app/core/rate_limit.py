"""Rate limits en Redis (docs/rate_limits.md).

Ventanas fijas: un contador por regla y ventana (`INCR` + `EXPIRE NX`, atomico en un
pipeline). Si alguna regla del request se pasa de su limite, responde 429 con `Retry-After`.

Las reglas van por **sesion, cliente y tienda** (salen del JWT), no por IP: todo el trafico de
una tienda llega desde su servidor (o desde el contenedor del chat), asi que muchos usuarios
comparten IP. La IP solo se usa para frenar intentos con API keys invalidas.

Si Redis falla, no se bloquea el request (fail-open) y se loguea: el limitador no puede ser
la causa de una caida.
"""

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

from fastapi import HTTPException, Request, status

from app.core.config import get_settings
from app.memory.long_term.consolidacion import get_redis

logger = logging.getLogger(__name__)

MINUTO = 60
DIA = 86400


@dataclass(frozen=True)
class Regla:
    nombre: str  # p. ej. "chat:sesion"
    sujeto: str  # id de la sesion, cliente, tienda o IP
    limite: int  # 0 => regla desactivada
    ventana_s: int


class LimiteExcedido(HTTPException):
    def __init__(self, retry_after: int, regla: str):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas solicitudes. Intenta de nuevo en unos segundos.",
            headers={"Retry-After": str(retry_after)},
        )
        self.regla = regla


def _clave(regla: Regla, ahora: float) -> str:
    return f"vethis:rl:{regla.nombre}:{regla.sujeto}:{int(ahora // regla.ventana_s)}"


async def consumir(reglas: List[Regla]) -> None:
    """Cuenta el request en cada regla activa; si alguna se pasa, levanta `LimiteExcedido`.
    Tambien cuenta los requests rechazados: quien insiste, sigue bloqueado."""
    if not get_settings().rate_limit_enabled:
        return
    activas = [r for r in reglas if r.limite > 0]
    if not activas:
        return
    ahora = time.time()
    try:
        pipe = get_redis().pipeline(transaction=True)
        for r in activas:
            clave = _clave(r, ahora)
            pipe.incr(clave)
            pipe.expire(clave, r.ventana_s, nx=True)
        resultados = await pipe.execute()
    except Exception:
        logger.exception("Rate limit no disponible (Redis); se deja pasar el request")
        return

    excedidas = [r for r, n in zip(activas, resultados[::2]) if n > r.limite]
    if excedidas:
        # Esperar a que se libere la ventana mas larga de las excedidas.
        retry_after = max(r.ventana_s - int(ahora % r.ventana_s) for r in excedidas)
        peor = max(excedidas, key=lambda r: r.ventana_s)
        logger.warning("Rate limit %s excedido para %s", peor.nombre, peor.sujeto)
        raise LimiteExcedido(retry_after, peor.nombre)


async def excedido(regla: Regla) -> Optional[int]:
    """Segundos hasta liberar si la regla ya esta por encima del limite (sin contar este
    request); None si no. Para bloquear antes de hacer trabajo (p. ej. API keys invalidas)."""
    if not get_settings().rate_limit_enabled or regla.limite <= 0:
        return None
    ahora = time.time()
    try:
        n = await get_redis().get(_clave(regla, ahora))
    except Exception:
        logger.exception("Rate limit no disponible (Redis); se deja pasar el request")
        return None
    if n is not None and int(n) >= regla.limite:
        return regla.ventana_s - int(ahora % regla.ventana_s)
    return None


def ip_cliente(request: Request) -> str:
    """IP del cliente. Detras de Caddy, uvicorn la toma de X-Forwarded-For solo si el proxy
    es de confianza (FORWARDED_ALLOW_IPS en docker-compose.prod.yml)."""
    return request.client.host if request.client else "desconocida"
