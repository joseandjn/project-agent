"""Flujo de autenticacion contra Postgres real: API key de tienda -> JWT -> refresh.
Requiere Postgres en POSTGRES_DSN con `alembic upgrade head` aplicado; si no, se saltea."""

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import delete, inspect, update

from app.core.config import get_settings
from app.core.security import validar_token
from app.db.models import Tienda
from app.db.session import close_engine, get_sessionmaker
from app.main import app
from scripts.crear_tienda import crear_tienda


async def _esquema_aplicado() -> bool:
    try:
        async with get_sessionmaker()() as db:
            conn = await db.connection()
            return await conn.run_sync(lambda c: inspect(c).has_table("clientes"))
    except Exception:
        return False
    finally:
        await close_engine()


pytestmark = pytest.mark.skipif(
    not asyncio.run(_esquema_aplicado()),
    reason="Postgres no disponible en POSTGRES_DSN o falta `alembic upgrade head`",
)


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "jwt_secret", "secreto-de-test-de-al-menos-32-bytes!!")


@pytest.fixture
async def tienda():
    """Tienda de prueba; al borrarla, el CASCADE se lleva sus clientes."""
    tienda, api_key = await crear_tienda(f"test-{uuid.uuid4().hex[:8]}")
    yield tienda, api_key
    async with get_sessionmaker()() as db:
        await db.execute(delete(Tienda).where(Tienda.id == tienda.id))
        await db.commit()
    # El engine queda atado al event loop del test: se cierra para no reusarlo en otro loop.
    await close_engine()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_api_key_invalida_responde_401(client, tienda):
    r = await client.post("/api/v1/auth/token", json={}, headers={"X-API-Key": "vth_inventada"})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/token", json={})
    assert r.status_code == 401


async def test_token_anonimo(client, tienda):
    t, api_key = tienda
    r = await client.post("/api/v1/auth/token", json={}, headers={"X-API-Key": api_key})
    assert r.status_code == 200
    body = r.json()
    ctx = validar_token(body["access_token"])
    assert ctx.tienda_id == t.id
    assert ctx.anonimo
    assert str(ctx.session_id) == body["session_id"]
    assert body["expires_in"] == get_settings().jwt_ttl_seconds


async def test_mismo_usuario_mismo_cliente_y_sesion_nueva(client, tienda):
    _, api_key = tienda
    headers = {"X-API-Key": api_key}
    a = validar_token((await client.post("/api/v1/auth/token", json={"external_user_id": "u-1"}, headers=headers)).json()["access_token"])
    b = validar_token((await client.post("/api/v1/auth/token", json={"external_user_id": "u-1"}, headers=headers)).json()["access_token"])
    c = validar_token((await client.post("/api/v1/auth/token", json={"external_user_id": "u-2"}, headers=headers)).json()["access_token"])
    assert a.cliente_id is not None
    assert a.cliente_id == b.cliente_id != c.cliente_id
    assert a.session_id != b.session_id


async def test_mismo_external_id_en_otra_tienda_es_otro_cliente(client, tienda):
    _, api_key = tienda
    otra, otra_key = await crear_tienda(f"test-{uuid.uuid4().hex[:8]}")
    try:
        body = {"external_user_id": "u-1"}
        a = validar_token((await client.post("/api/v1/auth/token", json=body, headers={"X-API-Key": api_key})).json()["access_token"])
        b = validar_token((await client.post("/api/v1/auth/token", json=body, headers={"X-API-Key": otra_key})).json()["access_token"])
        assert a.cliente_id != b.cliente_id
    finally:
        async with get_sessionmaker()() as db:
            await db.execute(delete(Tienda).where(Tienda.id == otra.id))
            await db.commit()


async def test_refresh_mantiene_sesion_y_tienda_inactiva_no_renueva(client, tienda):
    t, api_key = tienda
    token = (await client.post("/api/v1/auth/token", json={"external_user_id": "u-1"}, headers={"X-API-Key": api_key})).json()["access_token"]
    original = validar_token(token)

    r = await client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert validar_token(r.json()["access_token"]) == original

    async with get_sessionmaker()() as db:
        await db.execute(update(Tienda).where(Tienda.id == t.id).values(activa=False))
        await db.commit()

    r = await client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/token", json={}, headers={"X-API-Key": api_key})
    assert r.status_code == 401
