# Pack Security & Isolation (Sprint 5.9)

Статус: **контракт утверждён** (5.9.0, с поправками ревью) — реализация идёт
по этапам 5.9.1–5.9.6.

---

## 0. Главный инвариант спринта

> Даже полностью скомпрометированный Pack не может прочитать данные, вызвать
> действие или обратиться к другому Pack сверх явно выданных ему Core-разрешений.

Следствие: наш собственный AutoParts моделируется как потенциально взломанный.
«Свой» код не получает доверительных послаблений — только явные разрешения.
Самая опасная дыра будущего Marketplace закрыта заранее: **глобальный
credential пака физически не может выбрать tenant** — доступ к данным компании
существует только внутри workload-токенов, которые выдаёт сам Core.

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
  «выданных» разрешений нет;
- checksum манифеста сверяется при регистрации/healthcheck (5.7), но это
  self-declared checksum;
- tenant-scoping на Context API отсутствует: клиент любого арендатора
  возвращается паку, у которого в манифесте есть `customer.read`.

Отсюда — все девять сценариев из матрицы ниже сегодня либо проходимы целиком,
либо проходимы частично. Это фиксируется честно: текущий токен — наследие
однопроцессного монолита, где границы доверия не существовало.

---

## 4. Матрица атак (обязана быть покрыта тестами спринта)

| # | Атака | Вектор | Обязательное поведение | Где enforcement | Этап |
|---|---|---|---|---|---|
| A1 | Pack impersonation | Beauty шлёт `X-Pack-Name: autoparts` | невозможно: личность берётся из проверенной подписи токена, не из заголовка | JWT-валидация в Core | 5.9.1, 5.9.4 |
| A2 | Permission escalation | манифест добавил `order.create` → пак зовёт API | `403 PACK_PERMISSION_DENIED`: effective = declared ∩ granted из БД | permission-gate Core | 5.9.2 |
| A3 | Cross-tenant access | пак запрашивает клиента компании B | `403 TENANT_FORBIDDEN`: tenant берётся из workload-токена, пак его не выбирает | object-scope в Core | 5.9.3 |
| A4 | Cross-pack access | Beauty дёргает `/internal/...` AutoParts напрямую | невозможно: у Beauty нет dispatch-секрета AutoParts; токен Beauty не проходит аудит пака-адресата | per-pack dispatch secret + aud | 5.9.1 |
| A5 | Token theft/replay | украден долгоживущий общий токен | окно жизни ≤ 5 минут; `jti`; master-secret Core никогда не покидает Core | TTL + ротация + jti-cache | 5.9.2–5.9.4 |
| A6 | Manifest tampering | зарегистрирован artifact X, запущен Y | reject/degraded: расхождение артефакта с зафиксированным checksum | healthcheck + реестр | усиление 5.7 |
| A7 | Disabled pack жив | пак `disabled` продолжает слать запросы | `403 PACK_DISABLED` немедленно, независимо от живого токена | статус identity проверяется по БД на каждый вызов | 5.9.4 |
| A8 | Removed permission | админ снял `customer.read`, старый токен жив | окно риска ≤ TTL (5 мин); effective читается из БД на каждый вызов | permission-gate Core | 5.9.2–5.9.3 |
| A9 | Forged tenant/context | пак подменяет `company_id`/`customer_id`/`conversation_id` | Core повторно авторизует объект: belongs-to-tenant иначе отказ | object-scope в Core | 5.9.3 |
| A10 | Rotation bypass | украден старый секрет после ротации | мгновенный `401`: `credential_version` токена ≠ версии identity | cv-check при каждом вызове | 5.9.1 |

Критерий готовности спринта: ключевые пункты матрицы — автотесты
(adversarial suite EvilPack, 5.9.6), падающие на ветке без фиксов.

Коды ошибок стандартизируются: `PACK_UNAUTHENTICATED`, `PACK_PERMISSION_DENIED`,
`PACK_DISABLED`, `PACK_REVOKED`, `TENANT_FORBIDDEN`, `OBJECT_NOT_FOUND`
(не раскрываем существование чужого объекта).

---

## 5. Целевая модель аутентификации

### 5.9.1 Pack Identity

Каждый установленный пак имеет собственную identity вместо «общего токена на
все сервисы».

