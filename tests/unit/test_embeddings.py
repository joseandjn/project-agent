"""Seleccion del proveedor de embeddings (EMBEDDING_PROVIDER); sin red."""

import pytest

from app.core.config import get_settings
from app.tools import embeddings


class _OpenAIFake:
    def __init__(self, api_key):
        self.api_key = api_key
        self.embeddings = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def create(self, model, input):
        _OpenAIFake.llamadas.append((model, input))

        class _Dato:
            embedding = [0.1, 0.2]

        class _Respuesta:
            data = [_Dato()]

        return _Respuesta()


async def test_openai_usa_el_modelo_configurado(monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_provider", "openai")
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-test")
    _OpenAIFake.llamadas = []
    monkeypatch.setattr("openai.AsyncOpenAI", _OpenAIFake)

    assert await embeddings.embed_text("perro adulto") == [0.1, 0.2]
    assert _OpenAIFake.llamadas == [(get_settings().openai_embedding_model, "perro adulto")]


async def test_openai_sin_key_falla_claro(monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_provider", "openai")
    monkeypatch.setattr(get_settings(), "openai_api_key", None)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await embeddings.embed_text("x")


async def test_proveedor_desconocido(monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_provider", "otro")
    with pytest.raises(ValueError, match="EMBEDDING_PROVIDER"):
        await embeddings.embed_text("x")
