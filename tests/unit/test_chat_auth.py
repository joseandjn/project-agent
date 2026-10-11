"""`POST /api/v1/chat` exige JWT y saca la sesion del token, no del body. El agente se
reemplaza por un fake: no necesita LLM, Redis ni Postgres (no corre el lifespan)."""

import uuid

import httpx
import pytest

from app.core.config import get_settings
from app.core.security import AuthContext, emitir_token
from app.main import app


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "jwt_secret", "secreto-de-test-de-al-menos-32-bytes!!")


@pytest.fixture
def llamadas(monkeypatch):
    registro = []

    async def _fake_generate_reply(mensaje, thread_id):
        registro.append((mensaje, thread_id))
        return "respuesta fake"

    monkeypatch.setattr("app.api.v1.routes.chat.generate_reply", _fake_generate_reply)
    return registro


async def _post(json, headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v1/chat", json=json, headers=headers or {})


async def test_sin_token_responde_401(llamadas):
    r = await _post({"mensaje": "hola"})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert llamadas == []


async def test_token_invalido_responde_401(llamadas):
    r = await _post({"mensaje": "hola"}, {"Authorization": "Bearer no-es-un-jwt"})
    assert r.status_code == 401
    assert llamadas == []


async def test_la_sesion_sale_del_token_y_no_del_body(llamadas):
    ctx = AuthContext(tienda_id=uuid.uuid4(), session_id=uuid.uuid4(), cliente_id=None)
    r = await _post(
        # session_id / cliente_id en el body se ignoran (ya no son parte del contrato).
        {"mensaje": "hola", "session_id": "sesion-de-otro", "cliente_id": "cliente-de-otro"},
        {"Authorization": f"Bearer {emitir_token(ctx)}"},
    )
    assert r.status_code == 200
    assert r.json() == {"respuesta": "respuesta fake", "session_id": str(ctx.session_id)}
    assert llamadas == [("hola", ctx.thread_id)]
