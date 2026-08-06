# AgentForge — Digital Workforce OS

Операционная система для цифровых сотрудников. Не «боты», а **живые объекты**:
каждый агент — это цифровой сотрудник с идентичностью, целью, инструкциями,
памятью, инструментами, правами, моделью и статистикой.

> Sprint 1 — Foundation: запускаемая платформа. Уже работают SystemAgent (роутер),
> EmailAgent (реальная отправка писем через MailHog), SearchAgent (поиск по базе
> знаний) и передача задач между агентами.

---

## Быстрый старт (Docker)

Предварительно: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(Windows: включить WSL2) + Git.

```bash
# 1. Скопировать окружение (по умолчанию LLM — локальная Ollama, ключ не нужен)
cp .env.example .env

# 2. Поднять стек: PostgreSQL + Redis + MailHog + Ollama + backend + frontend
#    Первый запуск скачает модель LLM в Ollama (~2 ГБ) и соберёт образы.
docker compose up --build
```

После запуска:

- Frontend (AgentForge UI): http://localhost:3000
- Backend API: http://localhost:8000 — Swagger: http://localhost:8000/docs
- **MailHog** (входящие письма EmailAgent): http://localhost:8025
- PostgreSQL: localhost:5432, Redis: localhost:6379

Первый экран — **Обзор**: Компании / Агенты / Задачи / Логи / Настройки.

## Агенты

При первом старте автоматически создаются демо-компания, **SystemAgent** и **EmailAgent**.

- **SystemAgent** — диспетчер: получает задачу и определяет нужного агента
  (детерминированные правила или LLM через Ollama).
- **EmailAgent** — специалист по почте: принимает задачу от SystemAgent,
  достаёт получателя/тему/текст и отправляет письмо по SMTP (в демо — MailHog,
  UI на http://localhost:8025). Получателя можно указать в поле «Кому (email)».
- **SearchAgent** — специалист по поиску: ищет по базе знаний компании
  (демо-каталог запчастей). Внешние каталоги подключаются позже.

```
Задача: "Найди тормозные колодки"
Ответ:  "По запросу «тормозные колодки» найдено записей: 1
          • Тормозные колодки TRW GDB3410 (передние) — ..."

Задача: "Отправь письмо клиенту: напомни про встречу завтра в 10:00"
Письмо:  SystemAgent -> EmailAgent -> SMTP/MailHog -> http://localhost:8025
```

Проверьте прямо в UI: **Задачи → «Новая задача»** → введите текст → результат,
журнал событий и письмо в MailHog. Работает даже без ключа OpenAI —
детерминированный режим маршрутизации.

## Локальная разработка (без Docker)

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env        # укажите DATABASE_URL (Postgres или SQLite)
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev                   # http://localhost:3000
```

## Тесты

```bash
cd backend
.venv\Scripts\python.exe -m pytest     # 21 тест: агенты, оркестратор, API, память, email, поиск
```

## Структура

```
agentforge/
├── backend/
│   ├── app/
│   │   ├── api/v1/        # REST API: companies, agents, tasks, logs, settings, dashboard
│   │   ├── core/          # config, database, redis, seeding
│   │   ├── agents/        # BaseAgent, SystemAgent, EmailAgent, SearchAgent, реестр
│   │   ├── orchestrator/  # сердце платформы: маршрутизация, handoff, очередь, воркеры
│   │   ├── tools/         # каждый инструмент — отдельный модуль (email, search, http)
│   │   ├── models/        # Agent (цифровой сотрудник), Company, Task, Memory
│   │   ├── services/      # сервисный слой
│   │   ├── memory/        # Short / Long / Knowledge Base
│   │   ├── llm/           # провайдеры LLM (OpenAI-совместимые)
│   │   └── main.py
│   ├── alembic/           # миграции
│   └── tests/
├── frontend/              # Next.js + TypeScript + Tailwind
├── docker/
├── docs/
└── docker-compose.yml     # db, redis, mailhog, ollama, backend, frontend
```

## Стек

| Слой      | Технологии                                        |
|-----------|---------------------------------------------------|
| Backend   | Python 3.12, FastAPI, SQLAlchemy 2, Alembic       |
| Данные    | PostgreSQL 16, Redis 7                            |
| Почта     | SMTP (демо: MailHog, UI :8025)                    |
| Frontend  | Next.js 15, TypeScript, Tailwind CSS              |
| Инфра     | Docker Compose                                    |
| LLM       | OpenAI (и совместимые: Azure, Ollama)             |

Подробнее об архитектуре: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
