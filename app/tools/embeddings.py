import asyncio
import math
from typing import Dict, List

from ollama import AsyncClient

from app.core.config import get_settings
from app.tools.catalog import get_catalog

_catalog_embeddings: Dict[str, List[float]] = {}
_embeddings_lock = asyncio.Lock()


async def embed_text(texto: str) -> List[float]:
    # Cliente sin cachear: uno persistente atado a un event loop rompe si se reutiliza
    # desde otro loop (ver tests de integracion, que corren cada test en su propio loop).
    settings = get_settings()
    client = AsyncClient(host=settings.ollama_base_url)
    response = await client.embeddings(model=settings.ollama_embedding_model, prompt=texto)
    return response["embedding"]


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
        for producto in get_catalog():
            _catalog_embeddings[producto["sku"]] = await embed_text(producto["documento_busqueda"])
        return _catalog_embeddings
