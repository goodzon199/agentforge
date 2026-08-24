# Pack Security & Isolation (Sprint 5.9)

Статус: **проект контракта (5.9.0)** — утверждается до начала реализации auth,
чтобы потом не переделывать интеграцию Core ↔ Pack.

---

## 0. Главный инвариант спринта

> Даже полностью скомпрометированный Pack не может прочитать данные, вызвать
> действие или обратиться к другому Pack сверх явно выданных ему Core-разрешений.

Следствие: наш собственный AutoParts моделируется как потенциально взломанный.
«Свой» код не получает доверительных послаблений — только явные разрешения.

---

## 1. Границы доверия

```text
Internet
   ↓
Frontend / Public API
   ↓
┌─────────────────────────────┐
│         TRUSTED CORE        │
│ Auth / Permissions / Audit  │
└──────────────┬──────────────┘
               │
        authenticated RPC
               │
     ┌─────────┴─────────┐
     ↓                   ↓
 AutoParts Pack       Beauty Pack
 UNTRUSTED             UNTRUSTED
```

| Субъект | Доверие | Обоснование |
|---|---|---|
| Core | trusted | единственная точка аутентификации, авторизации, аудита |
| Frontend | полу-доверенный | публичный токен компании + пользовательский JWT; без внутренних прав |
| Public API | доверенная граница | rate-limit, emergency switch, обязательная авторизация объектов |
| Pack (любой) | **untrusted** | сторонний код; скомпрометирован по умолчанию |
| Redis | инфраструктура | очереди неймспейсены (v0.5.1); не канал авторизации |

Правила пересечения границ:

1. Каждый вызов Pack → Core аутентифицирован и авторизован по разрешениям
   конкретного пака (не «какого-то внутреннего сервиса»).
2. Каждый вызов Core → Pack несёт подписанный Core'ом токен; Pack проверяет
   подпись, но не является авторитетом ни по чему.
3. Core никогда не доверяет идентификаторам (`company_id`, `customer_id`,
   `conversation_id`), присланным Pack'ом, без повторной проверки принадлежности
   объекту (tenant re-authorization).
4. Сетевая изоляция (docker-сети, egress) — отдельная тема, не заменяет
   криптографическую аутентификацию и в этом спринте не рассматривается.

---

## 2. Активы

| Актив | Владелец | Пример ущерба при компрометации |
|---|---|---|
| Персональные данные клиентов | компания-арендатор | утечка PII всех компаний платформы |
| Переписки (conversations) | компания | социальная инженерия от имени бренда |
| Заявки/заказы/цены | компания | финансовые махинации |
| Календари бронирований | компания | срыв записи, конкурентная разведка |
| LLM-бюджет (usage) | оператор платформы | слив токенов, financial DoS |
| Audit trail | оператор | сокрытие следов (нужен append-only поток) |

---

## 3. As-is: что есть сейчас и где дыры (аудит v0.5.1)

Механизмы, доставшиеся от монолита:

- один статический `INTERNAL_API_TOKEN` для **всех** внутренних вызовов в обе
  стороны (`shared/internal.py`, env `INTERNAL_API_TOKEN`);
- личность пака при вызове Core — само-заявленный заголовок `X-Pack-Name`
  (`services/core/app/api/internal.py::_require_pack_permission`);
- права пака = `pack.permissions` из манифеста; **declared ≡ granted**, базы
  «выданных» разрешений нет (`services/core/app/models/pack.py`);
- checksum манифеста сверяется при регистрации/healthcheck (5.7), но это
  self-declared checksum;
- tenant-scoping на Context API отсутствует: `GET /internal/context/customers/{id}`
  возвращает клиента любого арендатора паку с правом `customer.read`.

Отсюда — все девять сценариев из матрицы ниже сегодня либо проходимы целиком,
либо проходимы частично. Это фиксируется честно: текущий токен — наследие
однопроцессного монолита, где границы доверия не существовало.

---

## 4. Матрица атак (обязана быть покрыта тестами 5.9)

