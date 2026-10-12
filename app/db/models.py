"""Tablas de Postgres (SQLAlchemy 2.0). El esquema real lo crean las migraciones de Alembic
(`app/db/migrations/`); estas clases son la fuente que usa `alembic revision --autogenerate`.

Diseño: docs/memoria_largo_plazo.md (Fase 1: `tiendas` y `clientes`; Fase 2: perfiles) y
docs/feedback_cliente.md (`feedback_mensajes`).
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tienda(Base):
    """Una tienda que integra el chat. Se autentica de servidor a servidor con su API key;
    solo se guarda el sha256 de la key (alta entropia, no hace falta bcrypt)."""

    __tablename__ = "tiendas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Reservado para CORS por tienda; todavia no se usa (fuera de alcance de la Fase 1).
    origenes_permitidos: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Cliente(Base):
    """Un usuario final de una tienda. `external_id` es el id del usuario en el sistema de la
    tienda; hacia afuera (en el JWT) solo viaja el `id` interno."""

    __tablename__ = "clientes"
    __table_args__ = (UniqueConstraint("tienda_id", "external_id", name="uq_clientes_tienda_external"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tienda_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tiendas.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PerfilClienteDB(Base):
    """Memoria de largo plazo: un perfil estructurado por cliente (`PerfilCliente` de
    app/memory/long_term/models.py, serializado a JSONB). No se guarda la transcripcion."""

    __tablename__ = "perfiles_cliente"

    cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id", ondelete="CASCADE"), primary_key=True
    )
    perfil: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PerfilClienteHistorial(Base):
    """Cada version guardada de un perfil, para auditar o revertir un envenenamiento de
    memoria (ASI06). Se borra en cascada con el cliente."""

    __tablename__ = "perfiles_cliente_historial"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    perfil: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FeedbackMensaje(Base):
    """Voto del cliente (positivo/negativo, motivo opcional) sobre una respuesta del agente.
    Un voto por mensaje: si vuelve a votar, se reemplaza. `skus` son los productos que el
    agente consulto en ese turno (de las tool calls, no de lo que diga el cliente)."""

    __tablename__ = "feedback_mensajes"
    __table_args__ = (
        CheckConstraint("valor IN ('positivo', 'negativo')", name="ck_feedback_valor"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tienda_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tiendas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nulo en sesiones anonimas.
    cliente_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id", ondelete="CASCADE"), nullable=True
    )
    thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    mensaje_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    valor: Mapped[str] = mapped_column(String(8), nullable=False)
    motivo: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    comentario: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    skus: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
