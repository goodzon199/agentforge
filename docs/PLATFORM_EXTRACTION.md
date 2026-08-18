# Sprint 5.0 — Platform Extraction: Core ↔ AutoParts microservice split

Status: DRAFT (branch `sprint-5-platform-extraction`; live stays on `main` v0.4.7)

Goal: split the monolith into two deployable services with separate databases,
moving ALL automotive-domain logic out of the platform core. Core must run and
pass tests with zero knowledge of parts/quotes/orders.

---

## 1. Service boundaries

### core-service (platform)
Runs its own FastAPI app + `core-db`. Owns identity, workforce, task engine,
dialogues, audit, analytics, quality, settings, tracing, memory.

**Models (core-db):** base, enums, company, user, agent, agent_action,
agent_feedback, task, dead_task, llm_usage, memory, knowledge_entries,
conversation, conversation_message, audit_event, prompt_version, trace, customer.

**Services:** agent_service, agent_quality_service, task_service, user_service,
company_service, conversation_service, chat_service, audit_service,
analytics_service (auto-parts metrics removed), prompt_service,
company_policy_service, audit_context, shadow_service (shadow dashboard =
platform feature comparing AI vs manager; keep in core).

**Agents:** base, system, email, registry (platform agents only).

**API:** auth, users, agents, tasks, conversations, audit, analytics, quality,
settings, permissions, logs, ops, traces, dashboard, companies,
company_policies, manager, chat.

**Platform packages:** core/, llm/, memory/, tools/, tracing/, reliability/,
orchestrator/ (task engine only, no domain handler imports).

### autoparts-service (domain)
Runs its own FastAPI app + `autoparts-db`. Owns the parts journey:
request → search → pricing → quote → approval → order → supplier → tracking.

**Models (autoparts-db):** part_request, supplier, supplier_offer,
supplier_search, quote, order, fitment, vehicle, supplier_fulfillment,
shadow_comparison, part_return, cross_reference, catalog_fitment,
fitment_evidence.

**Services:** part_request_service, parts_search_service, pricing_service,
quote_service, sales_service, order_service, supplier_service,
supplier_order_service, supplier_reliability_service, offer_ranking_service,
fitment_service, garage_service, vin_decode, quote_guard, auto_send_service,
intake_service, manager_dashboard_service (domain metrics).

**Agents:** intake, search, pricing, sales.

**API:** part_requests, suppliers, quotes, orders, supplier_orders, fitment,
garage + internal-only endpoints (see §3).

**Package:** suppliers/ (entire adapter layer).

---

## 2. Cross-cutting dependencies to BREAK (today: monolith)

| # | Today (file:line) | Direction | After split |
|---|-------------------|-----------|-------------|
| 1 | `core/seeding.py:12,235,436,514` imports domain models/services | core→domain | split into `core-seed` + `autoparts-seed` |
| 2 | `orchestrator/worker.py:53` imports `parts_search_service` | core→domain | orchestrator dispatches by task intent via internal HTTP/event |
| 3 | `conversation_service.py:208` imports `order_service` (accept-on-confirm) | core→domain | core emits "customer-confirmed" event; autoparts consumes |
| 4 | `analytics_service.py:366` imports `auto_send_service` | core→domain | move auto-send metrics into autoparts analytics endpoint |
| 5 | `agents/registry.py` transitively pulls domain agents | core→domain | registry built per-service; orchestrator resolves handlers via contract |
| 6 | `sales_service.py:70` imports `app.api.access` | domain→core | move `company_allowed` into a shared contract package |
| 7 | `schemas/users.py` imports `user_service.ROLES` | schemas→services | move ROLES into core models/enums |
| 8 | `quote_service.py:134` imports orchestrator | domain→core | use core task/client stub, not direct import |
| 9 | `conversation_service` ↔ `order_service` circular (lazy import) | domain↔core | resolved by event contract |

