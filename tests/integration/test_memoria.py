"""Memoria de largo plazo contra Redis y Postgres reales; el LLM del extractor y el del
agente son fakes. Requiere Redis (RediSearch) en REDIS_URL y Postgres en POSTGRES_DSN con
`alembic upgrade head` aplicado; si no, se saltea."""

import asyncio
import time
import uuid

import httpx
import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.runnables import RunnableLambda
from sqlalchemy import delete, func, inspect, select

from app.core.config import get_settings
from app.core.security import AuthContext, emitir_token, validar_token
from app.db.models import PerfilClienteHistorial, Tienda
from app.db.session import close_engine, get_sessionmaker
from app.main import app
from app.memory.long_term.consolidacion import (
    ACTIVIDAD_KEY,
    close_redis,
    consolidar,
    consolidar_inactivas,
    debe_consolidar,
    get_redis,
    registrar_turno,
)
from app.memory.long_term.models import Mascota, PerfilExtraido
from app.memory.long_term.repo import leer_perfil
from app.memory.short_term.session_memory import close_checkpointer, get_checkpointer, session_config
from scripts.crear_tienda import crear_tienda


async def _servicios_listos() -> bool:
    try:
        await get_redis().ping()
        async with get_sessionmaker()() as db:
            conn = await db.connection()
            return await conn.run_sync(lambda c: inspect(c).has_table("perfiles_cliente"))
    except Exception:
        return False
    finally:
        await close_redis()
        await close_engine()


pytestmark = pytest.mark.skipif(
    not asyncio.run(_servicios_listos()),
    reason="Redis o Postgres no disponibles, o falta `alembic upgrade head`",
)

SALIDA_LLM = PerfilExtraido(mascotas=[Mascota(nombre="Rocky", especie="Perro", peso_kg=12)], resumen="Busca alimento.")


class _ExtractorFake:
    def __init__(self):
        self.llamadas = 0

    def with_structured_output(self, schema):
        def _invocar(_):
            self.llamadas += 1
            return SALIDA_LLM

        return RunnableLambda(_invocar)


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "jwt_secret", "secreto-de-test-de-al-menos-32-bytes!!")


@pytest.fixture
def extractor(monkeypatch):
    fake = _ExtractorFake()
    monkeypatch.setattr("app.memory.long_term.extractor.get_memoria_model", lambda: fake)
    return fake


@pytest.fixture
async def ctx():
    """Sesion de un cliente real (tienda + cliente en Postgres). Limpia Redis y Postgres."""
    tienda, api_key = await crear_tienda(f"test-{uuid.uuid4().hex[:8]}")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/auth/token", json={"external_user_id": "u-1"}, headers={"X-API-Key": api_key})
    contexto = validar_token(r.json()["access_token"])
    yield contexto

    r = get_redis()
    await r.zrem(ACTIVIDAD_KEY, contexto.thread_id)
    await r.delete(f"vethis:mem:sesion:{contexto.thread_id}", f"vethis:mem:lock:{contexto.thread_id}")
    await (await get_checkpointer()).adelete_thread(contexto.thread_id)
    async with get_sessionmaker()() as db:
        await db.execute(delete(Tienda).where(Tienda.id == tienda.id))
        await db.commit()
    # Los clientes quedan atados al event loop del test: se cierran para no reusarlos.
    await close_redis()
    await close_checkpointer()
    await close_engine()


async def _conversar(thread_id: str, *mensajes: str) -> None:
    """Escribe turnos en el checkpoint de Redis con un agente de modelo fake."""
    modelo = GenericFakeChatModel(messages=iter([f"respuesta {i}" for i in range(len(mensajes))]))
    agente = create_agent(modelo, tools=[], system_prompt="x", checkpointer=await get_checkpointer())
    for m in mensajes:
        await agente.ainvoke({"messages": [{"role": "user", "content": m}]}, config=session_config(thread_id))


async def _versiones(cliente_id) -> int:
    async with get_sessionmaker()() as db:
        return await db.scalar(
            select(func.count()).select_from(PerfilClienteHistorial).where(PerfilClienteHistorial.cliente_id == cliente_id)
        )


async def test_cada_n_turnos_dispara_la_consolidacion(ctx):
    n = get_settings().memoria_consolidar_cada_n_turnos
    pendientes = [await registrar_turno(ctx) for _ in range(n)]
    assert pendientes == list(range(1, n + 1))
    assert [debe_consolidar(p) for p in pendientes] == [False] * (n - 1) + [True]


