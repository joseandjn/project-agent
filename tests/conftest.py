import pytest

import app.observability.langfuse as obs
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _sin_langfuse(monkeypatch):
    """Los tests nunca envian trazas a Langfuse Cloud, aunque el .env tenga
    LANGFUSE_ENABLED=true. test_observabilidad.py usa su propio cliente con un exportador en
    memoria. Los rate limits tambien se apagan (los tests hacen muchos requests seguidos)."""
    monkeypatch.setattr(get_settings(), "langfuse_enabled", False)
    # Rate limits apagados salvo en tests/integration/test_rate_limit.py, que los prende.
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", False)
    monkeypatch.setattr(obs, "_cliente", None)
    monkeypatch.setattr(obs, "_inicializado", False)
