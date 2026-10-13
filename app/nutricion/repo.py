"""Guia activa de cada tienda, leida de Neo4j con cache en memoria.

Si Neo4j no esta configurado (NEO4J_URI vacio), no responde o la tienda no tiene guia
activa, se usa la guia por defecto (GUIA_POR_DEFECTO, un YAML del repo) y se loguea: el
asesor sigue funcionando con la guia generica.
"""

import logging
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

from app.core.config import get_settings
from app.nutricion.grafo import LEER_ACTIVA, guia_desde_registro
from app.nutricion.guia import Guia, cargar_yaml

logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[2]

_driver = None
_cache: Dict[str, Tuple[float, Guia, str]] = {}


def _get_driver():
    global _driver
    s = get_settings()
    if not s.neo4j_uri:
        return None
    if _driver is None:
        from neo4j import AsyncGraphDatabase

        _driver = AsyncGraphDatabase.driver(
            s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password or ""), connection_timeout=3
        )
    return _driver


async def close_neo4j() -> None:
    global _driver
    if _driver is not None:
        try:
            await _driver.close()
        finally:
            _driver = None
    _cache.clear()


@lru_cache
def guia_por_defecto() -> Guia:
    ruta = Path(get_settings().guia_por_defecto)
    return cargar_yaml(ruta if ruta.is_absolute() else RAIZ / ruta)


async def _leer_de_neo4j(tienda_id: str) -> Optional[Guia]:
    driver = _get_driver()
    if driver is None:
        return None
    async with driver.session() as s:
        registro = await (await s.run(LEER_ACTIVA, tienda_id=tienda_id)).single()
    return guia_desde_registro(registro["contenido"]) if registro else None


async def guia_activa(tienda_id: str) -> Tuple[Guia, str]:
    """(guia, origen) con origen "neo4j" o "por_defecto". Cache por tienda (GUIA_CACHE_SEGUNDOS)."""
    ahora = time.monotonic()
    if (en_cache := _cache.get(tienda_id)) and ahora - en_cache[0] < get_settings().guia_cache_segundos:
        return en_cache[1], en_cache[2]
    guia, origen = None, "neo4j"
    try:
        guia = await _leer_de_neo4j(tienda_id)
        if guia is None and get_settings().neo4j_uri:
            logger.warning("La tienda %s no tiene guia activa en Neo4j: se usa la guia por defecto", tienda_id)
    except Exception:
        logger.exception("No se pudo leer la guia de Neo4j: se usa la guia por defecto")
    if guia is None:
        guia, origen = guia_por_defecto(), "por_defecto"
    _cache[tienda_id] = (ahora, guia, origen)
    return guia, origen


def tienda_de(thread_id: str) -> str:
    """El thread_id es `{tienda_id}:{session_id}` (AuthContext.thread_id)."""
    tienda = thread_id.split(":", 1)[0]
    try:
        return str(uuid.UUID(tienda))
    except ValueError:
        return tienda  # evals/tests usan thread_ids sin UUID: van a la guia por defecto
