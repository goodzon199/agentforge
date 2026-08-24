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
>
> Sprint 2 (часть 6) — Заказы: клиент принимает квоту (`accepted`), менеджер
> конвертирует принятую квоту в `Order` (HIGH-риск, только человек),
> автопринятие из диалога клиента, страница «Заказы» в UI.
>
> Sprint 3 (часть 1) — Пилотные каналы: публичный web-chat канал
> (`/public/chat`) без JWT — посетитель сайта превращается в Conversation и
> прогоняется через весь pipeline; human takeover — `conversation.mode`
> (ai_active / human_active / paused / closed), при перехвате AI замолкает,
> страница «Веб-чат» для демо.
>
> Sprint 3 (часть 2) — Аналитика пилота: деньги на дашборде — выручка и
> прибыль из заказов, конверсия (запросы → КП → заказ), SLA-метрики
> конвейера (avg/p95/% в SLA по каждой стадии), латентность поставщиков,
> счётчики LLM и watchdog: зависшие задачи/поиски помечаются failed
> (task_timeout / supplier_failed) и попадают в метрики.
>
> Sprint 3 (часть 3) — Качество агентов: `AgentFeedback` реально используется
> как метрика качества по агентам (accept / edit / reject / hallucination rate,
> human takeover, avg response, стоимость LLM на задачу), версии промптов
> SalesAgent (v1 «Базовая версия» → v2 «Структурированный шаблон») с
> A/B-сравнением качества, `LLMUsage` — стоимость каждого вызова,
> API `/agents/quality` и `/prompts`, UI-блоки «Качество агентов» и
> «Версии промптов» с активацией.
>
> Sprint 3 (часть 4) — PermissionEngine: единый механизм безопасности для
> любого агента — `(agent, company, action, resource, context)` →
> `{allowed, requires_approval, risk_level, reason}`. Политики по умолчанию
> в registry (action+resource), компания переопределяет риск через
> `company.settings.permissions` (`send_customer_message: low` →
> SalesAgent отправляет автономно). Вся платформа говорит через движок:
> Sales/Order/Conversation flows и аудит `AgentAction` берут риск и
> require-approval из одного источника; API `/permissions/evaluate`,
> `/permissions/policies` (GET/PUT).
>
> Sprint 3 (часть 5) — Company Policy Engine: бизнес-правила компании в
> отдельном домене (`CompanyPolicy`, 5 JSON-политик) — «как именно компания
> продаёт», в отличие от PermissionEngine «можно ли действовать»:
> PricingPolicy (мин. маржа, наценки по поставщикам, мин. прибыль,
> округление, скидки), SupplierPolicy (приоритет, запрещённые/любимые бренды,
> макс. срок, рейтинг, макс. вариантов), ApprovalPolicy (автоотправка по сумме,
> нужен менеджер/владелец), SalesPolicy (автоотправка quote, эмодзи, стиль,
> аналоги/сроки/остатки), SecurityPolicy (оверрайды PermissionEngine,
> зеркалятся в `settings.permissions`). API `/company-policies`, UI-вкладка
> «Политики компании».
>
> Sprint 3 (часть 6) — Real Supplier Integration: хватит mock — живой
> HTTP-адаптер поставщика (`HttpSupplierAdapter`, тип `http`) через
> `SupplierRegistry`, ничего не ломая. Авторизация (api-key/bearer/basic),
> поиск по артикулу, кроссы (аналоги расширяются в офферы `is_cross=true`),
> остатки/цена/срок; типизированные ошибки (`SupplierAuthError`,
> `SupplierRateLimitError`, `SupplierTimeoutError`, `SupplierConnectionError`,
> `SupplierParseError`, `SupplierResponseError`), ретраи с экспоненциальным
> бэкoff и учётом `Retry-After`, rate-limit (мин. интервал между запросами).
> Конфигурация через `supplier.settings` (Rossko/Armtek-style JSON API);
> поле `is_cross` у `SupplierOffer` (миграция `a1b2c3d4e5fb`).
>
> Sprint 3 (часть 6b) — Rossko live: подключён реальный поставщик Rossko
> (`RosskoAdapter`, тип `rossko`) — SOAP-сервис `GetSearch`
> (namespace `https://api.rossko.ru/`, `SOAPAction` = URL сервиса),
> `KEY1`/`KEY2` в теле запроса, `delivery_id` + `address_id` из
> `GetCheckoutDetails` аккаунта; парсинг `PartsList`/`stocks`/`crosses`
> (выбор лучшего склада: мин. цена среди в наличии), карточки без остатков
> пропускаются. Живые цены/остатки/сроки и кроссы; live e2e через пайплайн:
> поиск → supplier policy → цены (Mapco 1612₽ → 2095.60₽ при марже 30%);
> `/suppliers/{id}/test` = ok, 5 офферов.

