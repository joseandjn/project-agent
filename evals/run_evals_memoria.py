"""Eval del extractor de memoria de largo plazo: corre los casos de casos_memoria.py contra
el LLM real y verifica aserciones duras sobre el perfil extraido.

Sirve para elegir MEMORIA_MODEL: correrlo con distintos modelos y comparar aciertos y
latencia. Usa el mismo LLM_PROVIDER del .env.

    python -m evals.run_evals_memoria                       # modelo de MEMORIA_MODEL (o el del chat)
    python -m evals.run_evals_memoria --modelo qwen2.5:14b   # probar otro modelo del proveedor
    python -m evals.run_evals_memoria --repeticiones 3       # medir estabilidad
"""

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import get_settings
from app.memory.long_term.extractor import extraer_perfil
from app.services.config_llm import build_chat_model
from evals.casos.casos_memoria import CASOS_MEMORIA

REPORTES_DIR = Path(__file__).resolve().parent / "reportes"


def _nombre_modelo(modelo: Optional[str]) -> str:
    settings = get_settings()
    proveedor = settings.llm_provider.strip().lower()
    por_defecto = getattr(settings, f"{proveedor}_chat_model", "?")
    return f"{proveedor}:{modelo or settings.memoria_model or por_defecto}"


async def correr(modelo: Optional[str], repeticiones: int) -> dict:
    settings = get_settings()
    llm = build_chat_model(settings, model=modelo or settings.memoria_model)
    filas = []
    for caso in CASOS_MEMORIA:
        for rep in range(repeticiones):
            inicio = time.perf_counter()
            perfil = await extraer_perfil(caso.perfil_previo, caso.mensajes, model=llm)
            segundos = time.perf_counter() - inicio
            if perfil is None:
                chequeos = {nombre: False for nombre, _ in caso.chequeos}
            else:
                chequeos = {nombre: bool(fn(perfil)) for nombre, fn in caso.chequeos}
            filas.append(
                {
                    "caso_id": caso.id,
                    "repeticion": rep + 1,
                    "descripcion": caso.descripcion,
                    "aprobado": all(chequeos.values()),
                    "chequeos": chequeos,
                    "segundos": round(segundos, 2),
                    "perfil": perfil.model_dump() if perfil else None,
                }
            )
            estado = "OK  " if filas[-1]["aprobado"] else "FALLA"
            fallidos = [n for n, ok in chequeos.items() if not ok]
            print(f"[{estado}] {caso.id} #{rep + 1} ({segundos:.1f}s)" + (f" — falla: {', '.join(fallidos)}" if fallidos else ""))

    aprobados = sum(f["aprobado"] for f in filas)
    return {
        "modelo": _nombre_modelo(modelo),
        "aprobados": aprobados,
        "total": len(filas),
        "segundos_promedio": round(sum(f["segundos"] for f in filas) / len(filas), 2),
        "casos": filas,
        "generado": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Eval del extractor de memoria de largo plazo")
    parser.add_argument("--modelo", help="Modelo del LLM_PROVIDER a probar (por defecto MEMORIA_MODEL o el del chat)")
    parser.add_argument("--repeticiones", type=int, default=1)
    args = parser.parse_args()

    reporte = asyncio.run(correr(args.modelo, args.repeticiones))
    print(
        f"\n{reporte['modelo']}: {reporte['aprobados']}/{reporte['total']} casos aprobados, "
        f"{reporte['segundos_promedio']}s promedio por extraccion"
    )

    REPORTES_DIR.mkdir(exist_ok=True)
    marca = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destino = REPORTES_DIR / f"memoria_{marca}.json"
    destino.write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Reporte: {destino.relative_to(REPORTES_DIR.parent.parent)}")


if __name__ == "__main__":
    main()
