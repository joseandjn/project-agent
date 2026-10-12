import pytest


@pytest.fixture
def sin_registro_feedback(monkeypatch):
    """Las rutas de chat registran cada respuesta en Redis para el feedback; en los tests
    unitarios de rutas (sin Redis) se reemplaza por un no-op que anota los mensaje_id."""
    registrados = []

    async def _contar(thread_id):
        return 0

    async def _registrar(ctx, mensaje_id, desde):
        registrados.append(str(mensaje_id))

    for ruta in ("app.api.v1.routes.chat", "app.api.v2.routes.chat"):
        monkeypatch.setattr(f"{ruta}.contar_mensajes", _contar)
        monkeypatch.setattr(f"{ruta}.registrar_mensaje", _registrar)
    return registrados