---

## Роадмап (явные следующие блоки)

> Номер спринта + статус, чтобы roadmap не терялся между релизами.

**Выполнено (13):** Sprint 1 (Foundation) · Sprint 2.1–2.6 (Диалоги, Intake,
Поставщики mock/csv, Цены, Согласование продажи, Заказы) · Sprint 3.1 (Пилотные
каналы) · 3.2 (Аналитика пилота) · 3.3 (Качество агентов) · 3.4 (PermissionEngine)
· 3.5 (Company Policy Engine) · 3.6 (Real Supplier Integration: HTTP-адаптер
с auth/search/crosses/остатками/ошибками/retry/rate-limit + **Rossko live**
через `RosskoAdapter`/SOAP GetSearch — реальные цены и остатки в пайплайне).

**Sprint 3.7 — Живой заказ у Rossko** *(не сделано — следующий кандидат)*:
`RosskoAdapter` дорабатывается до `GetCheckout`/`GetOrders` — оформление
реального заказа поставщику из конвертированного `Order` (адрес/доставка,
реквизиты из `GetCheckoutDetails`), статусы заказа из `GetOrders`.
Веха: платформа не только ищет и продаёт, но и **закупает**.

**Sprint 4 — «Агентство агентов»** *(не сделано)*: выделение универсальных
компонентов из вертикального продукта — Agent Runtime, Orchestrator, Tool Registry,
Supplier/Integration Registry, Memory, Permission Engine ✓, Approval Engine, Action
Engine, Workflow Engine, Analytics. Автозапчасти становятся первым вертикальным
Pack (IntakeAgent, PartsSearchAgent, PricingAgent, SalesAgent, OrderAgent), затем
Beauty Pack (Reception/Booking/Sales/Reminder) и RealEstate Pack
(Lead/Qualification/PropertySearch/Viewing).

---

## Что сделано (по порядку, последнее сверху)

1. **feat/rossko-adapter** — реальный поставщик Rossko в платформе:
   - `suppliers/rossko.py` — `RosskoAdapter` (тип `rossko`): SOAP 1.1
     `GetSearch` (namespace `https://api.rossko.ru/`, `SOAPAction` = URL
     сервиса — выявлено по WSDL), `KEY1`/`KEY2` в теле, `text = brand +
     article`, `delivery_id` + опциональный `address_id` (оба — из
     `GetCheckoutDetails` аккаунта). Парсинг `PartsList/Part/stocks/stock`
     namespace-агностично (`_local`), кроссы `crosses/Part` → `is_cross=True`.
   - **Выбор склада**: среди складов с остатком (count>0) — мин. цена, при
     равенстве — мин. срок; карточки без `stocks` не котируются.
   - **Ошибки по live-ответам**: `success=false` + `message` →
     `SupplierAuthError` (ключ/авторизац), `SupplierRateLimitError` (лимит),
     иначе `SupplierResponseError`; SOAP Fault → `SupplierResponseError`.
     Ретраи транзиентных (408/425/429/5xx) с бэкoff, rate-limit `min_interval`
     (лимит Rossko: 300 поисков/мин).
   - Live: поставщик `rossko--live` (ключи в `supplier.settings`, не в коде),
     `/test` → ok, 5 офферов; e2e заявка P06089: поиск completed
     (2 поставщика), цены (Mapco 1612₽ → 2095.60₽ при марже 30%).
   - pytest **249 passed** (+16: auth/поиск/склады/кроссы/ошибки/retry/
     rate-limit/healthcheck на фейковом SOAP-сервере).

