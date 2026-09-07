from functools import lru_cache
from typing import List, Optional

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

    # --- Langfuse (self-hosted, observabilidad) ---
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None

    # --- Evals (juez LLM-as-judge para evals/, usa el mismo LLM_PROVIDER) ---
    # Si no se define, el juez usa el mismo modelo que el agente en produccion. Se puede
    # apuntar a un modelo mas grande solo para evaluar (ej. un Ollama local mas capaz)
    # sin cambiar el modelo que sirve el chat real.
    eval_judge_model: Optional[str] = None

    @property
    def allowed_origins_list(self) -> List[str]:
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
