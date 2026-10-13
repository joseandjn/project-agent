"""Rate limits (app/core/rate_limit.py) contra Redis y Postgres reales, con limites chicos.
El agente es un fake. Requiere Redis y Postgres con `alembic upgrade head`; si no, se saltea."""

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import delete, inspect

from app.core.config import get_settings
from app.db.models import Tienda
from app.db.session import close_engine, get_sessionmaker
from app.main import app
from app.memory.long_term.consolidacion import close_redis, get_redis
from app.memory.short_term.session_memory import close_checkpointer
from scripts.crear_tienda import crear_tienda


async def _servicios_listos() -> bool:
    try:
        await get_redis().ping()
        async with get_sessionmaker()() as db:
            conn = await db.connection()
            return await conn.run_sync(lambda c: inspect(c).has_table("tiendas"))
    except Exception:
        return False
    finally:
        await close_redis()
        await close_engine()


pytestmark = pytest.mark.skipif(
    not asyncio.run(_servicios_listos()),
    reason="Redis o Postgres no disponibles, o falta `alembic upgrade head`",
)

LIMITES_ALTOS = {
    "rl_chat_sesion_por_minuto": 100,
    "rl_chat_cliente_por_minuto": 100,
    "rl_chat_tienda_por_minuto": 100,
    "rl_chat_tienda_por_dia": 1000,
    "rl_token_tienda_por_minuto": 100,
    "rl_api_key_invalida_ip_por_minuto": 100,
}


@pytest.fixture
async def entorno(monkeypatch):
    """Tienda real, rate limits prendidos (altos por defecto; cada test baja el que prueba) y
    el agente reemplazado por un fake. Limpia la tienda y sus contadores."""
    s = get_settings()
    monkeypatch.setattr(s, "jwt_secret", "secreto-de-test-de-al-menos-32-bytes!!")
    monkeypatch.setattr(s, "rate_limit_enabled", True)
    for k, v in LIMITES_ALTOS.items():
        monkeypatch.setattr(s, k, v)

    async def _fake_reply(mensaje, thread_id, perfil=None):
        return "ok"

    monkeypatch.setattr("app.api.v1.routes.chat.generate_reply", _fake_reply)
    tienda, api_key = await crear_tienda(f"test-rl-{uuid.uuid4().hex[:8]}")
    marcas = {str(tienda.id)}  # todo contador que contenga esto se borra al final

    def cliente_http(ip="10.9.0.1"):
        marcas.add(ip)
        transport = httpx.ASGITransport(app=app, client=(ip, 1234))
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    async def token(c, external_user_id=None):
        body = {"external_user_id": external_user_id} if external_user_id else {}
        r = await c.post("/api/v1/auth/token", json=body, headers={"X-API-Key": api_key})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    yield {"api_key": api_key, "cliente_http": cliente_http, "token": token, "marcas": marcas}

    r = get_redis()
    async for clave in r.scan_iter(match="vethis:rl:*"):
        if any(m in clave for m in marcas):
            await r.delete(clave)
    async with get_sessionmaker()() as db:
        await db.execute(delete(Tienda).where(Tienda.id == tienda.id))
        await db.commit()
    await close_redis()
    await close_checkpointer()
    await close_engine()


async def _chat(c, headers):
    return await c.post("/api/v1/chat", json={"mensaje": "hola"}, headers=headers)


async def test_chat_por_sesion(entorno, monkeypatch):
    monkeypatch.setattr(get_settings(), "rl_chat_sesion_por_minuto", 3)
    async with entorno["cliente_http"]() as c:
        sesion = await entorno["token"](c)
        codigos = [(await _chat(c, sesion)).status_code for _ in range(4)]
        assert codigos == [200, 200, 200, 429]
        r = await _chat(c, sesion)
        assert r.status_code == 429
        assert 0 < int(r.headers["Retry-After"]) <= 60
        # Otra sesion de la misma tienda no esta afectada.
        assert (await _chat(c, await entorno["token"](c))).status_code == 200


async def test_chat_por_tienda(entorno, monkeypatch):
    monkeypatch.setattr(get_settings(), "rl_chat_tienda_por_minuto", 4)
    async with entorno["cliente_http"]() as c:
        sesiones = [await entorno["token"](c) for _ in range(3)]
        codigos = [(await _chat(c, sesiones[i % 3])).status_code for i in range(5)]
        assert codigos == [200, 200, 200, 200, 429]


async def test_chat_por_cliente_suma_todas_sus_sesiones(entorno, monkeypatch):
    monkeypatch.setattr(get_settings(), "rl_chat_cliente_por_minuto", 2)
    externo = f"u-rl-{uuid.uuid4().hex[:6]}"
    async with entorno["cliente_http"]() as c:
        a, b = await entorno["token"](c, externo), await entorno["token"](c, externo)
        assert [(await _chat(c, s)).status_code for s in (a, b, a)] == [200, 200, 429]
        # Una sesion anonima de la misma tienda sigue pudiendo.
        assert (await _chat(c, await entorno["token"](c))).status_code == 200
    from app.core.security import validar_token

    entorno["marcas"].add(str(validar_token(a["Authorization"].split()[1]).cliente_id))


async def test_api_key_invalida_bloquea_la_ip(entorno, monkeypatch):
    monkeypatch.setattr(get_settings(), "rl_api_key_invalida_ip_por_minuto", 3)
    async with entorno["cliente_http"]("10.9.0.66") as atacante, entorno["cliente_http"]("10.9.0.77") as otra:
        mala = {"X-API-Key": "vth_inventada"}
        codigos = [(await atacante.post("/api/v1/auth/token", json={}, headers=mala)).status_code for _ in range(4)]
        assert codigos == [401, 401, 401, 429]
        # Bloqueada la IP, ni una key valida pasa (no se pueden seguir probando keys).
        r = await atacante.post("/api/v1/auth/token", json={}, headers={"X-API-Key": entorno["api_key"]})
        assert r.status_code == 429
        # Otra IP con la key valida no se ve afectada.
        r = await otra.post("/api/v1/auth/token", json={}, headers={"X-API-Key": entorno["api_key"]})
        assert r.status_code == 200


async def test_sesiones_nuevas_por_tienda(entorno, monkeypatch):
    monkeypatch.setattr(get_settings(), "rl_token_tienda_por_minuto", 2)
    async with entorno["cliente_http"]() as c:
        await entorno["token"](c)
        await entorno["token"](c)
        r = await c.post("/api/v1/auth/token", json={}, headers={"X-API-Key": entorno["api_key"]})
        assert r.status_code == 429


async def test_sin_token_no_consume_cupo(entorno, monkeypatch):
    monkeypatch.setattr(get_settings(), "rl_chat_tienda_por_minuto", 1)
    async with entorno["cliente_http"]() as c:
        for _ in range(3):
            assert (await c.post("/api/v1/chat", json={"mensaje": "hola"})).status_code == 401
        assert (await _chat(c, await entorno["token"](c))).status_code == 200


async def test_si_redis_falla_deja_pasar(entorno, monkeypatch):
    monkeypatch.setattr(get_settings(), "rl_chat_sesion_por_minuto", 1)
    async with entorno["cliente_http"]() as c:
        sesion = await entorno["token"](c)

        class _RedisCaido:
            def pipeline(self, **kwargs):
                raise ConnectionError("redis caido")

        monkeypatch.setattr("app.core.rate_limit.get_redis", lambda: _RedisCaido())
        assert [(await _chat(c, sesion)).status_code for _ in range(3)] == [200, 200, 200]