2. **feat/supplier-http-adapter** — реальный поставщик через `SupplierAdapter`:
   - `suppliers/http.py` — `HttpSupplierAdapter` (тип `http`): HTTP-запросы
     к Rossko/Armtek-style JSON API. Авторизация `api_key`/`bearer`/`basic`,
     поиск по артикулу/бренду, **кроссы** (`data.crosses` расширяются в
     офферы `is_cross=true`), остатки (`quantity`), цена (`price`), срок
     (`delivery_days`). Полевые ключи настраиваются (`keys`, `offers_key`,
     `crosses_key` — dotted path).
   - `suppliers/errors.py` — типизированные ошибки: `SupplierConnectionError`,
     `SupplierTimeoutError`, `SupplierAuthError`, `SupplierRateLimitError`,
     `SupplierResponseError`, `SupplierParseError` — дружелюбные русские
     сообщения, ни один сбой не роняет поиск.
   - **Retry** — экспоненциальный бэкoff для транзиентных (408/425/429/5xx,
     сеть), учёт `Retry-After`; **rate limit** — мин. интервал между запросами
     (`min_interval`), per-loop asyncio-lock.
   - `is_cross` у `NormalizedSupplierOffer` и `SupplierOffer`
     (миграция `a1b2c3d4e5fb`, live применена); персист в `PartsSearchService`.
   - Регистрация в `SupplierRegistry` (`types() = [mock, csv, http]`);
     конфигурация — через существующий `supplier.settings`, API не менялся.
   - pytest **233 passed** (+19: auth/search/crosses/errors/retry/rate-limit/
     timeout/healthcheck на фейковом HTTP-сервере). Live smoke:
     `/suppliers` POST `http` + `/test` — грациозная ошибка при недоступности.

2. **feat/company-policy-engine** — бизнес-правила компании отдельным доменом:
   - `CompanyPolicy` (таблица `company_policies`, одна строка на компанию):
     пять JSON-политик `pricing / supplier / approval / sales / security`;
     `core/policies.py` — типизированные дефолты, `merge_policy` —
     компания хранит только свои оверрайды.
   - `PricingService`: мин. маржа (floor над наценкой), наценки по поставщикам
     (`markups: {slug: %}`), мин. прибыль (поднимает цену), округление к шагу
     (0.01/1/10/50/100). Дефолты = прежнее поведение (без изменений цены).
   - `PartsSearchService`: `SupplierPolicy` — запрещённые бренды, любимые
     первыми, макс. срок, мин. рейтинг (из `supplier.settings.rating`),
     приоритет поставщиков, лимит `max_variants`.
   - `SalesService.request_send`: автоотправка по `sales.auto_send_quote`
     или `approval.auto_approve_quote_amount` (только для MEDIUM-риска;
     PermissionEngine остаётся шлюзом безопасности).
   - `SecurityPolicy` зеркалится в `company.settings.permissions` —
     единый источник для PermissionEngine.
   - API `/company-policies` (GET — эффективные политики + дефолты; PUT —
     частичное обновление любого домена). UI: вкладка «Политики компании»
     (`/policies`) — формы всех пяти доменов.
   - Миграция `a1b2c3d4e5fa` применена live. pytest **214 passed**
     (+19: merge/сервис/цены/поставщики/API/e2e автоотправка).

2. **feat/permission-engine** — единый механизм безопасности:
   - `core/permissions.py`: `PermissionEngine` — `evaluate(agent, company,
     action, resource, context)` → `PermissionDecision{allowed,
     requires_approval, risk_level, reason}`; registry `DEFAULT_POLICIES`
     keyed `(action, resource)` (LOW автономно / MEDIUM согласование / HIGH
     только человек); компания переопределяет риск через
     `company.settings.permissions` (`{"send_customer_message": "low"}` или
     `{"give_discount:quote": "medium"}`, неверные значения игнорируются).
     Неизвестное действие → MEDIUM.
   - Полный переход: `core/risk.py` удалён; sales/order/conversation flows и
     `_record_action` берут риск и `requires_approval` из движка
     (resource = target_type, company из БД). `request_send` принимает
     решение через `evaluate()`: MEDIUM → ApprovalRequest (как раньше),
     override LOW → авто-отправка через общий `_perform_send`
     (QuoteGuard проверяется всегда).
   - API `/permissions`: `POST /evaluate` (контракт), `GET /policies`
     (эффективные политики с source default/company), `PUT /policies`
     (переопределение, валидация low/medium/high, пустой map сбрасывает).
   - Тесты: `tests/test_permission_engine.py` — 16 шт (unit-движок, API,
     e2e авто-отправка при override LOW, регрессия MEDIUM → согласование).
     pytest **195 passed**. Live: `GET/POST /permissions` работают,
     `send_supplier_order` → `{allowed:false, requires_approval:true,
     risk_level:"HIGH", reason:"…только человек…"}`.

