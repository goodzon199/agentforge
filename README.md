# AgentForge — Digital Workforce OS

Операционная система для цифровых сотрудников. Не «боты», а **живые объекты**:
каждый агент — это цифровой сотрудник с идентичностью, целью, инструкциями,
памятью, инструментами, правами, моделью и статистикой.

> Sprint 1 — Foundation: запускаемая платформа. Уже работают SystemAgent (роутер),
> EmailAgent (реальная отправка писем через MailHog), SearchAgent (поиск по базе
> знаний) и передача задач между агентами.
>
> Sprint 2 (часть 1) — Диалоги: домен Customer/Conversation/ConversationMessage,
> REST API `/customers`, `/conversations`, `/messages` и автосоздание задачи
> `process_customer_message` при входящем сообщении клиента. UI: раздел «Диалоги».
>
> Sprint 2 (часть 2) — Intake: домен Vehicle/PartRequest, IntakeAgent
> (LLM + валидация + fallback на правила), REST API `/part_requests`,
> панель заявки в разделе «Диалоги».
>
> Sprint 2 (часть 3) — Поставщики: адаптеры `mock`/`csv`, `SupplierRegistry`,
> `PartsSearchService` (параллельный поиск, таймауты, дедуп), сущности
> `Supplier`, `SupplierOffer`, `SupplierSearchRun`, `SupplierSearchAttempt`,
> API `/suppliers` и `/part_requests/{id}/offers|search|search-runs`,
> таблица предложений в UI, handoff-задача `pricing_parts`.

---

## Что сделано (по порядку, последнее сверху)

1. **feat/supplier-adapters** — вертикальный срез «поиск предложений»:
   - Адаптеры поставщиков: `MockSupplierAdapter` (стабильный каталог BREMBO P06089 /
     TRW GDB2119) и `CsvSupplierAdapter` (маппинг колонок через конфиг
     `{delimiter, encoding, columns}`), `normalize_article()` (только isalnum, верхний регистр),
     `SupplierRegistry.create(type, settings)`.
   - `PartsSearchService`: параллельный вызов адаптеров через `asyncio.gather`,
     таймаут на поставщика, дедуп по (поставщик, артикул) с выбором дешёвого,
     ошибка одного поставщика не ломает весь поиск; сохраняет `SupplierSearchRun`
     + `SupplierSearchAttempt` (повторный поиск — новая run, история не удаляется).
   - `SearchAgent` — тонкий координатор: для задачи `search_parts` запускает поиск
     по активным поставщикам и создаёт handoff-задачу `pricing_parts`.
   - REST API под JWT: `GET/POST /suppliers`, `PATCH /suppliers/{id}`,
     `POST /suppliers/{id}/test`, `GET /part_requests/{id}/offers`,
     `POST /part_requests/{id}/search`, `GET /part_requests/{id}/search-runs`.
   - Frontend: кнопка «Найти предложения», счётчики, таблица Бренд/Артикул/Название/
     Закупка/Наличие/Срок/Поставщик (колонка «Закупка» — только для менеджера).
   - Alembic-миграция `c37f28d9a4b1`, застамплена в live-БД; демо-поставщик
     «АвтоТорг (демо)» (mock) создаётся при сидинге.
   - Тесты 99/99: адаптеры (8), PartsSearchService (11), suppliers API (13),
     DoD-сценарий целиком (диалог → VIN → поиск → предложения).
2. **feat/conversations-domain** (`336eb00`) — домен диалогов:
   - Модели `Customer`, `Conversation`, `ConversationMessage` (SQLAlchemy 2, UUID + timestamps).
   - Pydantic-схемы: CustomerCreate/Read, ConversationCreate/Read/Detail, MessageCreate/Read, MessageSent.
   - Сервис `ConversationService` + автосоздание задачи `process_customer_message`
     (в `input_data` — `conversation_id`, `message_id`).
   - REST API под JWT: `POST/GET /api/v1/customers`, `POST/GET /api/v1/conversations`,
     `GET /api/v1/conversations/{id}`, `POST/GET .../messages`.
   - Alembic-миграция `f4e7291ad0aa` (create_table ×3 + индексы, `down_revision=None`), застамплена в live-БД.
   - Frontend: типы в `types.ts`, двухпанельная страница `/conversations` (список +
     переписка с отправкой сообщения), пункт «Диалоги» в сайдбаре.
   - Live-проверка API: customer → conversation → message (201), возвращается `task_id`,
     задача видна в `/tasks`.
3. **3af4800** — JWT auth: логин/me, защищённое v1 API, sign-in на фронтенде.
4. **14881d6** — векторный поиск: Ollama-эмбеддинги по базе знаний.
5. **f612045** — SearchAgent: поиск по базе знаний, демо-каталог запчастей, handoff.
6. **770a02d** — Sprint 2 (Email): EmailAgent, реальный SMTP через MailHog, handoff-роутинг.
7. **e5444ff** — Sprint 1 polish: локальная Ollama-LLM, устойчивая маршрутизация, фиксы Docker.

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

Первый экран — **Вход**: админ по умолчанию `admin@agentos.local` / `admin123`
(меняется через `SEED_ADMIN_*` в `.env`). После входа — Обзор: Компании / Агенты /
Задачи / Логи / Настройки. Раздел **Диалоги** — клиенты и переписка: из UI можно
создать клиента и диалог, написать сообщение — в ответ создастся задача обработки.

## Агенты

При первом старте автоматически создаются демо-компания, **SystemAgent** и **EmailAgent**.

- **SystemAgent** — диспетчер: получает задачу и определяет нужного агента
  (детерминированные правила или LLM через Ollama).
- **EmailAgent** — специалист по почте: принимает задачу от SystemAgent,
  достаёт получателя/тему/текст и отправляет письмо по SMTP (в демо — MailHog,
  UI на http://localhost:8025). Получателя можно указать в поле «Кому (email)».
- **SearchAgent** — специалист по поиску: ищет по базе знаний компании
  (**векторный поиск** через Ollama-эмбеддинги + fallback на ключевой матч;
  демо-каталог запчастей). Внешние каталоги подключаются позже.

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
.venv\Scripts\python.exe -m pytest     # 99 тестов: агенты, оркестратор, API, память, email, поиск, эмбеддинги, auth, диалоги, intake, поставщики
```

## Структура

```
agentforge/
├── backend/
│   ├── app/
│   │   ├── api/v1/        # REST API: companies, agents, tasks, logs, settings, dashboard, customers, conversations, part_requests, suppliers
│   │   ├── core/          # config, database, redis, seeding
│   │   ├── agents/        # BaseAgent, SystemAgent, EmailAgent, SearchAgent, IntakeAgent, реестр
│   │   ├── orchestrator/  # сердце платформы: маршрутизация, handoff, очередь, воркеры
│   │   ├── tools/         # каждый инструмент — отдельный модуль (email, search, http)
│   │   ├── suppliers/     # адаптеры поставщиков: base, mock, csv, normalize, registry
│   │   ├── models/        # Agent, Company, Task, Memory, Customer, Conversation, PartRequest, Supplier, SupplierOffer, SupplierSearch*
│   │   ├── services/      # сервисный слой (в т.ч. PartsSearchService, SupplierService)
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
| Поиск     | Ollama-эмбеддинги (nomic-embed-text) + vector search |
| Auth      | JWT (HS256, PBKDF2-пароли)                        |

Подробнее об архитектуре: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
