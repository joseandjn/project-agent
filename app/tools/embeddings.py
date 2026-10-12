import asyncio
import math
from typing import Dict, List

from ollama import AsyncClient

from app.core.config import get_settings
from app.tools.catalog import get_catalog

_catalog_embeddings: Dict[str, List[float]] = {}
_embeddings_lock = asyncio.Lock()


async def embed_text(texto: str) -> List[float]:
    """Embedding segun EMBEDDING_PROVIDER: "ollama" (local) u "openai" (sin Ollama)."""
    # Clientes sin cachear: uno persistente atado a un event loop rompe si se reutiliza
    # desde otro loop (ver tests de integracion, que corren cada test en su propio loop).
    settings = get_settings()
    proveedor = settings.embedding_provider.strip().lower()

    if proveedor == "ollama":
        client = AsyncClient(host=settings.ollama_base_url)
        response = await client.embeddings(model=settings.ollama_embedding_model, prompt=texto)
        return response["embedding"]

    if proveedor == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY no esta configurado (EMBEDDING_PROVIDER=openai)")
        from openai import AsyncOpenAI

        async with AsyncOpenAI(api_key=settings.openai_api_key) as client:
            response = await client.embeddings.create(model=settings.openai_embedding_model, input=texto)
        return response.data[0].embedding

    raise ValueError(f"EMBEDDING_PROVIDER no soportado: {settings.embedding_provider!r} (usar 'ollama' u 'openai')")


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def get_catalog_embeddings() -> Dict[str, List[float]]:
    """Calcula (una sola vez, cacheado en memoria) el embedding de cada producto del catalogo."""
    if _catalog_embeddings:
        return _catalog_embeddings

    async with _embeddings_lock:
        if _catalog_embeddings:
            return _catalog_embeddings
        catalogo = get_catalog()
        vectores = await _embed_textos([p["documento_busqueda"] for p in catalogo])
        for producto, vector in zip(catalogo, vectores):
            _catalog_embeddings[producto["sku"]] = vector
        return _catalog_embeddings


async def _embed_textos(textos: List[str]) -> List[List[float]]:
    """Varios embeddings: con OpenAI en una sola llamada (el catalogo entero tarda ~1 s en vez
    de ~1 s por producto); con Ollama, uno por uno."""
    settings = get_settings()
    if settings.embedding_provider.strip().lower() == "openai" and settings.openai_api_key:
        from openai import AsyncOpenAI

        async with AsyncOpenAI(api_key=settings.openai_api_key) as client:
            response = await client.embeddings.create(model=settings.openai_embedding_model, input=textos)
        return [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
    return [await embed_text(t) for t in textos]
