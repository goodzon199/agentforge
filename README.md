# AgentForge — Digital Workforce OS

Операционная система для цифровых сотрудников. Не «боты», а **живые объекты**:
каждый агент — это цифровой сотрудник с идентичностью, целью, инструкциями,
памятью, инструментами, правами, моделью и статистикой.

> Sprint 1 — Foundation. Цель этого этапа: получить **запускаемую платформу**, а не набор файлов.

---

## Быстрый старт (Docker)

Предварительно: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(Windows: включить WSL2) + Git.

```bash
# 1. Скопировать окружение (по умолчанию LLM — локальная Ollama, ключ не нужен)
cp .env.example .env

# 2. Поднять стек: PostgreSQL + Redis + Ollama + backend + frontend
#    Первый запуск скачает модель LLM в Ollama (~2 ГБ) и соберёт образы.
docker compose up --build
```

После запуска:

- Frontend (AgentForge UI): http://localhost:3000
- Backend API: http://localhost:8000 — Swagger: http://localhost:8000/docs
- PostgreSQL: localhost:5432, Redis: localhost:6379

Первый экран — **Обзор**: Компании / Агенты / Задачи / Логи / Настройки.

## Первый агент

При первом старте автоматически создаются демо-компания и **SystemAgent**.

SystemAgent умеет одно: получает задачу и определяет нужного агента.

```
Задача: "Найди тормозные колодки"
Ответ:  "Для выполнения этой задачи нужен SearchAgent."
```

Проверьте прямо в UI: **Задачи → «Новая задача»** → введите текст → результат и
журнал событий появятся мгновенно. Работает даже без ключа OpenAI —
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
.venv\Scripts\python.exe -m pytest     # 12 тестов: агенты, оркестратор, API, память
```

## Структура

```
agentforge/
├── backend/
│   ├── app/
│   │   ├── api/v1/        # REST API: companies, agents, tasks, logs, settings, dashboard
│   │   ├── core/          # config, database, redis, seeding
│   │   ├── agents/        # BaseAgent, SystemAgent, реестр агентов
│   │   ├── orchestrator/  # сердце платформы: маршрутизация, очередь, воркеры
│   │   ├── tools/         # каждый инструмент — отдельный модуль (search, email, http)
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
└── docker-compose.yml
```

## Стек

| Слой      | Технологии                                        |
|-----------|---------------------------------------------------|
| Backend   | Python 3.12, FastAPI, SQLAlchemy 2, Alembic       |
| Данные    | PostgreSQL 16, Redis 7                            |
| Frontend  | Next.js 15, TypeScript, Tailwind CSS              |
| Инфра     | Docker Compose                                    |
| LLM       | OpenAI (и совместимые: Azure, Ollama)             |

Подробнее об архитектуре: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
