"""Registra una tienda y le genera su API key. La key se muestra UNA sola vez: en la base
solo queda su sha256.

Uso (desde la raiz del repo, con `alembic upgrade head` ya aplicado):
    python -m scripts.crear_tienda "Nombre de la tienda"
"""

import argparse
import asyncio

from app.core.security import generar_api_key, hash_api_key
from app.db.models import Tienda
from app.db.session import close_engine, get_sessionmaker


async def crear_tienda(nombre: str) -> tuple[Tienda, str]:
    api_key = generar_api_key()
    tienda = Tienda(nombre=nombre, api_key_hash=hash_api_key(api_key))
    async with get_sessionmaker()() as db:
        db.add(tienda)
        await db.commit()
    return tienda, api_key


async def main() -> None:
    parser = argparse.ArgumentParser(description="Registra una tienda y genera su API key.")
    parser.add_argument("nombre", help="Nombre de la tienda")
    args = parser.parse_args()

    try:
        tienda, api_key = await crear_tienda(args.nombre)
    finally:
        await close_engine()

    print(f"Tienda creada: {tienda.nombre} ({tienda.id})")
    print(f"API key (guardala ahora, no se vuelve a mostrar): {api_key}")


if __name__ == "__main__":
    asyncio.run(main())