| # | Атака | Вектор | Обязательное поведение | Где enforcement | Пункт |
|---|---|---|---|---|---|
| A1 | Pack impersonation | Beauty шлёт `X-Pack-Name: autoparts` | невозможно: личность берётся из проверенной подписи токена, не из заголовка | JWT-валидация в Core | 5.9.1–5.9.2 |
| A2 | Permission escalation | манифест добавил `order.create` → пак зовёт API | `403 PACK_PERMISSION_DENIED`: effective = declared ∩ granted из БД | permission-gate Core | 5.9.3 |
| A3 | Cross-tenant access | пак запрашивает клиента компании B | `403`: объект вне `tenant_id` токена | object-scope в Context/API Core | 5.9.5 |
| A4 | Cross-pack access | Beauty дёргает `/internal/...` AutoParts напрямую | невозможно: у Beauty нет секрета AutoParts; токен Beauty не проходит аудит пака-адресата | per-pack credentials + aud | 5.9.1–5.9.2 |
| A5 | Token theft/replay | украден долгоживущий общий токен | окно жизни ≤ 5 минут; `jti`; нет master-secret у пака | TTL + ротация + jti-cache | 5.9.2 |
| A6 | Manifest tampering | зарегистрирован artifact X, запущен Y | reject/degraded: расхождение артефакта с зафиксированным checksum | healthcheck + реестр | 5.9.1 (усиление 5.7) |
| A7 | Disabled pack жив | пак `disabled` продолжает слать запросы | `403 PACK_DISABLED` немедленно, независимо от живого токена | статус пака проверяется по БД на каждый вызов | 5.9.2 |
| A8 | Removed permission | админ снял `customer.read`, старый токен жив | окно риска ≤ TTL (5 мин); фактически мгновенно — effective читается из БД | permission-gate Core | 5.9.2–5.9.3 |
| A9 | Forged tenant/context | пак подменяет `company_id`/`customer_id`/`conversation_id` | Core повторно авторизует объект: belongs-to-tenant иначе `403` | object-scope в Core | 5.9.5 |

Критерий готовности спринта: каждый пункт A1–A9 — автотест
(adversarial suite, 5.9.6), падающий на ветке без фиксов.

Коды ошибок стандартизируются: `PACK_UNAUTHENTICATED`,
`PACK_PERMISSION_DENIED`, `PACK_DISABLED`, `TENANT_FORBIDDEN`,
`OBJECT_NOT_FOUND` (не раскрываем существование чужого объекта).

---

## 5. Целевая модель аутентификации

### 5.9.1 Pack Identity

Каждый установленный пак имеет собственную identity вместо «общего токена на
все сервисы».

Новая таблица `pack_identities`:

```text
PackIdentity
  id                 uuid pk
  pack_id            fk -> packs.name          # уникально среди активных
  publisher_id       str                       # из манифеста/реестра
  service_id         str                       # логическое имя сервиса пака
  status             active | suspended | revoked
  credential_hash    str                       # хеш секрета пака (PHC-формат)
  credential_version int                       # инкремент при каждой ротации
  created_at / rotated_at / revoked_at
```

Принципы:

- секрет генерирует **Core** при `register`/`enable`, показывается **один раз**
  (ответ регистрации), хранится только хешем;
- доставка секреты паку — через env конфигурации стека (`PACK_CREDENTIAL_<NAME>`),
  не через репозиторий;
- `disable` пака → `status=suspended`; `enable` → обратно `active`;
  `uninstall` → `revoked` (identity не переиспользуется);
- ротация: новая версия секрета, старая инвалидируется немедленно
  (credential_version пишется в токен для диагностики);
- удаление общего `X-Internal-Token` как конечной модели безопасности
  (переходный период совместимости см. §7).

### 5.9.2 Short-Lived Service Tokens

Вместо статического токена Core выдаёт короткоживущий JWT:

```json
{
  "iss": "agentos-core",
  "sub": "pack:beauty",
  "aud": "agentos-internal",
  "pack_id": "beauty",
  "tenant_id": "...",
  "permissions": [
    "customer.read",
    "conversation.read",
    "calendar.read",
    "calendar.write"
  ],
  "jti": "...",
  "iat": 1787300000,
  "exp": 1787300300
}
```

Параметры:

- **TTL = 5 минут.** Пак обновляет токен заранее (порог 60с до exp).
- Подпись: HS256 ключом Core (`INTERNAL_JWT_KEY`, отдельно от legacy-токена);
  переход на асимметрию (Ed25519/JWKS) — за кадром v1, отмечено в non-goals.
- `permissions` в клеймах — **информационные** (для диагностики и быстрого
  fail-fast на паке). Источник истины для авторизации — БД Core:
  `effective = declared ∩ granted` вычисляется на каждый запрос.
- `aud` различает назначение: `agentos-internal` — вызовы пака в Core;
  `pack:<name>` — диспетчерские токены Core→Pack (украденный токен одного пака
  не принимается другим).
