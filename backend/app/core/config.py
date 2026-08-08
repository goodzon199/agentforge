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

    # LLM reliability (hotfix 3.4.1): one LLM operation must stay well under
    # the 60s task watchdog, so a hung provider fails fast instead of blocking
    # a worker thread for the SDK default (10 min).
    llm_connect_timeout: float = 5.0
    llm_read_timeout: float = 25.0
    llm_write_timeout: float = 10.0
    llm_pool_timeout: float = 5.0
    # Attempts per logical call (1 = no retry). Transient errors only.
    llm_max_attempts: int = 2
    llm_retry_initial_delay: float = 0.5
    llm_retry_max_delay: float = 3.0

    # Embeddings (vector search over the Knowledge Base)
    # Модель эмбеддингов (Ollama: nomic-embed-text / mxbai-embed-large и т.п.).
    # Пустая строка = векторный поиск выключен, работает ключевой fallback.
    embedding_model: str = ""
    embedding_top_k: int = 5

    # LLM cost estimation (sprint 3.2): RUB per 1M tokens, per model.
    # Models not listed are treated as free (e.g. local Ollama). Used for
    # cost/task in the agent-quality report.
    llm_price_rub_per_1m_input: dict[str, float] = {
        "gpt-4o-mini": 13.5,
    }
    llm_price_rub_per_1m_output: dict[str, float] = {
        "gpt-4o-mini": 54.0,
    }

    # Orchestrator
    orchestrator_workers: int = 4
    task_queue_name: str = "agentos:tasks"

    # Supplier search (sprint 2.3)
    supplier_search_timeout: float = 15.0

    # Pricing engine (sprint 2.4)
    # Наценка по умолчанию к закупочной цене поставщика (проценты). Может быть
    # переопределена на уровне компании в settings["pricing"]["margin_percent"].
    pricing_margin_percent: float = 30.0
    pricing_currency: str = "RUB"

    # Sales + approval (sprint 2.5)
    # Срок жизни запроса на согласование: после expiry approve/reject нельзя.
    approval_ttl_hours: float = 24.0

    # Pilot analytics + SLA (sprint 3.1)
    # Целевое время на каждый этап pipeline (секунды). Используется в дашборде
    # аналитики для доли задач, укладывающихся в SLA.
    pipeline_sla_seconds: dict[str, float] = {
        "process_customer_message": 5.0,
        "search_parts": 15.0,
        "pricing_parts": 2.0,
        "sales_draft": 5.0,
    }
    # Watchdog: задача, зависшая в статусе running дольше этого срока,
    # помечается failed (task_timeout), чтобы ничего не висело вечно.
    task_max_running_seconds: float = 60.0
    # Аналогично для поискового запуска (supplier_failed).
    search_run_max_running_seconds: float = 60.0

    # E-mail (SMTP)
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "agentforge@agentos.local"
    email_default_to: str = "demo@agentos.local"

    # Auth (JWT)
    # В production обязательно переопределите JWT_SECRET (>= 32 байта).
    jwt_secret: str = "dev-only-agentforge-jwt-secret-change-me-9f3a1c"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 дней
    jwt_issuer: str = "agentforge"

    # Demo admin (создаётся при первом сидинге)
    seed_admin_email: str = "admin@agentos.local"
    seed_admin_password: str = "admin123"
    seed_admin_name: str = "Администратор"

    @property
    def is_llm_available(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
