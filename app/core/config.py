from functools import lru_cache
from typing import List, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "VethisAgent"
    environment: str = "development"
    allowed_origins: str = "*"

    # --- Proveedor de LLM: "ollama" (self-hosted), "openai" o "anthropic" ---
    llm_provider: str = "ollama"

    # --- Ollama (LLM + embeddings, self-hosted) ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.1:8b"
    ollama_embedding_model: str = "nomic-embed-text"

    # --- Embeddings de buscar_alimentos: "ollama" (local) u "openai" (sin Ollama, p. ej. en la
    # nube; usa OPENAI_API_KEY). Independiente de LLM_PROVIDER.
    embedding_provider: str = "ollama"
    openai_embedding_model: str = "text-embedding-3-small"

    # --- OpenAI (opcional, solo si llm_provider == "openai") ---
    openai_api_key: Optional[str] = None
    openai_chat_model: str = "gpt-4o-mini"

    # --- Anthropic (opcional, solo si llm_provider == "anthropic") ---
    anthropic_api_key: Optional[str] = None
    anthropic_chat_model: str = "claude-sonnet-5"

    # --- PostgreSQL + pgvector ---
    postgres_dsn: str = "postgresql+asyncpg://vethis:vethis@localhost:5432/vethis"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"
    session_ttl_seconds: int = 1800  # 30 min, igual al TTL de checkpoints del blueprint

    # --- Autenticacion: JWT propio, agnostico a la tienda (docs/memoria_largo_plazo.md) ---
    # Sin JWT_SECRET la app no arranca (ver lifespan en main.py).
    jwt_secret: Optional[str] = None
    jwt_ttl_seconds: int = 3600  # 1 h; se renueva con POST /api/v1/auth/refresh

    # --- Memoria de largo plazo (perfil de cliente en Postgres, docs/memoria_largo_plazo.md) ---
    memoria_consolidar_cada_n_turnos: int = 5
    # Una sesion inactiva se consolida antes de que Redis borre su checkpoint: tiene que ser
    # menor que SESSION_TTL_SECONDS (se valida abajo).
    memoria_inactividad_segundos: int = 1500
    memoria_sweep_intervalo_segundos: int = 60
    # Modelo del extractor (mismo LLM_PROVIDER). Vacio => el mismo modelo del chat. Se elige
    # con evals/run_evals_memoria.py.
    memoria_model: Optional[str] = None

    # --- Control de tema (app/guardrails/tema.py): clasifica cada mensaje antes del agente y
    # responde con una plantilla si esta fuera del tema (salud humana, malestar emocional...).
    tema_guard_enabled: bool = True
    tema_model: Optional[str] = None  # vacio => el modelo del chat
    # Lineas de ayuda que se mencionan en las respuestas de malestar emocional y riesgo.
    # Valores para Peru: verificar que sigan vigentes antes de produccion.
    tema_ayuda_salud_mental: str = "En Perú puedes llamar gratis a la Línea 113, opción 5 (salud mental del MINSA)."
    tema_ayuda_emergencia: str = "Si alguien está en peligro inmediato, llama al 106 (SAMU) o al 105 (Policía)."

    # --- Rate limits (docs/rate_limits.md). Por sesion, cliente y tienda (del JWT); por IP solo
    # los intentos con API key invalida. 0 desactiva una regla.
    rate_limit_enabled: bool = True
    rl_chat_sesion_por_minuto: int = 10
    rl_chat_cliente_por_minuto: int = 20
    rl_chat_tienda_por_minuto: int = 300
    rl_chat_tienda_por_dia: int = 10000  # tope de costo diario de LLM por tienda
    rl_token_tienda_por_minuto: int = 120  # sesiones nuevas por tienda
    rl_api_key_invalida_ip_por_minuto: int = 10
    rl_refresh_sesion_por_minuto: int = 10
    rl_feedback_sesion_por_minuto: int = 30
    rl_memoria_cliente_por_minuto: int = 20

    # --- Feedback del cliente (docs/feedback_cliente.md) ---
    # Cuanto tiempo despues de una respuesta se la puede votar.
    feedback_ventana_segundos: int = 86400

    # --- Langfuse Cloud (trazas, docs/observabilidad_langfuse.md) ---
    # Apagado por defecto (tests, evals): se prende con LANGFUSE_ENABLED=true + las dos claves.
    langfuse_enabled: bool = False
    # Region del proyecto: EU https://cloud.langfuse.com, US https://us.cloud.langfuse.com
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None
    langfuse_sample_rate: float = 1.0  # fraccion de trazas que se envian (0.0 a 1.0)

    # --- Evals (juez LLM-as-judge para evals/, usa el mismo LLM_PROVIDER) ---
    # Si no se define, el juez usa el mismo modelo que el agente en produccion. Se puede
    # apuntar a un modelo mas grande solo para evaluar (ej. un Ollama local mas capaz)
    # sin cambiar el modelo que sirve el chat real.
    eval_judge_model: Optional[str] = None

    @model_validator(mode="after")
    def _inactividad_menor_que_ttl(self) -> "Settings":
        if self.memoria_inactividad_segundos >= self.session_ttl_seconds:
            raise ValueError(
                "MEMORIA_INACTIVIDAD_SEGUNDOS debe ser menor que SESSION_TTL_SECONDS: si no, Redis "
                "borra la sesion antes de que se consolide"
            )
        return self

    @property
    def allowed_origins_list(self) -> List[str]:
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
