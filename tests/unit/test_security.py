"""JWT propio: emision/validacion y rechazo de tokens manipulados. Sin Postgres ni Redis."""

import time
import uuid

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    JWT_AUDIENCE,
    JWT_ISSUER,
    AuthContext,
    TokenInvalido,
    emitir_token,
    generar_api_key,
    hash_api_key,
    validar_token,
)

SECRET = "secreto-de-test-de-al-menos-32-bytes!!"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "jwt_secret", SECRET)
    monkeypatch.setattr(get_settings(), "jwt_ttl_seconds", 3600)


def _ctx(cliente=True) -> AuthContext:
    return AuthContext(
        tienda_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        cliente_id=uuid.uuid4() if cliente else None,
    )


def _claims_validos(**cambios) -> dict:
    ahora = int(time.time())
    claims = {
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": ahora,
        "exp": ahora + 60,
        "tid": str(uuid.uuid4()),
        "sid": str(uuid.uuid4()),
        "anon": True,
    }
    claims.update(cambios)
    return {k: v for k, v in claims.items() if v is not None}


@pytest.mark.parametrize("cliente", [True, False])
def test_ida_y_vuelta(cliente):
    ctx = _ctx(cliente)
    assert validar_token(emitir_token(ctx)) == ctx


def test_token_anonimo_no_lleva_sub():
    ctx = _ctx(cliente=False)
    claims = jwt.decode(emitir_token(ctx), SECRET, algorithms=["HS256"], audience=JWT_AUDIENCE)
    assert claims["anon"] is True
    assert "sub" not in claims


def test_thread_id_tiene_namespace_de_tienda():
    ctx = _ctx()
    assert ctx.thread_id == f"{ctx.tienda_id}:{ctx.session_id}"


def test_rechaza_token_expirado():
    token = jwt.encode(_claims_validos(exp=int(time.time()) - 10), SECRET, algorithm="HS256")
    with pytest.raises(TokenInvalido):
        validar_token(token)


def test_rechaza_firma_con_otro_secreto():
    token = jwt.encode(_claims_validos(), "otro-secreto-distinto-de-al-menos-32-bytes", algorithm="HS256")
    with pytest.raises(TokenInvalido):
        validar_token(token)


def test_rechaza_alg_none():
    token = jwt.encode(_claims_validos(), None, algorithm="none")
    with pytest.raises(TokenInvalido):
        validar_token(token)


@pytest.mark.parametrize("claim, valor", [("aud", "otra-app"), ("iss", "otro-emisor")])
def test_rechaza_issuer_o_audience_ajenos(claim, valor):
    token = jwt.encode(_claims_validos(**{claim: valor}), SECRET, algorithm="HS256")
    with pytest.raises(TokenInvalido):
        validar_token(token)


@pytest.mark.parametrize(
    "cambios",
    [
        {"anon": True, "sub": str(uuid.uuid4())},  # anonimo con cliente
        {"anon": False},  # no anonimo sin cliente
        {"sid": None},  # falta la sesion
        {"tid": "no-es-un-uuid"},
    ],
)
def test_rechaza_claims_inconsistentes(cambios):
    token = jwt.encode(_claims_validos(**cambios), SECRET, algorithm="HS256")
    with pytest.raises(TokenInvalido):
        validar_token(token)


def test_api_key_y_su_hash():
    key = generar_api_key()
    assert key.startswith("vth_")
    assert key != generar_api_key()
    assert hash_api_key(key) == hash_api_key(key)
    assert len(hash_api_key(key)) == 64
