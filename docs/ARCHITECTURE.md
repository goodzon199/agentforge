# Архитектура AgentForge

## Принципы

1. **Агент — живой объект, а не чат-бот.** Агент — это цифровой сотрудник: строка в БД
   с идентичностью, поведением, правами, моделью и статистикой.
2. **Инструменты — отдельные модули.** Агент не знает, как работает инструмент.
   Он вызывает функцию по контракту (`name`, `description`, `input_schema`, `run`).
3. **Оркестратор — единственное сердце.** Он владеет маршрутизацией, очередью,
   воркерами и статистикой. Агенты не общаются напрямую.
4. **Память многоуровневая.** Short → Long → Knowledge Base → Logs. Это фундамент
   для «обучения» агентов на собственной работе.
5. **LLM — сменный провайдер.** OpenAI и любые совместимые API (Azure, Ollama).
   Без ключа платформа работает в детерминированном режиме.

## Поток задачи

```
POST /api/v1/tasks
   │  TaskService.create()  -> Task(status=pending)
   ▼
Orchestrator.submit()
   ├─ Redis доступен?  -> очередь "agentos:tasks" -> воркеры (async)
   └─ Redis недоступен -> синхронный process() (inline)
        │
        ▼
Orchestrator.process(task)
   1. статус=running, started_at, событие «получена агентом»
   2. SystemAgent.execute(objective)
        - LLM доступен? -> классификация маршрута через LLM
        - иначе        -> детерминированные правила (search/email/...)
   3. handoff? -> задача передаётся специализированному агенту
        EmailAgent.execute(objective, input_data) -> email_tool -> SMTP
   4. результат: {response, routing_decision, handoff_agent}
   5. статус=completed, output_data, события логов
   6. память: agent.remember(...)  (short memory)
   7. статистика агента-исполнителя: tasks_total / completed / success_rate
```

## Модель «цифровой сотрудник» (Agent)

| Поле            | Назначение                                   |
|-----------------|----------------------------------------------|
| id              | UUID                                         |
| name, slug      | идентичность                                 |
| role            | должность                                    |
| goal            | цель (зачем существует)                      |
| description     | описание                                     |
| instructions    | инструкции поведения                         |
| type            | system / general / specialized               |
| tools           | связи AgentTool (что умеет)                  |
| permissions     | JSON-права                                   |
| model           | LLM-модель                                   |
| temperature     | температура                                  |
| status          | idle/active/paused/disabled/failed           |
| tasks_total     | статистика                                   |
| tasks_completed | статистика                                   |
| avg_success_rate| статистика (для оценки «обучения»)           |

## Агенты

- **SystemAgent** (`system-agent`) — диспетчер/роутер. Возвращает
  `handoff_agent` (например `EmailAgent`), если задача требует специалиста.
- **EmailAgent** (`email-agent`) — принимает задачу после handoff, извлекает
  `to`/`subject`/`body` из `input_data` (fallback: `EMAIL_DEFAULT_TO`, objective)
  и отправляет письмо через `email_tool`.
- **SearchAgent** (`search-agent`) — ищет по базе знаний компании
  (`KnowledgeEntry`). Сначала **векторный поиск** (эмбеддинги через Ollama,
  cosine similarity), при недоступности — case-insensitive fallback по
  title/content/tags. Пусто → ответ «ничего не найдено».
  Внешние каталоги (Rossko, Armtek и т.п.) подключаются через `search_tool`.

Маршрутизация SystemAgent по handoff-имени в тип агента — в `agents/registry.py`
(`HANDOFF_TO_TYPE`), слот для записи в БД — slug `<type>-agent`.

## Передача задач между агентами (handoff)

`Orchestrator.process()` после ответа SystemAgent вызывает
`agent_registry.resolve_handoff(decision.handoff_agent)`:

```
SystemAgent -> (needs_agent: "EmailAgent")
             -> resolve_handoff("EmailAgent") == "email"
             -> запись агента по slug "email-agent"
             -> EmailAgent.execute(objective, input_data)
             -> финальный ответ/события/статистика от исполнителя
```

Если handoff-агент не существует в реестре (например `SearchAgent` пока не
реализован) — задача завершается ответом SystemAgent без передачи.

## Память

