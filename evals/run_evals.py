import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from deepeval.test_case import LLMTestCase

from app.services.llm_client import generate_reply
from evals.casos.casos_prueba import CASOS_DE_PRUEBA
from evals.metrics import build_metrics

REPORTES_DIR = Path(__file__).resolve().parent / "reportes"


async def generar_test_cases() -> List[LLMTestCase]:
    """Corre cada caso contra el agente real (segun LLM_PROVIDER) para obtener
    actual_output de verdad, incluyendo el historial de turnos previos si los hay."""
    test_cases = []

    for caso in CASOS_DE_PRUEBA:
        session_id = f"eval-{caso.id}"
        historial = []
        respuesta = ""

        for mensaje in caso.mensajes:
            historial.append({"role": "user", "content": mensaje})
            respuesta = await generate_reply(historial, session_id)
            historial.append({"role": "assistant", "content": respuesta})

        test_cases.append(
            LLMTestCase(
                input=caso.mensajes[-1],
                actual_output=respuesta,
                context=caso.contexto or None,
                expected_output=caso.expected_output,
                metadata={"caso_id": caso.id, "categoria": caso.categoria, "descripcion": caso.descripcion},
            )
        )

    return test_cases


async def ejecutar_evaluaciones(test_cases: List[LLMTestCase]) -> dict:
    """Corre las 9 metricas GEval sobre cada test case y arma la matriz de resultados."""
    metrics = build_metrics()
    resultados = []

    for test_case in test_cases:
        fila = {
            "caso_id": test_case.metadata["caso_id"],
            "descripcion": test_case.metadata["descripcion"],
            "categoria": test_case.metadata["categoria"],
            "input": test_case.input,
            "actual_output": test_case.actual_output,
            "metricas": {},
        }

        for metric in metrics:
            await metric.a_measure(test_case, _show_indicator=False)
            fila["metricas"][metric.name] = {
                "score": round(metric.score, 3),
                "razon": metric.reason,
                "aprobado": metric.is_successful(),
            }

        resultados.append(fila)

    return {"casos": resultados, "generado": datetime.now(timezone.utc).isoformat()}


def generar_reporte(resultados: dict) -> Path:
    """Imprime un reporte en consola y lo guarda como JSON en evals/reportes/."""
    nombres_metricas = sorted({m for caso in resultados["casos"] for m in caso["metricas"]})
    promedios = defaultdict(list)

    print("\n" + "=" * 100)
    print("REPORTE DE EVALUACION - VethisAgent")
    print("=" * 100)

    for caso in resultados["casos"]:
        print(f"\n[{caso['caso_id']}] {caso['descripcion']} (categoria: {caso['categoria']})")
        for nombre in nombres_metricas:
            m = caso["metricas"][nombre]
            promedios[nombre].append(m["score"])
            marca = "OK" if m["aprobado"] else "FALLA"
            print(f"  - {nombre:<32} {m['score']:.2f}  [{marca}]")

    print("\n" + "-" * 100)
    print("PROMEDIO POR METRICA (todos los casos)")
    print("-" * 100)
    for nombre in nombres_metricas:
        valores = promedios[nombre]
        print(f"  - {nombre:<32} {sum(valores) / len(valores):.3f}")

    total_valores = [v for valores in promedios.values() for v in valores]
    print("-" * 100)
    print(f"PROMEDIO GENERAL: {sum(total_valores) / len(total_valores):.3f}")
    print("=" * 100 + "\n")

    REPORTES_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = REPORTES_DIR / f"reporte_{timestamp}.json"
    json_path.write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reporte JSON guardado en: {json_path}")

    return json_path


async def main() -> None:
    test_cases = await generar_test_cases()
    resultados = await ejecutar_evaluaciones(test_cases)
    generar_reporte(resultados)


if __name__ == "__main__":
    asyncio.run(main())
