"""Cuando se consolida la memoria de largo plazo (docs/memoria_largo_plazo.md, D3).

Dos disparadores, solo para sesiones con cliente autenticado:
1. **Cada N turnos** (`MEMORIA_CONSOLIDAR_CADA_N_TURNOS`): `/chat` lanza `consolidar` en
   segundo plano cuando la sesion acumula N turnos sin consolidar.
2. **Inactividad** (`MEMORIA_INACTIVIDAD_SEGUNDOS`): el *sweeper* consolida las sesiones
   que llevan ese tiempo sin mensajes, antes de que Redis borre su checkpoint (TTL).

Estado en Redis:
- `vethis:mem:actividad`: sorted set `thread_id -> timestamp del ultimo turno`.
- `vethis:mem:sesion:{thread_id}`: hash `{cliente_id, pendientes, consolidados}`, donde
  `consolidados` es cuantos mensajes del checkpoint ya pasaron por el extractor.
- `vethis:mem:lock:{thread_id}`: lock (`SET NX EX`) para que la misma sesion no se
  consolide dos veces a la vez, aunque haya varias replicas de `api`.
"""

import asyncio
import logging
import time
import uuid
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.security import AuthContext
from app.db.session import get_sessionmaker
from app.memory.long_term.extractor import extraer_perfil
from app.memory.long_term.repo import guardar_perfil, leer_perfil
from app.memory.short_term.session_memory import get_checkpointer, session_config

logger = logging.getLogger(__name__)

ACTIVIDAD_KEY = "vethis:mem:actividad"
_LOCK_TTL_SEGUNDOS = 120

# Borra el lock solo si sigue siendo nuestro (no el de otra replica que lo tomo al vencer).
_LIBERAR_LOCK = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""
# Saca la sesion del sorted set solo si no hubo actividad nueva mientras se consolidaba.
_ZREM_SI_SIN_CAMBIOS = """
if tonumber(redis.call('ZSCORE', KEYS[1], ARGV[1])) == tonumber(ARGV[2]) then
  return redis.call('ZREM', KEYS[1], ARGV[1])
end
return 0
"""

_redis: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        finally:
            _redis = None


def _sesion_key(thread_id: str) -> str:
    return f"vethis:mem:sesion:{thread_id}"


async def registrar_turno(ctx: AuthContext) -> int:
    """Anota un turno de una sesion autenticada. Devuelve cuantos turnos van sin consolidar."""
    settings = get_settings()
    key = _sesion_key(ctx.thread_id)
    pipe = get_redis().pipeline(transaction=True)
    pipe.zadd(ACTIVIDAD_KEY, {ctx.thread_id: time.time()})
    pipe.hset(key, "cliente_id", str(ctx.cliente_id))
    pipe.hincrby(key, "pendientes", 1)
    # Un poco mas que el checkpoint: sin checkpoint ya no hay nada que consolidar.
    pipe.expire(key, settings.session_ttl_seconds + 600)
    resultados = await pipe.execute()
    return int(resultados[2])


def debe_consolidar(pendientes: int) -> bool:
    return pendientes >= get_settings().memoria_consolidar_cada_n_turnos


async def consolidar(thread_id: str) -> bool:
    """Pasa los mensajes nuevos de la sesion por el extractor y guarda el perfil.
    True si guardo una version nueva. Nunca levanta: se corre en segundo plano."""
    r = get_redis()
    lock_key, token = f"vethis:mem:lock:{thread_id}", uuid.uuid4().hex
    if not await r.set(lock_key, token, nx=True, ex=_LOCK_TTL_SEGUNDOS):
        return False
    try:
        estado = await r.hgetall(_sesion_key(thread_id))
        if not estado.get("cliente_id"):
            return False
        cliente_id = uuid.UUID(estado["cliente_id"])

        checkpoint = await (await get_checkpointer()).aget_tuple(session_config(thread_id))
        mensajes = checkpoint.checkpoint["channel_values"].get("messages", []) if checkpoint else []
        nuevos = mensajes[int(estado.get("consolidados", 0)) :]
        if not nuevos:
            await r.hset(_sesion_key(thread_id), "pendientes", 0)
            return False

        async with get_sessionmaker()() as db:
            perfil = await extraer_perfil(await leer_perfil(db, cliente_id), nuevos)
            if perfil is None:
                # No se avanza `consolidados`: el proximo disparador reintenta con estos mensajes.
                return False
            await guardar_perfil(db, cliente_id, perfil, thread_id)

        await r.hset(_sesion_key(thread_id), mapping={"consolidados": len(mensajes), "pendientes": 0})
        return True
    except Exception:
        logger.exception("Fallo la consolidacion de memoria de %s", thread_id)
        return False
    finally:
        await r.eval(_LIBERAR_LOCK, 1, lock_key, token)


async def consolidar_inactivas() -> int:
    """Una pasada del sweeper: consolida las sesiones inactivas y las saca del sorted set.
    Devuelve cuantas proceso."""
    r = get_redis()
    corte = time.time() - get_settings().memoria_inactividad_segundos
    inactivas = await r.zrangebyscore(ACTIVIDAD_KEY, "-inf", corte, withscores=True)
    for thread_id, score in inactivas:
        await consolidar(thread_id)
        # Un solo intento por inactividad: si fallo, no se reintenta cada minuto hasta el TTL.
        await r.eval(_ZREM_SI_SIN_CAMBIOS, 1, ACTIVIDAD_KEY, thread_id, repr(score))
    return len(inactivas)


async def sweeper() -> None:
    """Tarea de fondo que arranca el lifespan de main.py."""
    intervalo = get_settings().memoria_sweep_intervalo_segundos
    while True:
        try:
            await consolidar_inactivas()
        except Exception:
            logger.exception("Fallo una pasada del sweeper de memoria")
        await asyncio.sleep(intervalo)