```text
PackIdentity
  id                     uuid pk
  pack_id                str, unique среди активных
  service_id             str            # логическое имя сервиса пака
  status                 active | disabled | revoked
  bootstrap_secret_hash  str            # PBKDF2 — проверка секрета пака
  dispatch_secret_hash   str            # sha256 — сверка смонтированного материала
  credential_version     int            # инкремент при каждой ротации
  created_at / rotated_at / revoked_at / last_authenticated_at
```

Два разных секрета на identity (ключевое решение контракта):

| Секрет | Кто хранит plaintext | Для чего | Хеш в БД |
|---|---|---|---|
| `bootstrap_secret` | только пак | подтвердить «я действительно AutoParts» на `POST /internal/token` | PBKDF2 |
| `dispatch_secret` | **Core и пак** (HS256 v1) | Core подписывает диспетчерские токены `aud=pack:<name>`; пак их верифицирует | sha256 (сверка материала) |

Компрометация Beauty не позволяет подписать токен для AutoParts: ключ подписи
у каждого пака свой. Позже HS256 заменяется на Ed25519/JWKS без изменения
`PackIdentityService`.

Принципы:

- секреты генерирует **Core** (`secrets.token_urlsafe(32)` — ≥256 бит),
  формат `<pack>_sec_<43 символов>`;
- plaintext показывается **один раз** в ответе provision/rotate; в БД — только
  хеши; в репозитории/.env.example — никогда;
- `disable` пака → `status=disabled`; `enable` → `active`; `uninstall` →
  `revoked` (identity переживает удаление пака и не переиспользуется);
- ротация: новая пара секретов + `credential_version += 1`; старые секреты и
  все выданные до этого токены инвалидируются немедленно (cv-check);
- `last_authenticated_at` обновляется при успешной выдаче токена.

Secret delivery (dev):

```text
.secrets/
├── autoparts-bootstrap
├── autoparts-dispatch
├── beauty-bootstrap
└── beauty-dispatch
```

`.gitignore`: `.secrets/`. Compose монтирует каталог как docker secret volume
(`/run/secrets/pack-credentials:ro`) в core-api и в каждый пак. Production
потом переезжает на Vault/KMS без изменения `PackIdentityService`.

### 5.9.2 Два типа токенов

Зафиксировано как архитектурное решение: **не бывает универсального Pack JWT**.

**Service token** — подтверждает личность пака, ничего больше.

```text
Pack                                 Core
  |  POST /internal/token            |
  |  X-Pack-Id / X-Pack-Credential   |
  |--------------------------------->|  hash-проверка, статус identity
  |  <-- service JWT (exp=+300s) ----|
```

Claims: `{iss:"agentos-core", sub:"pack:<name>", aud:"agentos-internal",
pack_id, jti, iat, exp, credential_version}`. Без `tenant_id`, без
`permissions`. Годится для health, registration handshake, credential refresh,
service-level операций. **Пак не выбирает tenant_id при получении токена** —
эндпоинт его просто не принимает.

**Workload token** — создаётся самим Core во время dispatch:

```text
Core receives customer message
        ↓
Core knows company/task/conversation
        ↓
Core creates workload JWT
        ↓
AutoParts receives: context + workload_token
        ↓
AutoParts → Core Context API using same workload_token
```

```json
{
  "iss": "agentos-core",
  "aud": "agentos-internal",
  "sub": "pack:autoparts",
  "pack_id": "autoparts",
  "tenant_id": "...",
  "task_id": "...",
  "dispatch_id": "...",
  "permissions": ["customer.read", "conversation.read"],
  "credential_version": 3,
  "jti": "...",
  "exp": "now + 5m"
}
```

Именно workload-токеном пак ходит в `/internal/context/*`,
`/internal/actions/*`, `/internal/memory/*`. Pack физически не может сказать:
«дай мне токен для компании B».

**Dispatch token (Core→Pack)** — подписывается per-pack `dispatch_secret`,
`aud = pack:<name>`; передаёт `task_id`, `dispatch_id`, `tenant_id`, `exp`,
`jti`. Повторное исполнение блокирует существующая идемпотентность по
`dispatch_id`; украденный токен Beauty не принимается AutoParts.

**Rotation/revoke — мгновенная инвалидация:**

```text
token.credential_version = 2
DB identity.credential_version = 3
→ 401
```