- `jti` + короткий TTL: replay-кэш (redis, окно ≤ TTL) — hardening-пункт,
  включается после базовой реализации.

Жизненный цикл:

```text
Pack                                Core
  |  POST /internal/token            |
  |  X-Pack-Id / X-Pack-Credential   |
  |--------------------------------->|  проверяет identity: hash, status=active
  |  <-- JWT (exp=+300s) ------------|
  |  ...вызовы с Bearer JWT...       |  каждый вызов: подпись, exp,
  |                                  |  pack.status, effective-perms из БД
```

Пак не получает master secret Core никогда. Компрометация секрета пака
компрометирует только этого пака и ограничена TTL'ами выданных им токенов.

### 5.9.3 Declared vs Granted Permissions

Разработчик пака не может сам себе выдать право изменением манифеста.

- `manifest.permissions` → колонка `packs.declared_permissions`
  (синхронизируется при register/update автоматически);
- `packs.granted_permissions` — управляет **админ платформы**, руками;
- эффективные права: `effective = declared ∩ granted`.

Политика начальной выдачи (компромисс совместимости):

- первая регистрация пака: `granted := declared` (демо-стек работает как раньше);
- обновление манифеста с НОВЫМИ разрешениями: новые права появляются только в
  `declared` и **не действуют**, пока админ их явно не выдаст
  (в UI/логе — подсказка «требуется грант»);

Админ-API: `GET/PUT /api/v1/packs/{name}/permissions`
(выдать можно только подмножество `declared`; попытка гранта незаявленного —
`422`). Изменения пишутся в audit log (`permission.grant` / `permission.revoke`).

---

## 6. Tenant re-authorization (A3/A9)

Все pull-эндпоинты Core (`/internal/context/*`) и мутирующие операции паков
обязаны:

1. взять `tenant_id` из **проверенного** токена (не из тела запроса);
2. проверить, что запрошенный объект (customer/conversation/part_request…)
   принадлежит этому tenant;
3. чужой объект отвечать `403 TENANT_FORBIDDEN` (или `404 OBJECT_NOT_FOUND`
   там, где раскрытие существования недопустимо).

Даже «свой» `company_id` в теле запроса игнорируется в пользу токена.

---

## 7. Совместимость и план перехода

| Этап | Core→Pack | Pack→Core |
|---|---|---|
| сейчас (v0.5.1) | `X-Internal-Token` | `X-Internal-Token` + `X-Pack-Name` |
| 5.9.1–5.9.3 | `X-Internal-Token` (временно) | Bearer JWT; legacy тоже принимается |
| 5.9.4–5.9.5 | подписанный диспетчерский токен (`aud=pack:<name>`) | только JWT |
| финал 5.9 | — | `X-Internal-Token` отклоняется (кроме explicit dev-flag) |

Флаг совместимости `LEGACY_INTERNAL_TOKEN=true` (default true на время
спринта, в проде финала — false).

## 8. Non-goals этого спринта

- сетевая изоляция (per-pack docker networks, egress firewall);
- mTLS / асимметричные ключи + JWKS (заложено как эволюция HS256);
- песочница исполнения кода паков;
- per-pack rate limiting сверх существующего;
- шифрование содержимого очередей/БД.

Каждый пункт возвращается отдельным спринтом после стабилизации 5.9.

---

## 9. Декомпозиция и DoD

| Пункт | Содержание | Готовность |
|---|---|---|
| 5.9.0 | этот документ: threat model + security contract | [x] |
| 5.9.1 | `PackIdentity`: модель, миграция, выдача/ротация/отзыв секрета, env-доставка | [ ] |
| 5.9.2 | token-endpoint + JWT-валидация (iss/aud/exp/status/effective-perms), коды ошибок | [ ] |
| 5.9.3 | declared/granted: миграция, admin API, effective-формула, audit-события | [ ] |
| 5.9.4 | диспетчерские токены Core→Pack (`aud=pack:<name>`) + верификация в shared SDK | [ ] |
| 5.9.5 | tenant re-authorization на Context API и мутирующих эндпоинтах | [ ] |
| 5.9.6 | adversarial suite: A1–A9 автотестами + ручной прогон на живом стеке + раздел в docs | [ ] |

DoD спринта: все пункты [x]; adversarial-тесты красные на main без фиксов и
зелёные с ними; legacy-токен выключается флагом; E2E 5.8.3 (webchat, duplicate
dispatch, beauty, hellopack) остаётся зелёным; ruff/pytest/tsc/build чистые.
