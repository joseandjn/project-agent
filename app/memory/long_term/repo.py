"""Acceso a Postgres para los perfiles de cliente (memoria de largo plazo)."""

import uuid
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PerfilClienteDB, PerfilClienteHistorial
from app.memory.long_term.models import PerfilCliente


async def leer_perfil(db: AsyncSession, cliente_id: uuid.UUID) -> Optional[PerfilCliente]:
    fila = await db.get(PerfilClienteDB, cliente_id)
    return PerfilCliente.model_validate(fila.perfil) if fila else None


async def guardar_perfil(db: AsyncSession, cliente_id: uuid.UUID, perfil: PerfilCliente, thread_id: str) -> int:
    """Guarda una version nueva del perfil y la registra en el historial. Devuelve la version.

    Varias sesiones simultaneas del mismo cliente quedan fuera de alcance (gana la ultima
    escritura); dentro de una sesion, el lock de Redis de consolidacion.py serializa."""
    datos = perfil.model_dump(mode="json")
    fila = await db.get(PerfilClienteDB, cliente_id, with_for_update=True)
    if fila is None:
        fila = PerfilClienteDB(cliente_id=cliente_id, perfil=datos, version=1)
        db.add(fila)
    else:
        fila.perfil = datos
        fila.version += 1
    db.add(PerfilClienteHistorial(cliente_id=cliente_id, version=fila.version, perfil=datos, thread_id=thread_id))
    await db.commit()
    return fila.version


async def borrar_perfil(db: AsyncSession, cliente_id: uuid.UUID) -> bool:
    """Borra el perfil y todo su historial (derecho de supresion). True si habia algo."""
    borrado = await db.execute(delete(PerfilClienteDB).where(PerfilClienteDB.cliente_id == cliente_id))
    await db.execute(delete(PerfilClienteHistorial).where(PerfilClienteHistorial.cliente_id == cliente_id))
    await db.commit()
    return borrado.rowcount > 0