2. **feat/agent-quality** — качество агентов и версии промптов:
   - `AgentFeedback` (accept / edit / reject / incorrect_fact) превращён в
     метрику: `GET /agents/quality?days=N` возвращает по каждому агенту
     задачи, success_rate, avg_response_seconds, человеческую обратную связь
     (счётчики + проценты), human takeover (по `AgentAction`), LLM-вызовы и
     стоимость (`LLMUsage`, тарифы `llm_rub_per_1m_tokens` в config, 0 для
     неизвестных моделей, напр. ollama), cost per task.
   - Версии промптов: модель `PromptVersion`, сидинг создаёт sales v1/v2,
     `Quote.prompt_version` и `AgentFeedback.prompt_version` — обратная связь
     группируется по версии в `by_prompt_version` (A/B: v1 «Базовая версия»
     против v2 «Структурированный шаблон»). API `/prompts`:
     GET / POST / POST `{id}/activate` / DELETE, scoped по компании (403
     чужой компании). `PromptService.active_prompt` отдаёт активную версию,
     SalesAgent дёргает её при подготовке черновика.
   - Галлюцинации: при детерминированном guard-block или блокированной
     отправке SalesAgent пишет `AgentFeedback.incorrect_fact`, атрибуция —
     по переданному `agent_id` или фоллбэк `sales-agent` по slug.
   - Стоимость LLM: `llm/cost.py` + `TaskLLMProxy` в `llm/client.py`
     (записывает usage каждого `chat()` и flush в БД по завершении задачи),
     оркестратор присваивает `task.agent_id` по финальному агенту.
   - UI: блок «Качество агентов · 7 дней» (rates, ответ, перехват, цена) и
     «Версии промптов · сравнение качества» с кнопкой «Активировать».
   - Миграция `a1b2c3d4e5f9` (идемпотентная) применена live; live-проверка
     `/agents/quality` и `/prompts` (v1 активна); pytest **179 passed**.

2. **feat/pilot-analytics** — аналитика пилота: деньги и SLA на дашборде:
   - `GET /analytics/pilot?days=N` под JWT (scoped по компании): запросы,
     диалоги, `ai_handled` (AI отвечал в диалоге), `handed_to_manager` и
     `takeover_rate` (по `AgentAction.conversation_takeover`), заявки,
     КП отправлено/принято, заказы, выручка и прибыль (из `Order.order_total`
     и снимка items с `margin_percent`), средний ответ AI
     (`avg_response_seconds`), pipeline-стадии с SLA, поставщики и LLM.
   - Pipeline/SLA: `core/config.py` — `pipeline_sla_seconds`
     (process_customer_message 5s / search_parts 15s / pricing_parts 2s /
     sales_draft 5s), `task_max_running_seconds` 60,
     `search_run_max_running_seconds` 60. Для каждой стадии считаются count,
     avg/p95 длительности, % в SLA и число failed.
   - Watchdog в `orchestrator/worker.py` (каждые ~5с):
     `TaskService.mark_stale_tasks` → зависшие queued/running-задачи помечаются
     failed с `error="task_timeout: …"` + TaskEvent;
     `PartsSearchService.mark_stale_runs` → зависшие поиски failed с
     `error="supplier_failed: …"`, `PartRequest` возвращается в
     `ready_for_search`. Таймауты задач видны в метрике `task_timeouts`.
   - `llm/client.py`: процессные счётчики вызовов/отказов (`stats()`,
     `available`) — видны в блоке LLM.
   - Frontend: на главной странице блок «Пилотная аналитика · 7 дней» —
     выручка/прибыль/заказы/запросы/перехват (StatsCard), конвейер с SLA
     (avg/p95/% в SLA по стадиям), поставщики и LLM.
   - Тесты 171/171 (+5): пустая витрина, деньги+конверсия+время ответа,
     метрики перехвата, watchdog по задачам и по поискам. Live E2E: старый
     заказ в аналитике (7930.00 / прибыль 3870.00), pipeline со стадиями,
     watchdog посчитал таймауты, фронт собран и отдаёт 200.
