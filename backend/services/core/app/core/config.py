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

    # Inter-service contract (sprint 5.0): core never imports the automotive
    # domain; autoparts-service is reached over its internal HTTP endpoint.
    autoparts_internal_url: str = "http://autoparts-api:8001"
    # Shared token both services require on /internal/* routes.
    internal_api_token: str = "dev-internal-token-change-me"

    # Database
    database_url: str = "postgresql+psycopg://agentos:agentos_secret@localhost:5432/agentos"

    # Schema management. Development defaults to True (fast first-run bootstrap);
    # production must set it to False so schema is managed exclusively by Alembic.
    # When False, startup verifies the Alembic revision and fails fast if the
    # database is behind `head`.
    db_auto_create: bool = True

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

    # Pilot analytics + SLA (sprint 3.1): target duration per pipeline stage
    # (seconds) used by the dashboard to measure the share of tasks within SLA.
    # Stages are task.objective names; the task records themselves are platform
    # entities, so the metric stays in core.
    pipeline_sla_seconds: dict[str, float] = {
        "process_customer_message": 5.0,
        "search_parts": 15.0,
        "pricing_parts": 2.0,
        "sales_draft": 5.0,
    }
    # Watchdog: задача, зависшая в статусе running дольше этого срока,
    # помечается failed (task_timeout), чтобы ничего не висело вечно.
    task_max_running_seconds: float = 60.0

    # Reliability layer (sprint 3.5)
    # Task-level retry: transient failures requeue up to this many times
    # before the task lands in the dead-letter queue.
    task_max_retries: int = 2
    # Replay chain guard: how many generations of "Повторить" a task may spawn.
    task_max_replay_depth: int = 5
    dlq_queue_name: str = "agentos:tasks:dead"

    # Unified RetryPolicy (transient-only, exponential backoff + jitter).
    retry_max_attempts: int = 2
    retry_initial_delay: float = 0.5
    retry_max_delay: float = 3.0
    # Per-service overrides, e.g. {"rossko": {"max_attempts": 3, "initial_delay": 1.0}}.
    retry_policies: dict[str, dict] = {}

    # Circuit breakers (ollama / rossko / smtp / http).
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 30.0
    circuit_breaker_half_open_max_calls: int = 1
    # Per-service overrides, e.g. {"smtp": {"failure_threshold": 3}}.
    circuit_breaker_overrides: dict[str, dict] = {}

    # Distributed circuit breaker (sprint 3.5.1): state lives in Redis so all
    # worker processes share one view. Keys: agentos:breaker:<name> (state)
    # and agentos:breaker:<name>:probe (HALF_OPEN distributed lock).
    breaker_redis_prefix: str = "agentos:breaker"
    # How long a breaker state survives untouched (after that it resets to
    # closed — the cluster was idle / all workers died).
    breaker_state_ttl_seconds: int = 3600
    # Distributed lock TTL for the single HALF_OPEN probe call. Should cover
    # the slowest provider call plus a little slack.
    breaker_probe_lock_ttl_seconds: float = 20.0

    # E-mail (SMTP)
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "agentforge@agentos.local"
    smtp_timeout: float = 10.0
    email_default_to: str = "demo@agentos.local"

    # Auth (JWT)
    # В production обязательно переопределите JWT_SECRET (>= 32 байта).
    # The dev default is rejected in production (fail-fast at startup).
    jwt_secret: str = "dev-only-agentforge-jwt-secret-change-me-9f3a1c"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 дней
    jwt_issuer: str = "agentforge"

    # Bootstrap admin (создаётся при первом сидинге ТОЛЬКО если задан пароль).
    # Пароль обязателен в production (fail-fast при старте) и не должен быть
    # well-known значением вроде admin123. Пустая строка = админ не создаётся.
    seed_admin_email: str = "admin@agentos.local"
    seed_admin_password: str = ""
    seed_admin_name: str = "Администратор"

    # --- Security / production hardening (sprint 3.7) ----------------------
    # Minimum password length enforced on user creation / password change.
    min_password_length: int = 8
    # CORS: comma-separated list of allowed origins. "*" is refused together
    # with credentials (insecure); an explicit list is expected in production.
    cors_origins: str = "http://localhost:3000"
    # Maximum accepted request body size (bytes). Larger bodies get 413.
    max_request_body_bytes: int = 1_048_576  # 1 MiB
    # Comma-separated Content-Security-Policy fragments applied in production
    # (left empty in development so Swagger UI keeps working).
    security_csp: str = "default-src 'self'"

    # Login throttle (brute-force protection).
    login_rate_per_minute: int = 20
    login_rate_window_seconds: int = 60
    login_failures_before_lock: int = 5
    login_lock_seconds: int = 900  # 15 минут

    # Public webchat rate limits (abuse protection).
    chat_rate_per_minute: int = 30
    chat_rate_per_day: int = 300
    chat_rate_window_seconds: int = 60

    # Business rate limits (sprint 3.7.1): per-user quotas applied to the
    # authenticated API, keyed by company_id:user_id. Categories are derived
    # from the request path/method (see category_for in core.business_rate_limit).
    # PUBLIC is keyed by client IP and guards the login + public chat endpoints.
    # Each entry: {"limit": calls, "window": seconds}. Values are overridable
    # via env (JSON, e.g. BUSINESS_RATE_LIMITS={"ai":{"limit":10,...}}).
    business_rate_limits: dict[str, dict] = {
        "read": {"limit": 300, "window": 60},
        "write": {"limit": 120, "window": 60},
        "expensive": {"limit": 30, "window": 60},
        "ai": {"limit": 20, "window": 60},
        "public": {"limit": 120, "window": 60},
    }

    # Shadow Mode (sprint 3.8.1): how many shadow comparisons the pilot will
    # accumulate before automatic shadow tracking stops (the first N real
    # requests are measured against a human selection, then automation can be
    # turned on deliberately).
    shadow_mode_limit: int = 100

    # Pilot 500 (sprint 3.9): the pilot is judged on its first N real requests.
    pilot_target_requests: int = 500
    # Estimated infra (GPU/DB/Rabbit/VM) cost attributed to a single request,
    # RUB. Added to the measured LLM cost to report total cost/request. The
    # LLM cost itself is computed from LLMUsage rows (tokens * price).
    infra_cost_per_request_rub: float = 0.0

    @property
    def is_llm_available(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