async def test_consolidar_guarda_perfil_y_no_reprocesa(ctx, extractor):
    await _conversar(ctx.thread_id, "Tengo un perro, Rocky, de 12 kg")
    await registrar_turno(ctx)

    assert await consolidar(ctx.thread_id) is True
    async with get_sessionmaker()() as db:
        perfil = await leer_perfil(db, ctx.cliente_id)
    assert perfil.mascotas[0].nombre == "Rocky"
    estado = await get_redis().hgetall(f"vethis:mem:sesion:{ctx.thread_id}")
    assert estado["pendientes"] == "0"
    assert estado["consolidados"] == "2"  # mensaje del cliente + respuesta

    # Sin mensajes nuevos no vuelve a llamar al LLM ni crea otra version.
    assert await consolidar(ctx.thread_id) is False
    assert extractor.llamadas == 1

    await _conversar(ctx.thread_id, "Ahora pesa 13 kg")
    assert await consolidar(ctx.thread_id) is True
    assert extractor.llamadas == 2
    assert await _versiones(ctx.cliente_id) == 2


async def test_lock_evita_consolidaciones_simultaneas(ctx, extractor):
    await _conversar(ctx.thread_id, "Hola")
    await registrar_turno(ctx)
    resultados = await asyncio.gather(consolidar(ctx.thread_id), consolidar(ctx.thread_id))
    assert sorted(resultados) == [False, True]
    assert extractor.llamadas == 1


async def test_sweeper_consolida_sesiones_inactivas(ctx, extractor):
    await _conversar(ctx.thread_id, "Tengo un gato")
    await registrar_turno(ctx)
    viejo = time.time() - get_settings().memoria_inactividad_segundos - 5
    await get_redis().zadd(ACTIVIDAD_KEY, {ctx.thread_id: viejo})

    assert await consolidar_inactivas() >= 1
    assert await _versiones(ctx.cliente_id) == 1
    assert await get_redis().zscore(ACTIVIDAD_KEY, ctx.thread_id) is None


async def test_sweeper_ignora_sesiones_activas(ctx, extractor):
    await _conversar(ctx.thread_id, "Tengo un gato")
    await registrar_turno(ctx)  # actividad = ahora
    await consolidar_inactivas()
    assert extractor.llamadas == 0
    assert await get_redis().zscore(ACTIVIDAD_KEY, ctx.thread_id) is not None


async def test_chat_usa_el_perfil_y_lanza_la_consolidacion_al_turno_n(ctx, extractor, monkeypatch):
    await _conversar(ctx.thread_id, "Tengo un perro, Rocky")
    await registrar_turno(ctx)
    await consolidar(ctx.thread_id)

    perfiles, consolidaciones = [], []

    async def _fake_reply(mensaje, thread_id, perfil=None):
        perfiles.append(perfil)
        return "ok"

    async def _fake_consolidar(thread_id):
        consolidaciones.append(thread_id)

    monkeypatch.setattr("app.api.v1.routes.chat.generate_reply", _fake_reply)
    monkeypatch.setattr("app.api.v1.routes.chat.consolidar", _fake_consolidar)

    headers = {"Authorization": f"Bearer {emitir_token(ctx)}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        for _ in range(get_settings().memoria_consolidar_cada_n_turnos):
            assert (await c.post("/api/v1/chat", json={"mensaje": "hola"}, headers=headers)).status_code == 200

    assert all(p.mascotas[0].nombre == "Rocky" for p in perfiles)
    assert consolidaciones == [ctx.thread_id]


async def test_memoria_ver_y_borrar(ctx, extractor):
    headers = {"Authorization": f"Bearer {emitir_token(ctx)}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/api/v1/memoria", headers=headers)).status_code == 404

        await _conversar(ctx.thread_id, "Tengo un perro, Rocky")
        await registrar_turno(ctx)
        await consolidar(ctx.thread_id)

        r = await c.get("/api/v1/memoria", headers=headers)
        assert r.status_code == 200
        assert r.json()["mascotas"][0]["nombre"] == "Rocky"

        assert (await c.delete("/api/v1/memoria", headers=headers)).status_code == 204
        assert (await c.get("/api/v1/memoria", headers=headers)).status_code == 404
        assert await _versiones(ctx.cliente_id) == 0


async def test_memoria_rechaza_sesiones_anonimas():
    anonimo = AuthContext(tienda_id=uuid.uuid4(), session_id=uuid.uuid4(), cliente_id=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/memoria", headers={"Authorization": f"Bearer {emitir_token(anonimo)}"})
    assert r.status_code == 403
