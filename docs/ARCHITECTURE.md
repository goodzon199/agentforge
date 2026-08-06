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
   3. результат: {response, routing_decision, handoff_agent}
   4. статус=completed, output_data, события логов
   5. память: agent.remember(...)  (short memory)
   6. статистика агента: tasks_total / completed / success_rate
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

## Инструменты

Каждый инструмент — отдельный модуль в `app/tools/builtin/`:

- `search_tool.py` — контракт поиска (query/filters/limit). В Sprint 1 возвращает
  сигнал `handoff_required: SearchAgent`.
- `email_tool.py` — контракт отправки письма.
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

- Специализированные агенты: SearchAgent, EmailAgent (реальные провайдеры).
- Действительная передача задач между агентами (handoff через оркестратор).
- Эмбеддинги + векторный поиск по Knowledge Base.
- Авторизация: JWT, пользователи, права компаний.
- Метрики и дашборд «цифровой штат».
