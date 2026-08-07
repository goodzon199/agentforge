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
>
> Sprint 2 (часть 4) — Цены: `PricingService` (наценка к закупочной цене,
> per-company margin из `company.settings`), агент `PricingAgent`,
> столбцы `customer_price`/`total_price`/`margin_percent` у офферов,
> REST API `/part_requests/{id}/price|quote`, блок «Лучшее предложение»
> с ценой для менеджера в UI.
>
> Sprint 2 (часть 5) — Согласование продажи: `SalesAgent` формулирует
> предложение по готовой квоте, `QuoteGuard` детерминированно проверяет текст
> (цены, валюта, артикулы, срок, наличие), отправка клиенту — MEDIUM-риск и
> всегда идёт через `ApprovalRequest` менеджера; сущности `Quote`,
> `AgentAction`, `AgentFeedback`, модель рисков `core/risk.py`, UI-блок
> «Предложение клиенту» с approve/reject.

---

## Что сделано (по порядку, последнее сверху)

1. **feat/sales-approval** — вертикальный срез «предложение клиенту с согласованием»:
   - Модель рисков `core/risk.py`: `ACTION_RISK` — подготовка черновика (low, агент сам),
     отправка клиенту / создание CRM-записи / письмо (medium → всегда approval),
     изменение цены / скидка / возврат / оплата (high, только человек).
   - `SalesAgent` — только формулирует сообщение по готовой квоте (никаких поисков и
     цен), на фактах квоты; `QuoteGuard` детерминированно проверяет текст: цена только
     из квоты (закупочная не протечёт), валюта `RUB`, артикул/бренд/срок/наличие —
     только из квоты. При блоке текст заменяется системным шаблоном.
   - Сущности: `Quote` (статусы draft → pending_approval → sent, снимок офферов,
     `ai_draft`/`manager_edited`/`final_message`, `guard_status`), `ApprovalRequest`
     (pending/approved/rejected/expired, `approval_ttl_hours=24`), `AgentAction`
     (аудит: кто/что/риск/idempotency_key), `AgentFeedback` (approved_unchanged /
     approved_edited / rejected); `users.company_id` для scoping по компаниям.
   - После pricing автоматически создаётся Quote + handoff-задача `sales_draft`
     (SalesAgent формирует черновик). Отправка клиенту — MEDIUM-риск, всегда
     `ApprovalRequest`; QuoteGuard перепроверяется при send **и** при approve;
     идемпотентность по ключу `send_quote:{quote_id}:{conversation_id}`.
   - REST API под JWT: `GET /quotes/{id}/sales-draft`, `POST /quotes/{id}/prepare|send|reject`,
     `GET /approvals`, `POST /approvals/{id}/approve|reject`, `GET /actions`. Всё scoped
     по `user.company_id` (403 чужой компании).
   - Frontend: блок «Предложение клиенту» в панели заявки — текст-черновик (можно
     править), бейдж проверки QuoteGuard, «Отправить на согласование», для менеджера
     «Одобрить и отправить клиенту» / «Отклонить», статус и срок согласования.
   - Alembic-миграция `a1b2c3d4e5f6` (4 таблицы + `users.company_id`), применена в
     live-БД; сидинг создаёт агента `sales-agent` и привязывает админа к демо-компании.
   - Тесты 146/146 (+~28): QuoteGuard (11), SalesAgent/API approvals/actions (17),
     DoD-сценарий расширен до «… → pricing → sales_draft → send → approve → сообщение
     клиенту → идемпотентность».
2. **feat/pricing-engine** — вертикальный срез «цены на заявку»:
   - `PricingService`: клиентская цена = закупочная × (1 + margin/100), округление
     half-up; margin берётся из `company.settings.pricing.margin_percent`
     (по умолчанию `PRICING_MARGIN_PERCENT=30.0`, валюта `RUB`).
   - `process(part_request_id, run_id=None)` штампует `customer_price`,
     `total_price` (× кол-во), `margin_percent` у всех офферов последнего поиска,
     выбирает лучшее предложение (мин. по `total_price`) и пишет
     `structured_data.pricing` ({best_offer_id, quote_total, currency, margin_percent}).
   - `PricingAgent` — обработчик handoff-задачи `pricing_parts`, которую
     SearchAgent создаёт после поиска; ответ агента со штампом цены
     и routing_decision.
   - REST API под JWT: `POST /part_requests/{id}/price` (пересчёт по текущему
     поиску) и `GET /part_requests/{id}/quote` (хранимый квоут или статус
     `not_priced`); схемы `SupplierOfferRead`/`PartQuoteRead`.
   - Frontend: в панели заявки блок «Лучшее предложение» (бренд, артикул,
     цена за единицу и за позицию), колонка «Цена» в таблице предложений
     (видима менеджеру), квоут подтягивается из `/quote`.
   - Alembic-миграция `7f3b9c2d4e5a` (столбцы офферов + `companies.settings`),
     застамплена в live-БД; сидинг создаёт агента `pricing-agent`.
   - Тесты 118/118: PricingService (14), pricing API (7), DoD-сценарий расширен
     до «диалог → VIN → поиск → pricing → quote», сидинг + дашборд.
2. **feat/supplier-adapters** — вертикальный срез «поиск предложений»:
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
.venv\Scripts\python.exe -m pytest     # 146 тестов: агенты, оркестратор, API, память, email, поиск, эмбеддинги, auth, диалоги, intake, поставщики, цены, согласование
```

## Структура

```
agentforge/
├── backend/
│   ├── app/
│   │   ├── api/v1/        # REST API: companies, agents, tasks, logs, settings, dashboard, customers, conversations, part_requests, suppliers, quotes, approvals, actions
│   │   ├── core/          # config, database, redis, seeding
│   │   ├── agents/        # BaseAgent, SystemAgent, EmailAgent, SearchAgent, IntakeAgent, PricingAgent, SalesAgent, реестр
│   │   ├── orchestrator/  # сердце платформы: маршрутизация, handoff, очередь, воркеры
│   │   ├── tools/         # каждый инструмент — отдельный модуль (email, search, http)
│   │   ├── suppliers/     # адаптеры поставщиков: base, mock, csv, normalize, registry
│   │   ├── models/        # Agent, Company, Task, Memory, Customer, Conversation, PartRequest, Supplier, Quote, ApprovalRequest, AgentAction, AgentFeedback
│   │   ├── services/      # сервисный слой (в т.ч. PartsSearchService, SupplierService, QuoteGuard, QuoteService, SalesService)
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