```
Agent
  │
  ├── ShortMemory   — рабочий контекст, TTL, «что было недавно»
  ├── LongMemory    — консолидированные уроки (confidence, source_task)
  ├── KnowledgeEntry— база знаний компании (поиск, embedding-ready)
  └── TaskEvent     — журнал событий (логи)
```

MemoryService собирает контекст агента через `build_context()` — это вход
для следующего промпта.

### Векторный поиск (эмбеддинги)

- Модель эмбеддингов — `EMBEDDING_MODEL` (Ollama, по умолчанию `nomic-embed-text`,
  768 измерений). Пусто → векторный поиск выключен.
- `MemoryService.embed_missing(company_id)` — заполняет пустые `embedding`
  у `KnowledgeEntry` (текст = title + content + tags).
- `MemoryService.vector_search(company_id, query)` — эмбеддит запрос и считает
  `cosine_similarity` по всем записям, возвращает ранжированные `(entry, score)`.
- SearchAgent: векторный поиск → fallback на ключевой матч.
- Векторы хранятся в JSON-поле `KnowledgeEntry.embedding` (без внешней векторной
  БД — для демо достаточно; при масштабировании — pgvector/Milvus).

## Инструменты

Каждый инструмент — отдельный модуль в `app/tools/builtin/`:

- `email_tool.py` — реальная отправка по SMTP (`smtplib`, MIME multipart,
  версия 2.0.0). В демо-стеке `SMTP_HOST=mailhog` — письма видны в UI :8025.
  При ошибке SMTP возвращает `ToolResult(ok=False, error=...)`, агент не падает.
- `search_tool.py` — контракт поиска (query/filters/limit). Провайдер
  подключается позже; сейчас SearchAgent ищет по базе знаний напрямую.
- `http_tool.py` — общий HTTP-контракт для внешних API (Rossko, Armtek, CRM и др.).

Добавление инструмента = новый класс в `builtin/` + регистрация в `ToolRegistry`.
Агенты получают инструменты через связи `AgentTool` (что подключено, включено ли).

## Оркестратор

- `Orchestrator.submit()` — принимает задачу, ставит в очередь или выполняет inline.
- `QueueWorker` — N потоков-потребителей Redis-очереди. Масштабирование:
  увеличить `ORCHESTRATOR_WORKERS` / поднять больше контейнеров.
- Контракты сообщений: `TaskMessage`, `ResultMessage`.

Это архитектурная заготовка для «1000 агентов одновременно»: очередь — точка
горизонтального масштабирования.

## LLM

- `LLMClient` — фасад. `available=False` → детерминированный режим.
- `providers/openai_provider.py` — OpenAI / Azure / Ollama через единый `/v1`.
- Маршрутизация SystemAgent: JSON-классификация `{needs_agent, reason, answer}`.

## Авторизация (JWT)

- `POST /api/v1/auth/login` (email+password) → `{access_token, user}`.
- `GET /api/v1/auth/me` — текущий пользователь (Bearer-токен).
- Пароли: PBKDF2-HMAC-SHA256 (100k итераций, соль на пользователя) — `app/core/security.py`.
- Токены: PyJWT, HS256, claims `sub/iss/iat/exp`; `JWT_SECRET` обязателен в production.
- Все ресурсные роутеры `/api/v1/*` защищены зависимостью `get_current_user`
  (`app/api/deps.py`); открыты `/health`, `/` и `/auth/login`.
- Демо-админ сидится автоматически (`SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD`).
- Frontend: страница `/login`, токен в localStorage, Bearer-заголовок в `api.ts`,
  guard в `AppShell`, logout в сайдбаре.

## Миграции (Alembic)

Dev-бутстрап: `Base.metadata.create_all()` при старте (см. `app/main.py`).
Production: `alembic upgrade head`.

Генерация первой миграции после подъёма БД:

```bash
cd backend
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

## Планы (Sprint 2+)

- **SearchAgent** — подключение реального поискового провайдера (каталог запчастей
  Rossko/Armtek, веб-поиск) через `search_tool`/`http_tool`.
- **Эмбеддинги** — переход на pgvector/Milvus при росте базы знаний.
- **EmailAgent** — расширение: шаблоны писем, вложения, несколько SMTP-профилей.
- **RBAC** — роли и права компаний (сейчас superuser/обычный), разграничение данных.
- Метрики и дашборд «цифровой штат».
