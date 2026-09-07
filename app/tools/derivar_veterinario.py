import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models.tools import DerivacionVeterinario

DERIVACIONES_DIR = Path(__file__).resolve().parents[2] / "data" / "derivaciones"
MAX_REINTENTOS = 2


def derivar_veterinario(motivo: str, session_id: str) -> DerivacionVeterinario:
    """Persiste DER-<id>.json y verifica que el archivo realmente exista, reintentando
    hasta 2 veces. El session_id lo inyecta Python (el caller), nunca el LLM."""
    DERIVACIONES_DIR.mkdir(parents=True, exist_ok=True)

    derivacion_id = f"DER-{uuid.uuid4().hex[:8]}"
    registro = DerivacionVeterinario(
        id=derivacion_id,
        session_id=session_id,
        motivo=motivo,
        fecha=datetime.now(timezone.utc).isoformat(),
    )
    path = DERIVACIONES_DIR / f"{derivacion_id}.json"

    for intento in range(MAX_REINTENTOS + 1):
        path.write_text(registro.model_dump_json(indent=2), encoding="utf-8")
        if path.exists():
            return registro

    raise RuntimeError(f"No se pudo verificar la escritura de {path} tras {MAX_REINTENTOS} reintentos")