2. **feat/pilot-webchat-takeover** — первый реальный канал + управление диалогом:
   - Публичный web-chat: `POST /public/chat/start` (ищет компанию по
     `companies.public_token`, находит-или-создаёт Customer source=webchat и
     Conversation channel=webchat; тот же `client_key` резюмирует диалог),
     `POST /public/chat/messages` (тот же `ConversationService.add_message` →
     таск → оркестратор → ответ агента), `GET /public/chat/{id}/messages`
     (polling для виджета). Всё без JWT.
   - Human takeover: у Conversation появился `mode`
     (ai_active/human_active/paused/closed) + ручки
     `POST /conversations/{id}/takeover|release|pause|close|reopen`
     (scoped по компании). Гейт в `add_message`: входящее сообщение клиента
     сохраняется, но задача `process_customer_message` создаётся только при
     `ai_active`; `IntakeService` дополнительно не отвечает при перехвате
     (защита от in-flight задач). Менеджер отвечает как `sender_type=manager`.
     Смена режима пишется в `AgentAction` (conversation_takeover/release/…)
     — база для метрики human-takeover-rate.
   - Устойчивость Intake: если LLM вернул пустой/заглушечный уточняющий вопрос
     (например «...»), используется детерминированный вопрос (VIN/деталь).
   - Frontend: в диалогах бейдж режима + кнопки «Перехватить диалог»,
     «Вернуть AI», «Пауза», «Закрыть», «Возобновить»; при human_active
     сообщения уходят от имени менеджера; отдельная публичная страница
     `/webchat` (виджет-демо, без авторизации).
   - Alembic-миграция `a1b2c3d4e5f8` (conversations.mode + companies.public_token),
     применена в live-БД; `public_token` бэкфиллится сидингом и виден в
     `GET /companies`.
   - Тесты 166/166 (+9): публичный чат (start/resume/полный pipeline/404/403),
     перехват (AI молчит при human_active/paused/closed, менеджер отвечает,
     release возобновляет), scoping 403, аудит takeover. Live E2E: web-chat →
     «Пришлите VIN» → перехват → AI молчит → ответ менеджера → release.
2. **feat/order-conversion** — вертикальный срез «квота → заказ»:
   - `OrderService`: `accept()` (LOW-риск, только из `sent`, идемпотентный,
     аудит `AgentAction accept_quote`), автопринятие `accept_if_customer_confirms()`
     — regex-детект подтверждения («да, беру» / «подтверждаю» / «не беру») в
     `ConversationService.add_message` для входящих сообщений клиента,
     `create_from_quote()` (HIGH-риск, только менеджер, `sent`/`accepted` →
     `Order` + `QuoteStatus.converted_to_order`, номер `ORD-{n}-{hex}`,
     подтверждение в диалог structured_data `{kind: order, ...}`, идемпотентно).
   - Сущность `Order`: FK на company/conversation/customer/part_request/quote,
     `order_number`, `order_total` Numeric(12,2), `items` JSON-снимок квоты,
     `created_by_user_id`, статусы `new/confirmed/paid/cancelled`.
   - REST API под JWT: `GET /orders` (scoped по компании), `GET /orders/{id}`,
     `POST /quotes/{id}/accept`, `POST /quotes/{id}/convert` (403 не-менеджеру,
     409 не та стадия квоты).
   - Frontend: в блоке «Предложение клиенту» — «Клиент принял предложение»
     (send), «Создать заказ» (менеджер, sent/accepted) и статус заказа;
     новая страница «Заказы» (таблица: номер, статус, сумма, товары, дата)
     с пунктом в сайдбаре.
   - Alembic-миграция `a1b2c3d4e5f7` (таблица orders + enum `order_status`),
     применена в live-БД; E2E: sent → авто-accept → convert → заказ в диалоге
     → идемпотентность, `create_order` аудируется как HIGH.
   - Тесты 157/157 (+11): accept/автоaccept/convert/orders API, DoD-сценарий
     расширен до «… → quote → accepted → convert → order».
