"""Eval del control de tema: (1) el clasificador contra casos_tema.py con aserciones duras y
(2) la conversacion de la demo de punta a punta contra el agente real con el control prendido.

    python -m evals.run_evals_tema                      # modelo de TEMA_MODEL (o el del chat)
    python -m evals.run_evals_tema --modelo llama3.1:8b # otro modelo del LLM_PROVIDER
    python -m evals.run_evals_tema --repeticiones 3     # medir estabilidad

No manda trazas a Langfuse salvo con --langfuse.
"""

import argparse
import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.guardrails import tema
from app.memory.short_term.session_memory import close_checkpointer, get_checkpointer
from app.services.config_llm import build_chat_model
from app.services.llm_client import generate_reply
from evals.casos.casos_tema import CASOS_TEMA, CONVERSACION_DEMO, TERMINOS_PROHIBIDOS

REPORTES_DIR = Path(__file__).resolve().parent / "reportes"


async def correr(modelo, repeticiones):
    settings = get_settings()
    llm = build_chat_model(settings, model=modelo or settings.tema_model)
    filas = []
    for caso in CASOS_TEMA:
        for rep in range(repeticiones):
            inicio = time.perf_counter()
            categoria = await tema.clasificar(caso.mensaje, caso.previos, model=llm)
            seg = time.perf_counter() - inicio
            ok = categoria in caso.aceptadas
            filas.append({"caso": caso.id, "rep": rep + 1, "categoria": categoria, "aceptadas": sorted(caso.aceptadas), "ok": ok, "segundos": round(seg, 2)})
            print(f"[{'OK  ' if ok else 'FALLA'}] {caso.id} #{rep + 1} -> {categoria} ({seg:.1f}s)" + ("" if ok else f" (esperado {sorted(caso.aceptadas)})"))

    # Conversacion completa con el agente real (el control usa el mismo modelo elegido).
    settings.tema_guard_enabled = True
    if modelo:
        tema.get_tema_model.cache_clear()
        settings.tema_model = modelo
    thread = f"eval-tema:{uuid.uuid4()}"
    turnos = []
    for mensaje in CONVERSACION_DEMO:
        respuesta = await generate_reply(mensaje, thread)
        prohibidos = [t for t in TERMINOS_PROHIBIDOS if t in respuesta.lower()]
        turnos.append({"mensaje": mensaje, "respuesta": respuesta, "prohibidos": prohibidos, "ok": not prohibidos})
        print(f"[{'OK  ' if not prohibidos else 'FALLA'}] conversacion: {mensaje[:50]!r}" + (f" -> contiene {prohibidos}" if prohibidos else ""))
    await (await get_checkpointer()).adelete_thread(thread)
    await close_checkpointer()

    aprobados = sum(f["ok"] for f in filas)
    return {
        "modelo": f"{settings.llm_provider}:{modelo or settings.tema_model or getattr(settings, settings.llm_provider + '_chat_model', '?')}",
        "clasificador": {"aprobados": aprobados, "total": len(filas), "segundos_promedio": round(sum(f["segundos"] for f in filas) / len(filas), 2), "casos": filas},
        "conversacion_demo": {"ok": all(t["ok"] for t in turnos), "turnos": turnos},
        "generado": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="Eval del control de tema")
    parser.add_argument("--modelo")
    parser.add_argument("--repeticiones", type=int, default=1)
    parser.add_argument("--langfuse", action="store_true", help="Mandar trazas a Langfuse")
    args = parser.parse_args()
    if not args.langfuse:
        get_settings().langfuse_enabled = False

    r = asyncio.run(correr(args.modelo, args.repeticiones))
    c = r["clasificador"]
    print(f"\n{r['modelo']}: clasificador {c['aprobados']}/{c['total']} ({c['segundos_promedio']}s promedio); "
          f"conversacion de la demo: {'OK' if r['conversacion_demo']['ok'] else 'FALLA'}")
    REPORTES_DIR.mkdir(exist_ok=True)
    destino = REPORTES_DIR / f"tema_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    destino.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Reporte: {destino.relative_to(REPORTES_DIR.parent.parent)}")


if __name__ == "__main__":
    main()