TTL 5 минут ограничивает остаточное окно, но основной барьер — cv-check на
каждом вызове. Подпись service/dispatch/workload токенов — HS256;
`INTERNAL_JWT_KEY` (ключ service/workload токенов) никогда не покидает Core;
пакам он не нужен — они получают готовые bearer-токены.

### 5.9.3 Declared vs Granted Permissions

Разработчик пака не может сам себе выдать право изменением манифеста.

- `manifest.permissions` → `declared_permissions` (синхронизируется при
  register/update автоматически);
- `granted_permissions` — управляет **админ платформы**, явно;
- эффективные права: `effective = declared ∩ granted`.

Политика выдачи:

- **migration bootstrap (только для существующих доверенных builtin-паков**
  autoparts/beauty): однократный перенос declared → granted при миграции,
  иначе живой стек сломается;
- **любой новый пак**: register → `granted_permissions = []` → admin reviews →
  explicit grant. Иначе EvilPack добавит себе `customer.read`, `order.create`,
  `memory.read` первой же регистрацией, и security model проиграна ещё до
  начала.

Админ-API: `GET/PUT /api/v1/packs/{name}/permissions` (выдать можно только
подмножество declared; иначе `422`). Изменения пишутся в audit log
(`permission.grant` / `permission.revoke`).

---

## 6. Tenant re-authorization (A3/A9)

Все pull-эндпоинты Core (`/internal/context/*`) и мутирующие операции паков
обязаны:

1. взять `tenant_id` из **проверенного workload-токена** (не из тела запроса);
2. проверить, что запрошенный объект (customer/conversation/part_request…)
   принадлежит этому tenant;
3. чужой объект отвечать `403 TENANT_FORBIDDEN` (или `404 OBJECT_NOT_FOUND`
   там, где раскрытие существования недопустимо).

Даже «свой» `company_id` в теле запроса игнорируется в пользу токена.

## 5A. Workload Delegation — спецификация этапа 5.9.3 (реализована)

> Статус: **реализована** (5.9.3b, с инвариантами I1–I4 ниже). Пункт «Решение» =
> согласованное предложение (D1–D7 утверждены без изменений).

### 5A.1 Принцип

**Service token** доказывает, *кто* такой Pack (identity, без данных).
**Workload token** доказывает, что конкретному Pack разрешено выполнить
конкретную работу для конкретного tenant над конкретными объектами.

Workload token создаёт **только Core**, только в момент dispatch. Pack не может
получить workload token сам: `POST /internal/token` навсегда остаётся
service-identity endpoint и выдаёт токены без `tenant_id`, `task_id`,
`permissions` и `scope`.

```json
{
  "iss": "agentos-core",
  "aud": "agentos-internal",
  "sub": "pack:autoparts",

  "pack_id": "autoparts",
  "tenant_id": "...",

  "task_id": "...",
  "dispatch_id": "...",

  "permissions": ["customer.read", "conversation.read"],

  "scope": {
    "mode": "explicit",
    "conversation_ids": ["..."],
    "customer_ids": ["..."]
  },

  "credential_version": 2,

  "jti": "...",
  "iat": 0,
  "nbf": 0,
  "exp": 0
}
```

TTL: `min(WORKLOAD_JWT_TTL_SECONDS=300, дедлайн задачи)` — короче для
коротких задач (D7).

### 5A.2 Формула permissions (least privilege per workload)

Никакого доверия данным от Pack:

```
manifest declared  ∩  tenant granted  ∩  required by this operation
                        (= effective 5.9.2)      =  workload permissions
```

- `declared` / `granted` — уже реализовано в 5.9.2 (`effective()`).
- **required** задаёт точка dispatch в Core: реестр операций
  `OPERATION_PERMISSIONS` в коде Core (например `intake_dispatch →
  {customer.read, conversation.read}`). Манифест пака **не участвует** в
  вычислении required и не может расширить набор (D1).

Даже если AutoParts в целом имеет `customer.read, conversation.read,
supplier.search, order.create`, для Intake-dispatch токен содержит только
`customer.read, conversation.read`. `scope_mode=tenant` (ниже) расширяет
объекты, но никогда не permissions.

### 5A.3 Object scope

Одного `tenant_id` недостаточно: легальный токен tenant A не должен давать
доступ к Conversation B той же компании.

```json
"scope": { "mode": "explicit", "conversation_ids": [...], "customer_ids": [...] }
```

