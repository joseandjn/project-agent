"""Contexto de un turno para el agente compartido (`app/services/agente.py`).

El agente se crea una vez por proceso; lo que cambia en cada request viaja aca, en
`agent.ainvoke(..., context=Contexto(...))`. El LLM nunca lo ve ni lo puede cambiar:
- `thread_id` lo leen las tools via `ToolRuntime` (p. ej. `derivar_veterinario`);
- `perfil` lo usa el middleware de prompt dinamico para armar el system prompt.
"""

from dataclasses import dataclass
from typing import Optional

from app.memory.long_term.models import PerfilCliente


@dataclass(frozen=True)
class Contexto:
    thread_id: str
    perfil: Optional[PerfilCliente] = None
