from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "AgentForge"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    debug: bool = True
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+psycopg://agentos:agentos_secret@localhost:5432/agentos"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True

    # LLM
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    default_agent_model: str = "gpt-4o-mini"
    default_agent_temperature: float = 0.3

    # Orchestrator
    orchestrator_workers: int = 4
    task_queue_name: str = "agentos:tasks"

    # E-mail (SMTP)
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "agentforge@agentos.local"
    email_default_to: str = "demo@agentos.local"

    @property
    def is_llm_available(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