- `scope_mode=explicit` (**default**) — перечисленные id; тип ресурса,
  отсутствующий в scope, закрыт полностью (D4).
- `scope_mode=tenant` — все объекты tenant; выбирается только решением точки
  dispatch в Core, pack запросить его не может (D2).
- Scope подписан JWT: модификация = signature failure.

### 5A.4 PackWorkloadPrincipal и зависимости эндпоинтов

Internal endpoints не разбирают JWT самостоятельно:

```python
class PackWorkloadPrincipal:
    pack_id: str
    tenant_id: UUID
    task_id: UUID
    dispatch_id: str
    permissions: frozenset[str]
    scope: WorkloadScope          # mode + frozenset per resource type
    jti: str
    credential_version: int

principal = Depends(require_workload_permission("customer.read"))
# внутри handler'а дополнительно:
require_scope_object(principal, "conversation", conversation_id)
```

### 5A.5 Pipeline авторизации Context API

```
Bearer JWT → verify signature → issuer/audience
→ PackIdentity active? → credential_version valid?
→ dispatch active? (не superseded/завершён) → token expired?
→ permission present? → grant still effective in DB? (current-grant recheck)
→ tenant matches resource? → object in token scope?
→ ALLOW
```

Коды ответа:

| Ситуация | HTTP | reason в аудите |
|---|---|---|
| подпись/формат/exp/nbf | 401 | `token_invalid` |
| identity нет/disabled | 401 | `identity_disabled` |
| credential_version mismatch | 401 | `credential_version_mismatch` |
| jti в denylist / dispatch завершён | 401 | `token_revoked` |
| permission нет в claims | 403 | `permission_missing` |
| грант отозван в БД после выпуска | 403 | `grant_revoked` |
| объект другого tenant | **404** | `wrong_tenant` |
| свой tenant, но вне explicit scope | 403 | `object_out_of_scope` |

`404` для cross-tenant — API не должен работать oracle'ом существования
чужих данных (D3). Вне-scope объект своего tenant — `403`: существование в
своём tenant скрытием не считается. Реальный reason всегда в аудите,
независимо от возвращаемого кода.

**Current-grant recheck**: sensitive Context API при каждом запросе
перечитывает `effective(pack, tenant)` из БД — JWT это capability, но Core
способен отозвать право мгновенно (revoke customer.read во время выполнения
задачи останавливает доступ до истечения TTL).

### 5A.6 Dispatch contract Core → Pack

В payload dispatch добавляется capability-токен; транспортный Bearer
(`aud=pack:<name>`, 5.9.1) продолжает доказывать «отправитель — Core»:

```json
{ "task": {...}, "context": {...}, "workload_token": "eyJ..." }
```

Pack использует `workload_token` как Bearer при вызовах `/internal/context/*`.
С 5.9.3 Context API принимает **только** workload principal — без переходного
периода, обе стороны деплоятся вместе; service JWT остаётся на health /
handshake / `/internal/token` до этапа 5.9.4 (D5).

### 5A.7 Делегирование нельзя расширить

Дочерняя операция (tool/action/подdispatch) получает максимум права исходного
workload: `child permissions ⊆ parent permissions`, scope ⊆ parent scope.
Обратное невозможно by construction: новый workload token выдаёт только Core
при новом dispatch, а точки выдачи требуют явной операции из реестра.
Заложено для будущих agent→tool→pack цепочек.

### 5A.8 Replay-политика

Повтор задачи = новый dispatch: Core создаёт новые `task_id`(опц.),
`dispatch_id`, `jti`, workload token и проставляет связь
`replayed_from_task_id` в задаче. Старый workload JWT после завершения/
замены dispatch отклоняется проверкой «dispatch active?» (5A.5) даже до
истечения exp. Внутри живого dispatch jti переиспользуем (несколько context-
вызовов одной задачи); мгновенный kill-switch — Redis denylist
`workload:jti:{jti}` с TTL до exp (D6).

### 5A.9 Audit

Каждый отказ — `pack.workload.denied` c `pack_id, tenant_id, task_id,
dispatch_id, permission, resource_type, resource_id, jti, reason`
(reason из таблицы 5A.5). Каждый выпуск — `pack.workload.dispatched`
(dispatch_id, task_id, permissions, scope_mode). Отказы не возвращают
детали в ответе API — только коды выше.

### 5A.10 Миграция паков

