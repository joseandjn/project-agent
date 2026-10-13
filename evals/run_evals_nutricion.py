"""Eval de la guia nutricional contra el agente real (/api/v2/chat): tools que usa y datos de
la guia en la respuesta. Usa la guia activa de la tienda en Neo4j si NEO4J_URI esta
configurado (si no, la guia por defecto).

    python -m evals.run_evals_nutricion --tienda <tienda_id> [--repeticiones 3]

No manda trazas a Langfuse salvo con --langfuse.
"""

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import AIMessage

from app.core.config import get_settings
from app.memory.short_term.session_memory import close_checkpointer, get_checkpointer, historial
from app.nutricion.repo import close_neo4j
from app.services.agente import generar_respuesta
from evals.casos.casos_nutricion import CASOS_NUTRICION

REPORTES_DIR = Path(__file__).resolve().parent / "reportes"


async def correr(tienda, repeticiones):
    filas = []
    for caso in CASOS_NUTRICION:
        for rep in range(repeticiones):
            thread = f"{tienda}:{uuid.uuid4()}"
            for mensaje in caso.mensajes:
                antes = len(await historial(await get_checkpointer(), thread))
                respuesta = await generar_respuesta(mensaje, thread)
            nuevos = (await historial(await get_checkpointer(), thread))[antes:]
            usadas = [c["name"] for m in nuevos if isinstance(m, AIMessage) for c in m.tool_calls]
            texto = respuesta.lower()
            faltan_tools = [g for g in caso.tools if not any(t in usadas for t in g)]
            faltan_datos = [g for g in caso.contiene if not any(v.lower() in texto for v in g)]
            ok = not faltan_tools and not faltan_datos
            filas.append({"caso": caso.id, "rep": rep + 1, "ok": ok, "tools": usadas, "faltan_tools": faltan_tools,
                          "faltan_datos": faltan_datos, "respuesta": respuesta})
            detalle = "" if ok else f" faltan tools {faltan_tools} / datos {faltan_datos} (uso {usadas})"
            print(f"[{'OK  ' if ok else 'FALLA'}] {caso.id} #{rep + 1}{detalle}")
            await (await get_checkpointer()).adelete_thread(thread)
    await close_checkpointer()
    await close_neo4j()
    return filas


def main():
    parser = argparse.ArgumentParser(description="Eval de la guia nutricional")
    parser.add_argument("--tienda", default="aad6e175-8952-42d9-b026-113e4d8dd6b9", help="UUID de la tienda (guia activa)")
    parser.add_argument("--repeticiones", type=int, default=1)
    parser.add_argument("--langfuse", action="store_true")
    args = parser.parse_args()
    if not args.langfuse:
        get_settings().langfuse_enabled = False
    filas = asyncio.run(correr(args.tienda, args.repeticiones))
    aprobados = sum(f["ok"] for f in filas)
    print(f"\n{aprobados}/{len(filas)} casos aprobados")
    REPORTES_DIR.mkdir(exist_ok=True)
    destino = REPORTES_DIR / f"nutricion_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    destino.write_text(json.dumps({"aprobados": aprobados, "total": len(filas), "casos": filas}, ensure_ascii=False, indent=2))
    print(f"Reporte: {destino.relative_to(REPORTES_DIR.parent.parent)}")


if __name__ == "__main__":
    main()