Shared contract package: `shared/` (pure Python, no SQLAlchemy models, no
services): enums subset, id/role constants, event schemas, HTTP client for
internal API. Both services depend on it.

---

## 3. Inter-service contract (internal HTTP, token-gated)

Core → Autoparts:
- `POST /internal/parts/search` (intent: search)
- `POST /internal/parts/price`  (intent: pricing)
- `POST /internal/quotes/prepare-draft` (intent: sales draft)
- `POST /internal/quotes/send` (intent: sales send / approval)
- `POST /internal/conversations/on-customer-reply` (intent: domain handling of a customer message)

Autoparts → Core:
- `GET /internal/company/{id}` (policy/company context)
- `POST /internal/audit/event` (append audit)
- `POST /internal/tasks/complete` (report handler completion)
- `GET /internal/agent/{id}` (agent identity for domain work)

Internal auth: shared `INTERNAL_API_TOKEN` (env), `X-Internal-Token` header,
checked by middleware in both services. Public API never exposed internally.

---

## 4. Database split

Two Postgres databases, two alembic trees:
- `services/core/alembic` → core-db (tables in §1 Core)
- `services/autoparts/alembic` → autoparts-db (tables in §1 AutoParts)

No cross-db FK constraints. Cross-service references are UUID columns only
(conversation_id, customer_id, order_id, quote_id, part_request_id) with no
FK — integrity enforced at the service boundary + audit trail.

Migration strategy: keep the existing single `alembic/versions/` tree frozen
on `main` (v0.4.7). On this branch create two new alembic trees seeded from
the current head schema split by table, so both new DBs bootstrap clean.

---

## 5. Directory layout

```
backend/
  shared/                  # contract package (pure, no models/services)
    pyproject.toml
    shared/__init__.py
    shared/events.py       # event schemas (dataclasses/pydantic)
    shared/roles.py        # role/status constants
    shared/internal.py     # HTTP client + token guard helpers
  services/
    core/
      pyproject.toml, requirements.txt, Dockerfile
      alembic/             # core-db migrations
      app/                 # FastAPI app (moved platform code)
      tests/
    autoparts/
      pyproject.toml, requirements.txt, Dockerfile
      alembic/             # autoparts-db migrations
      app/                 # FastAPI app (moved domain code)
      tests/
  docker-compose.services.yml   # core-api, autoparts-api, db-core, db-autoparts
```

`app/`, `alembic/` (old), `tests/` stay on `main` for v0.4.7; this branch
builds the new layout alongside, then the old app is removed only when both
services pass E2E.

---

## 6. Execution order