AutoParts, Beauty, HelloPack: берут `workload_token` из payload dispatch и
передают его в вызовы Context API вместо service JWT. SDK/shared получает
хелпер `workload_bearer(payload)`. Обратная совместимость Context API со
service JWT **не предусматривается** (D5).

### 5A.11 Adversarial-матрица 5.9.3 (обязательные тесты)

| # | Провокация | Ожидание |
|---|---|---|
| W1 | Pack сам подставляет tenant B при получении токена | невозможно: `/internal/token` не выдаёт workload tokens |
| W2 | tenant A token → customer компании B | denied |
| W3 | token Conversation A → Conversation B того же tenant | denied |
| W4 | операция требует `customer.read`, его нет в claims | denied |
| W5 | permission была в JWT, но грант revoked | denied immediately (recheck БД) |
| W6 | credential_version изменён ротацией | denied |
| W7 | pack disabled | denied |
| W8 | expired JWT | denied |
| W9 | модификация scope | signature failure |
| W10 | replay старого JWT после нового dispatch | denied |
| W11 | valid token + собственный scoped объект | allowed |

Regression: webchat → Core → AutoParts Intake → Context API → clarification →
Core Conversation продолжает работать end-to-end.

### 5A.12 Обязательные инварианты (утверждены, проверяются тестами)

- **I1 — явный тип токена.** Каждый JWT, подписанный Core, несёт
  `token_type`: `service` | `workload` | `dispatch`. Наличие `tenant_id`/
  `task_id` тип не заменяет. `/internal/context/*` принимает только
  `token_type=workload`; pack-side verify dispatch-токена требует
  `token_type=dispatch`; service-endpoints требуют `service`. Убирает класс
  token-confusion атак между тремя видами токенов.
- **I2 — OPERATION_PERMISSIONS fail-closed.** Операция отсутствует в реестре
  → dispatch **запрещён** (ошибка задачи). Никогда «unknown → permissions=[] →
  продолжаем». Тест: каждая комбинация (пак × agent_type из манифестов)
  имеет запись в реестре.
- **I3 — TENANT_SCOPE_OPERATIONS allowlist.** `scope_mode=tenant` разрешён
  только операциям из явного allowlist в коде Core; попытка выпустить
  tenant-scope для операции вне списка → отказ dispatch. Default везде
  `explicit`.
- **I4 — правила TTL.** Дедлайн задачи ≤ now → workload token вообще не
  выпускается (dispatch отклоняется). При проверке leeway на clock-skew
  10 секунд; `exp` никогда не превышает дедлайн задачи.

Граница этапа: 5.9.3 доказывает модель на Context API; Actions/Memory/Tools
и остальные `/internal/*` закрываются тем же enforcement-механизмом в 5.9.4.

---

## 7. Совместимость и план перехода

| Этап | Core→Pack | Pack→Core |
|---|---|---|
| сейчас (v0.5.1) | `X-Internal-Token` | `X-Internal-Token` + `X-Pack-Name` |
| 5.9.1 | + подписанный dispatch token (когда материал смонтирован) | + service JWT через `POST /internal/token` (legacy тоже принимается) |
| 5.9.2–5.9.3 | dispatch token везде | workload JWT для данных; service JWT для service-level |
| 5.9.4 enforcement | только dispatch token | только JWT; legacy отклоняется |

Флаг совместимости `LEGACY_INTERNAL_TOKEN=true`. Пока он включён, каждое
принятие legacy-токена пишет audit-событие **`pack.auth.legacy_used`** —
забыть включённым флаг невозможно, видно в аудите. В конце спринта:
`environment=production && LEGACY_INTERNAL_TOKEN=true` → **startup failure**:
невозможно случайно выпустить production со старой дырой навсегда.

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
| 5.9.0 | этот документ: threat model + security contract (утверждён с поправками) | [x] |
| 5.9.1 | PackIdentity: модель, миграция, генерация секретов, one-time reveal, hash storage, rotation, revocation, credential_version, `POST /internal/token` → service JWT, per-pack dispatch credential, compose secrets | [x] |
| 5.9.2 | declared/granted permissions: миграция bootstrap для builtin-паков, admin API, effective-формула | [x] |
| 5.9.3a | workload delegation: спецификация (раздел 5A) — утверждена с инвариантами I1–I4 | [x] |
| 5.9.3b | workload/tenant delegation по разделу 5A: WorkloadTokenService, principal, Context API migration, current-grant recheck, audit, миграция паков | [x] |

