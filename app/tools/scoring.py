import json
from pathlib import Path
from typing import Dict

FEEDBACK_PATH = Path(__file__).resolve().parents[2] / "data" / "scoring" / "feedback.json"


def _leer_feedback() -> Dict[str, Dict[str, int]]:
    if not FEEDBACK_PATH.exists():
        return {}
    with open(FEEDBACK_PATH, encoding="utf-8") as f:
        return json.load(f)


def calcular_confianza_feedback() -> Dict[str, float]:
    """Confianza por SKU con suavizado de Laplace: sin historial arranca en 0.5, no en 0."""
    feedback = _leer_feedback()
    confianza = {}
    for sku, conteo in feedback.items():
        aciertos = conteo.get("aciertos", 0)
        fallos = conteo.get("fallos", 0)
        confianza[sku] = (aciertos + 1) / (aciertos + fallos + 2)
    return confianza


def registrar_feedback(sku: str, acierto: bool) -> None:
    """Actualiza el contador de aciertos/fallos de un SKU. Aun no esta conectado a ningun
    flujo de cierre de sesion (ver roadmap): hoy es solo el mecanismo de persistencia."""
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    feedback = _leer_feedback()
    conteo = feedback.setdefault(sku, {"aciertos": 0, "fallos": 0})
    if acierto:
        conteo["aciertos"] += 1
    else:
        conteo["fallos"] += 1
    with open(FEEDBACK_PATH, "w", encoding="utf-8") as f:
        json.dump(feedback, f, indent=2, ensure_ascii=False)