1. [x] manifest accepted (this doc)
2. [x] `shared/` contract package
3. [x] split `seeding.py` into core-seed / autoparts-seed
4. [x] core-service skeleton: models, services, api (no domain imports)
5. [x] autoparts-service skeleton: models, services, api
6. [x] two alembic trees, clean bootstrap on both DBs
7. [x] internal HTTP contract + auth token
8. [x] orchestration dispatch via contract (remove worker.py:53 direct import)
9. [x] event: customer-confirmed (breaks #3)
10. [x] docker-compose.services.yml: core-api, autoparts-api, db-core, db-autoparts
11. [x] HelloPack: minimal domain package example (endpoint + service + test)
12. [ ] DoD: core tests pass without autoparts; autoparts tests pass; E2E green

## 7. Acceptance (DoD)

- [x] `core-service` test suite green with NO import from autoparts
- [x] `autoparts-service` test suite green
- [x] both DBs bootstrap from empty via `alembic upgrade head`
- [x] live-equivalent E2E: chat → intake → search → pricing → quote → send → order (two services)
- [x] HelloPack demo endpoint responds
- [x] `git grep autoparts` in core-service app/ = 0 (except shared/)

---

## 8. Sprint 5.1 — Pack SDK + Manifest

Standard for connecting a new vertical (Pack) to AgentOS identically.

### Manifest (`shared/pack.py` + pack's `manifest.yaml`)

```yaml
name: autoparts
version: 1.0.0
display_name: AutoParts
agents: [{type, display_name}, ...]
permissions: [customer.read, ...]
workflows: [{name, version}, ...]
tools: [supplier_search, ...]
required_core_version: ">=0.5.0"
```

### Core operations (no core code change per pack)

- `discover` — fetch `/internal/pack/manifest` from every `PACK_BASE_URLS` entry, upsert into `packs`
- `validate` — shared SDK schema + semver check against `required_core_version`
- `register` — manual offline registration from a submitted manifest
- `enable` / `disable` — lifecycle state, enable gated by live healthcheck
- `healthcheck` — probe `/internal/health`, record `last_health_ok`

### Notes

- `shared.pack` = pure SDK (pydantic + yaml), no SQLAlchemy; both core and packs import it
- `packs` table (core-db) stores only the contract: name/version/base_url/manifest/state
- orchestrator `_pack_base_url_for()` routes a domain agent to the active pack that declares it
- `traces.root_span_id` FK drift fixed (separate migration `7e95954f104a`)

---

## 9. Sprint 5.2 — Pack Lifecycle

Full lifecycle so a new vertical is installable/configurable/mutable by core
without manual DB work.

### Pack model + config

- `packs.config` JSON column (migration `4dd25de42969`) — per-pack operator config
- state machine `_TRANSITIONS` + `_guard`: installed → configured → active ↔ disabled,
  upgrade → upgrade_required, uninstall → removed (only from a stable state)

### Operations

- `configure` — write `config`, requires `installed` or `configured`
- `upgrade` — POST `/internal/pack/migrate` (pack runs its own alembic `upgrade head`),
  bumps version from the manifest, returns to `configured` (not auto-active)
- `uninstall` — removes the pack row

### Pack side

- `app/core/pack_migrations.py` — `upgrade_to_head()`, `current_revision()`
- `/internal/pack/migrate` (POST) — applies pack migrations, returns `{revision}`

### API (manager-guarded)

- `POST /api/v1/packs/{name}/configure`, `POST .../{name}/upgrade`, `DELETE .../{name}`

---

## 10. Sprint 5.3 — Declarative Workflow Runtime

Packs ship ready business processes as YAML DAGs; core executes them without
knowing the domain, dispatching agent nodes back over the internal contract.

### Workflow SDK (`shared/workflow.py`)

```yaml
name: sales_pipeline
version: 1.0.0
start: intake
nodes:
  - {id: intake, type: agent, agent: intake, next: classify}
  - {id: classify, type: condition,
     expression: "context.get('requires_search', False)",
     branches: {true: search, false: human}}
  - {id: approval, type: human, message: "Согласуйте с клиентом"}
  - {id: done, type: end}
```

- `Workflow`/`WorkflowNode`, NodeType = agent | condition | human | end
- `parse_workflow` / `load_workflow` / `validate_workflow` (start reachability,
  branch targets exist, agent nodes declare an agent)
- `evaluate_condition` — safe AST evaluator: only dict.get(), comparisons, bool ops,
  subscript/attribute access; calls beyond dict.get raise `ConditionError`

### Pack side

- `workflows/sales_pipeline.yaml` shipped in the pack
- `GET /internal/pack/workflows` — serves all `workflows/*.yaml`

### Core runtime (`services/workflow_service.py`)

- `load_from_pack` / `load_named` — fetch + validate workflows over internal contract
- `run()` walks the DAG:
  - agent → `POST /internal/agents/execute` on the active pack that declares the agent;
    returned `data` is folded (deep-copied) into the run context
  - condition → `evaluate_condition` over the run context, follow `branches`
  - human → record `AgentAction(action_type=workflow_human, pending,
    requires_approval=True)`, pause the run (`awaiting_approval` + `paused_at`)
  - end → terminal
- cycle detection per run; unknown start/targets raise `WorkflowRuntimeError`
- API (manager-guarded): `GET /api/v1/workflows/{pack}/workflows`,
  `POST /api/v1/workflows/{pack}/{workflow}/run` (task_id required)

### E2E verified (live, core:8011 / autoparts:8012)

- `requires_search=false` → intake → classify → human/end
- `requires_search=true` → intake → search → pricing → approval(human) →
  awaiting_approval, `agent_actions` row recorded
## 11. Sprint 5.4 — Agent/Tool SDK

Платформа, когда разработчик пишет агента, не зная внутренностей Core или
пака. Всё, что нужно знать — это `ctx` (AgentContext).

```python
from shared.agents import Agent, AgentContext, AgentOutput

class LeadAgent(Agent):
    name = "lead-agent"
    permissions = ["crm.read", "crm.write"]

    def execute(self, ctx: AgentContext) -> AgentOutput:
        ctx.permissions.require("crm.read")
        rows = ctx.tools.run("crm.search", query=ctx.input_data.get("q"))
        ctx.memory.remember(f"searched {ctx.objective}")
        return AgentOutput(response="done", data={"rows": rows.data})
```

### Shared SDK (`shared/agents.py`, `shared/tools.py`) — pure Python, pydantic only

- `Agent` — kind/name/description/permissions/tools/model/temperature ClassVars,
  abstract `execute(ctx)`; `describe()` для интроспекции
- `AgentContext` — objective/input_data/agent/agent_id/company_id/task_id + 8 фасадов:
  memory, tools, actions, permissions, approvals, trace, llm, events; `require_permission`
- `AgentOutput` — response/data/routing_decision/handoff_agent
- `AgentRegistry` — `register(kind)`/`get`/`require`/`kinds`/`describe_all`
- `run_agent(agent, ctx)` — поддерживает sync и async `execute` (`asyncio.run` для coroutine)
- `Tool` / `ToolResult` / `ToolRegistry` — декларативные инструменты пака

### Pack side (autoparts) — facades поверх сервисов пака

- `app/agents/context.py` — AgentMemory (remember/learn/recall/search/knowledge),
  AgentTools, AgentActions (AgentAction rows), AgentPermissions (manifest.yaml +
  record), AgentApprovals (pending approval_request), AgentTrace, AgentEvents
- `app/agents/base.py` — `BaseAgent(SDKAgent)`: legacy-конструктор
  `(record, memory, tools, llm, db)`, `build_context(objective, input_data, task_id, company_id)`
  собирает AgentContext с фасадами, `run(ctx)` делегирует в `execute(ctx)`
  (инстансные аксессоры `record_name`/`record_slug`/... не затеняют ClassVars SDK)
- все 6 агентов пака (system/email/search/intake/pricing/sales) переведены на
  контракт `execute(self, ctx)`
- `app/agents/registry.py` — `AgentRegistry(SDKAgentRegistry)`, резолв по `kind`
- `app/tools/{base,registry}.py` — PackToolRegistry на shared Tool SDK

### Точки входа переведены на SDK

- `POST /internal/agents/execute` — build_context + `run_agent`
- orchestrator `_run_pipeline` — build_context + `run_agent` для system и target

### Тесты

- shared: `tests/test_agent_sdk.py` (6) — registry/describe, run с ctx, async,
  noop-фасады, unknown kind, tool registry
- autoparts: `tests/test_agent_sdk_integration.py` (7) — registry describe,
  build_context wires facades, actions/approvals запись, permissions gate из
  manifest, run_agent через SDK, deny unknown permission

### Live E2E (core:8011 / autoparts:8012)

- `/internal/agents/execute` system -> SearchAgent (SDK contract, rules engine)
- workflow `sales_pipeline` `requires_search=false` — intake -> classify -> human/end
- `requires_search=true` — intake -> search(SDK) -> pricing(SDK) -> approval(human,
  awaiting_approval, AgentAction workflow_human pending recorded)