2. **feat/sales-approval** — вертикальный срез «предложение клиенту с согласованием»:
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

# 2. Поднять платформенный стек:
#    core + autoparts + beauty (паки) + frontend + redis + mailhog + ollama
#    Первый запуск скачает модель LLM в Ollama (~2 ГБ) и соберёт образы.
docker compose up --build
```

После запуска:

- Frontend (AgentOS UI): http://localhost:3000
- Core API (платформенный gateway): http://localhost:8011 — Swagger: http://localhost:8011/docs
- AutoParts pack API: http://localhost:8012, Beauty pack API: http://localhost:8013
- **MailHog** (входящие письма EmailAgent): http://localhost:8025
- PostgreSQL: core localhost:5433, autoparts localhost:5434; Redis: localhost:6379

Первый экран — **Вход**: админ по умолчанию `admin@agentos.local` / `admin123`
(меняется через `SEED_ADMIN_*` в `.env`). После входа — Обзор: Компании / Агенты /
Задачи / Логи / Настройки. Раздел **Паки** — регистрация и жизненный цикл
доменных паков; **Диалоги** — клиенты и переписка: сообщение клиента уходит в
задачу обработки и маршрутизируется в пак через оркестратор core.

## Архитектура

AgentOS — платформа + паки. Frontend знает только core; доменная логика живёт
в паках и вызывается по внутреннему контракту.

```
frontend
   ↓
core  (gateway, auth, conversations, tasks, registry, metering)
   ↓ internal contract (token-gated)
├── autoparts  → db-autoparts
└── beauty     (stateless demo)
```

Подробнее: `docs/PLATFORM_EXTRACTION.md` (контракт, спринты 5.0–5.8.3).

## Агенты

При первом старте автоматически создаются демо-компания, **SystemAgent** и **EmailAgent**.

- **SystemAgent** — диспетчер: получает задачу и определяет нужного агента
  (детерминированные правила или LLM через Ollama).
- **EmailAgent** — специалист по почте: принимает задачу от SystemAgent,
  достаёт получателя/тему/текст и отправляет письмо по SMTP (в демо — MailHog,
  UI на http://localhost:8025). Получателя можно указать в поле «Кому (email)».
- **Агенты паков** — материализуются из манифеста пака при его включении
  (например, IntakeAgent/SearchAgent/SalesAgent пака autoparts) и выполняются
  в сервисе пака по internal contract; core хранит только реестровую проекцию.

Проверьте прямо в UI: **Задачи → «Новая задача»** → введите текст → результат,
журнал событий и письмо в MailHog. Работает даже без ключа OpenAI —
детерминированный режим маршрутизации.

## Локальная разработка (без Docker)

```bash
# Core
cd backend/services/core
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8011

# Pack (пример: autoparts)
cd backend/services/autoparts
uvicorn app.main:app --reload --port 8012

# Frontend
cd frontend
npm install
npm run dev                   # http://localhost:3000
```

## Тесты

```bash
cd backend/shared      && python -m pytest tests   # SDK: агенты, манифесты, workflow
cd backend/services/core && python -m pytest tests # core: gateway, packs, context, usage, workflows
cd backend/services/autoparts && python -m pytest tests
cd backend/services/beauty   && python -m pytest tests
```

## Структура

```
agentforge/
├── backend/
│   ├── shared/              # Pack SDK: agents, manifest, workflow, internal contract
│   └── services/
│       ├── core/            # платформа: auth, gateway, orchestrator, packs, usage, traces
│       ├── autoparts/       # пак автозапчастей (своя БД, alembic, suppliers)
│       └── beauty/          # демо-пак салона (stateless)
├── frontend/                # Next.js + TypeScript + Tailwind (знает только core)
├── scripts/                 # db_backup.sh / db_restore.sh
├── docs/                    # PLATFORM_EXTRACTION.md и др.
└── docker-compose.yml       # core, autoparts, beauty, frontend, db×2, redis, mailhog, ollama
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
