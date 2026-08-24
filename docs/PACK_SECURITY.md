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
| 5.9.2 | declared/granted permissions: миграция bootstrap для builtin-паков, admin API, effective-формула | [ ] |
| 5.9.3 | workload/tenant delegation: workload-токены при dispatch, Context API по ним, object-scope | [ ] |
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