**DoD 5.9.3** (юнит-тесты `test_workload_adversarial.py`, 14 шт. + `test_pack_context.py`
13 шт.; live-прогон 7/7):

- [x] I1 `token_type` на всех Core-signed JWT; Context API принимает только workload (service-JWT → 401 + аудит)
- [x] I2 fail-closed `OPERATION_PERMISSIONS`; unknown operation → dispatch запрещён
- [x] I3 tenant-scope только для allowlist-операций
- [x] I4 exp = min(TTL, deadline); deadline в прошлом → токен не выдаётся, dispatch отклонён
- [x] W1–W11 матрица (cross-tenant 404, out-of-scope 403, replay, revocation, rotation, grant-recheck)
- [x] active-dispatch binding (`pack_dispatches`), supersede при replay, терминальные статусы
- [x] аудит `pack.workload.dispatched` / `pack.workload.denied` с reason-enum
- [x] webchat round-trip на workload-токене (autoparts intake), jti+task_id зафиксированы
| 5.9.4 | enforcement всех `/internal/*`: только JWT, legacy off, коды ошибок | [ ] |
| 5.9.5 | audit/revocation: `pack.auth.legacy_used`, события грантов, UI отзывов | [ ] |
| 5.9.6 | EvilPack adversarial suite: автотесты A1–A10 | [ ] |

**DoD 5.9.1** (юнит-тесты `test_pack_identity.py`, 15 шт. + live-прогон 10/10):

- [x] AutoParts secret ≠ Beauty secret
- [x] bootstrap secret AutoParts → получает service JWT AutoParts
- [x] неверный секрет → 401
- [x] Beauty secret с заявкой `autoparts` → 401
- [x] после ротации старый секрет → 401
- [x] revoked identity → выдача токена 403
- [x] token со старым credential_version → отклонён
- [x] core→autoparts JWT (`aud=pack:autoparts`) принят автопартсом
- [x] тот же JWT → Beauty → отклонён
- [x] restart стека → identities/credentials остаются валидны
- [x] в БД и репозитории нет plaintext секретов

Провижининг dev-стека: админ → `POST /api/v1/packs/{name}/identity/provision`
→ записать оба plaintext-секрета в `.secrets/{pack}-bootstrap|.dispatch`
(gitignored; монтируется в core-api и паки как `/run/secrets/pack-credentials`).

**DoD 5.9.2** (юнит-тесты `test_pack_permissions.py`, 17 шт. + live-проверки):

- [x] bootstrap autoparts/beauty → 5+5 грантов, `grant_source=migration_bootstrap`, idempotent
- [x] новый пак: declared есть, granted/effective пустые
- [x] grant declared-разрешения → появляется в effective; revoke → мгновенно исчезает
- [x] грант без declaration (stale active-строка) → в effective не попадает; выдать undeclared нельзя (409)
- [x] неизвестное разрешение в манифесте → validation error при регистрации
- [x] upgrade добавил permission → остаётся pending, старые права работают, авто-гранта нет
- [x] удаление из манифеста при живом гранте → `inactive_not_declared` (строка хранится)
- [x] возврат LOW/MEDIUM → авто-восстановление; возврат HIGH → только явный re-grant админом
- [x] tenant-scoped грант компании A не действует для B; глобальный вид tenant-гранты игнорирует
- [x] RBAC: owner/superuser могут grant/revoke; manager → 403
- [x] аудит: `pack.permission.requested/.granted/.revoked/.removed_from_manifest` с reason/risk/tenant
- [x] EvilPack-провокация: манифест заявляет `order.create` → регистрация ок, effective пуст

Реализация: каталог 21 разрешения в коде (`app/core/pack_permissions.py`,
risk low/medium/high); `PackPermissionGrant` + `PackDeclaredPermission`
(софт-удаление через `removed_at`), миграция `e8f21b4c6a93` с bootstrap-SQL;
service-level `bootstrap_builtin()` для юнит-тестов; sync_declared вызывается
из `PackService.register`. Решение: enable() на гранты в этом спринте НЕ
гейтится — реальный запрет появится вместе с workload-токенами и enforcement
(5.9.3–5.9.4). Live: bootstrap-гранты подтверждены psql, roundtrip
revoke→re-grant `supplier.search` прошёл с аудитом.
