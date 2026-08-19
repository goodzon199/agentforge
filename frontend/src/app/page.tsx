"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getStoredUser } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type {
  Agent,
  DashboardStats,
  ManagerDashboard,
  PilotAnalytics,
  QueueItem,
  Sprint39Report,
  Task,
  ToolInfo,
} from "@/lib/types";
import { EmptyState, ErrorBox, Loading, StatCard, StatusBadge } from "@/components/ui";

const PIPELINE_LABELS: Record<string, string> = {
  process_customer_message: "Приём сообщения",
  search_parts: "Поиск запчастей",
  pricing_parts: "Расчёт цены",
  sales_draft: "Черновик КП",
};

const ACTION_LABEL: Record<string, string> = {
  reply: "Ответить",
  confirm: "Подтвердить",
  open: "Открыть",
};

function ActionButton({ item }: { item: QueueItem }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const label = ACTION_LABEL[item.action] ?? "Открыть";

  async function run() {
    if (busy) return;
    setBusy(true);
    try {
      if (item.action === "reply") {
        router.push(`/conversations?open=${item.conversation_id}`);
      } else if (item.action === "confirm" && item.approval_id) {
        await api.post(`/approvals/${item.approval_id}/approve`, {});
        window.location.reload();
      } else {
        router.push(`/conversations?open=${item.conversation_id}`);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <button className="btn-primary" disabled={busy} onClick={run}>
      {label}
    </button>
  );
}

function QueueCard({ queue }: { queue: QueueItem[] }) {
  if (!queue.length) {
    return <EmptyState title="Всё сделано" description="Нет заявок, требующих вашего внимания." />;
  }
  return (
    <div className="card divide-y divide-surface-border p-0">
      {queue.map((item, i) => (
        <div key={`${item.type}-${item.part_request_id ?? item.conversation_id ?? item.approval_id ?? i}`} className="flex items-center justify-between gap-4 px-5 py-3">
          <div className="min-w-0">
            <div className="truncate text-sm text-slate-200">{item.title}</div>
            <div className="mt-0.5 truncate text-xs text-slate-500">
              {[item.customer, item.part, item.vehicle].filter(Boolean).join(" · ") || "—"}
            </div>
          </div>
          <ActionButton item={item} />
        </div>
      ))}
    </div>
  );
}

function Row({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "good" | "warn" | "bad" }) {
  const color =
    tone === "good" ? "text-emerald-400" : tone === "warn" ? "text-amber-400" : tone === "bad" ? "text-rose-400" : "text-slate-200";
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-2.5">
      <div className="min-w-0">
        <div className="text-sm text-slate-300">{label}</div>
        {hint ? <div className="mt-0.5 text-xs text-slate-500">{hint}</div> : null}
      </div>
      <div className={`font-mono text-sm font-medium ${color}`}>{value}</div>
    </div>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-surface-border px-5 pb-1 pt-3">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{title}</div>
      <div className="mt-2 divide-y divide-surface-border/60">{children}</div>
    </div>
  );
}

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value}%`;
}

function Sprint39Table({ report }: { report: Sprint39Report }) {
  const unchangedRate = report.manager_unchanged_send;
  const autoError = report.auto_send_error_rate;
  return (
    <div className="card p-0">
      <div className="flex items-center justify-between px-5 py-4">
        <div>
          <h3 className="text-sm font-medium text-slate-200">Sprint 3.9 · Pilot 500</h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Цель {report.target_requests} заявок · реально {report.real_requests} · осталось {report.remaining_to_target}
          </p>
        </div>
        {report.real_requests >= report.target_requests ? (
          <span className="badge bg-emerald-500/15 text-emerald-400">Пилот завершён</span>
        ) : (
          <span className="badge bg-accent/15 text-accent-soft">В работе</span>
        )}
      </div>

      <Group title="Воронка">
        <Row label="Real requests" value={String(report.real_requests)} hint="заявок в пилоте" />
        <Row label="Intake accuracy" value={pct(report.intake_accuracy)} hint="заявок структурировано без вопросов" />
        <Row label="Search success" value={pct(report.search_success)} hint="запусков поиска с офферами" />
        <Row label="Correct fitment" value={pct(report.correct_fitment)} hint="подтверждена совместимость по VIN/авто" />
        <Row label="Quotes generated" value={pct(report.quotes_generated)} hint="квот на заявку" />
        <Row label="QuoteGuard pass" value={pct(report.quote_guard_pass)} hint="квот прошли проверку" />
      </Group>

      <Group title="Цикл менеджера">
        <Row
          label="Manager unchanged send"
          value={pct(unchangedRate)}
          hint="отправлено без правок"
          tone={unchangedRate !== null && unchangedRate >= 85 ? "good" : unchangedRate !== null ? "warn" : undefined}
        />
        <Row label="Manager edited" value={pct(report.manager_edited)} hint="с правками менеджера" />
        <Row label="Manager rejected" value={pct(report.manager_rejected)} hint="отклонено менеджером" />
      </Group>

      <Group title="Controlled Auto">
        <Row label="Auto eligible" value={pct(report.controlled_auto_eligible)} hint="квот с зелёными проверками" />
        <Row label="Auto successfully sent" value={pct(report.controlled_auto_sent)} hint="отправлено без человека" />
        <Row
          label="Auto-send error rate"
          value={pct(autoError)}
          hint="отказы / отклонения после авто-отправки"
          tone={autoError !== null && autoError <= 2 ? "good" : autoError !== null && autoError <= 10 ? "warn" : "bad"}
        />
      </Group>

      <Group title="Отклик">
        <Row label="Average response time" value={report.avg_response_seconds !== null ? `${report.avg_response_seconds}с` : "—"} />
        <Row label="P95 response time" value={report.p95_response_seconds !== null ? `${report.p95_response_seconds}с` : "—"} />
      </Group>

      <Group title="Конверсия">
        <Row label="Quote → accepted" value={pct(report.quote_to_accepted)} hint="квот принято клиентом" />
        <Row label="Accepted → order" value={pct(report.accepted_to_order)} hint="принято квот стало заказом" />
        <Row label="Revenue" value={`${report.revenue} ₽`} />
        <Row label="Gross profit" value={`${report.gross_profit} ₽`} />
      </Group>

      <Group title="Стоимость">
        <Row label="LLM cost/request" value={`${report.llm_cost_per_request} ₽`} />
        <Row label="Infrastructure cost/request" value={`${report.infra_cost_per_request} ₽`} />
        <Row label="Total cost/request" value={`${report.total_cost_per_request} ₽`} />
      </Group>

      <Group title="Автоматизация">
        <Row label="Human takeover" value={pct(report.human_takeover)} hint="диалогов передано человеку" />
        <Row label="Full automation" value={pct(report.full_automation)} hint="диалогов без участия человека" />
      </Group>
    </div>
  );
}

export default function DashboardPage() {
  const manager = useApi<ManagerDashboard>("/manager/dashboard");
  const [isSuperuser, setIsSuperuser] = useState(false);

  const stats = useApi<DashboardStats>(isSuperuser ? "/dashboard" : null);
  const tasks = useApi<Task[]>(isSuperuser ? "/tasks?limit=6" : null);
  const agents = useApi<Agent[]>("/agents");
  const tools = useApi<ToolInfo[]>("/settings/tools");
  const analytics = useApi<PilotAnalytics>(isSuperuser ? "/analytics/pilot?days=7" : null);

  useEffect(() => {
    setIsSuperuser(getStoredUser<{ is_superuser?: boolean }>()?.is_superuser === true);
  }, []);

  if (manager.loading) return <Loading />;
  if (manager.error) {
    return (
      <div>
        <ErrorBox message={manager.error} />
        {isSuperuser ? <p className="mt-4 text-sm text-slate-500">Показ данных платформы для администратора.</p> : null}
      </div>
    );
  }
  if (!manager.data) return <Loading />;

  const attention = manager.data.attention;
  const today = manager.data.today;
  const hasAttention = attention.client_waiting_reply + attention.approval_pending + attention.ai_unsure + attention.supplier_error > 0;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-white">Рабочий стол менеджера</h1>
        <p className="mt-1 text-sm text-slate-500">
          Что требует внимания · что сделал AI сегодня · очередь действий.
        </p>
      </div>

      {/* 1. Attention */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-300">Требуется внимание</h2>
          {hasAttention ? (
            <span className="badge bg-amber-500/15 text-amber-400">есть задачи</span>
          ) : (
            <span className="badge bg-emerald-500/15 text-emerald-400">всё под контролем</span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard
            label="Клиент ждёт ответа"
            value={attention.client_waiting_reply}
            hint="диалоги без последнего ответа"
          />
          <StatCard
            label="Quote на подтверждение"
            value={attention.approval_pending}
            hint="отправка ждёт решения"
          />
          <StatCard
            label="AI не уверен"
            value={attention.ai_unsure}
            hint="заявки с низкой уверенностью"
          />
          <StatCard
            label="Ошибки поставщиков"
            value={attention.supplier_error}
            hint="сбои за сегодня"
          />
        </div>
      </section>

      {/* 2. Today */}
      <section className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-300">Что сделал AI сегодня</h2>
          <span className="text-xs text-slate-500">накопительно за сутки</span>
        </div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <StatCard label="Заявки" value={today.requests} />
          <StatCard label="Подборы" value={today.selections} />
          <StatCard label="Quote" value={today.quotes} />
          <StatCard label="Отправлено клиенту" value={today.sent} />
          <StatCard label="Заказы" value={today.orders} />
        </div>
      </section>

      {/* 3. Queue */}
      <section className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-300">Очередь действий</h2>
          <Link href="/conversations" className="text-xs text-accent-soft hover:underline">
            Все диалоги →
          </Link>
        </div>
        <QueueCard queue={manager.data.queue} />
      </section>

      {/* Shadow mode status */}
      <section className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-300">Shadow Mode</h2>
          <span className="text-xs text-slate-500">AI работает параллельно с менеджером</span>
        </div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Сравнений" value={manager.data.shadow.total} hint={`лимит пилота: ${manager.data.shadow.limit}`} />
          <StatCard label="Оценено" value={manager.data.shadow.completed} hint={`в работе: ${manager.data.shadow.pending}`} />
          <StatCard label="Совпадение деталей" value={manager.data.shadow.part_match_pct !== null ? `${manager.data.shadow.part_match_pct}%` : "—"} />
          <StatCard label="Совпадение OEM" value={manager.data.shadow.oem_match_pct !== null ? `${manager.data.shadow.oem_match_pct}%` : "—"} />
        </div>
      </section>

      {/* Assist mode: AI drafts, manager approves */}
      <section className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-300">Assist Mode · 30 дней</h2>
          <span className="text-xs text-slate-500">AI готовит КП, менеджер проверяет и отправляет</span>
        </div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Отправлено КП" value={manager.data.assist.sends_total} hint={`без правок: ${manager.data.assist.sends_unchanged}`} />
          <StatCard label="С правками менеджера" value={manager.data.assist.sends_edited} />
          <StatCard
            label="Доля без правок"
            value={manager.data.assist.manager_edit_rate !== null ? `${manager.data.assist.manager_edit_rate}%` : "—"}
            hint={manager.data.assist.manager_edit_rate !== null ? "агент готовит, менеджер не правит" : "пока нет отправок"}
          />
          <StatCard label="Отклонено" value={manager.data.assist.sends_rejected} />
        </div>
      </section>

      {isSuperuser ? (
        <>
          {stats.data && (
            <div className="mt-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard label="Компании" value={stats.data.companies} />
              <StatCard label="Агенты" value={stats.data.agents} hint={`активных: ${stats.data.agents_active}`} />
              <StatCard label="Задачи" value={stats.data.tasks} hint={`выполнено: ${stats.data.tasks_completed}`} />
              <StatCard label="События логов" value={stats.data.logs_total} hint={`ошибок: ${stats.data.tasks_failed}`} />
            </div>
          )}

          {analytics.data && (
            <div className="mt-8">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-medium text-slate-300">Пилотная аналитика · 7 дней</h2>
                <span className="text-xs text-slate-500">деньги, SLA и конверсия</span>
              </div>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <StatCard
                  label="Выручка"
                  value={analytics.data.revenue != null ? `${analytics.data.revenue} ₽` : "—"}
                  hint={analytics.data.gross_profit != null ? `прибыль: ${analytics.data.gross_profit} ₽` : undefined}
                />
                <StatCard
                  label="Заказы"
                  value={analytics.data.orders_total ?? "—"}
                  hint={analytics.data.quotes_sent != null ? `КП отправлено: ${analytics.data.quotes_sent}` : undefined}
                />
                <StatCard label="Запросы" value={analytics.data.requests_total ?? "—"} hint={`AI ответил: ${analytics.data.ai_handled ?? 0}`} />
                <StatCard
                  label="Передано менеджеру"
                  value={`${analytics.data.handed_to_manager ?? 0}`}
                  hint={`перехват: ${analytics.data.takeover_rate ?? 0}% · ответ ${analytics.data.avg_response_seconds ?? "—"}с`}
                />
              </div>

              <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
                <StatCard
                  label="Авто-отправки КП"
                  value={analytics.data.assist?.auto_sends ?? 0}
                  hint="Controlled Auto: AI отправил без менеджера"
                />
                <StatCard
                  label="Отправлено без правок"
                  value={analytics.data.assist?.sends_unchanged ?? 0}
                  hint={`доля: ${analytics.data.assist?.manager_edit_rate ?? 0}%`}
                />
                <StatCard label="С правками" value={analytics.data.assist?.sends_edited ?? 0} />
                <StatCard label="Всего отправок" value={analytics.data.assist?.sends_total ?? 0} />
              </div>

              <div className="mt-6 grid gap-4 lg:grid-cols-2">
                <div className="card p-5">
                  <h3 className="text-sm font-medium text-slate-300">Конвейер и SLA</h3>
                  <div className="mt-4 space-y-3">
                    {analytics.data.pipeline.map((p) => {
                      const ok = p.on_sla_pct !== null && p.on_sla_pct >= 95;
                      return (
                        <div key={p.objective}>
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-slate-200">{PIPELINE_LABELS[p.objective] ?? p.objective}</span>
                            <span className={ok ? "text-emerald-400" : "text-amber-400"}>
                              {p.avg_seconds !== null ? `${p.avg_seconds.toFixed(2)}с` : "—"} / SLA {p.sla_seconds}с
                            </span>
                          </div>
                          <div className="mt-1 flex items-center justify-between text-xs text-slate-500">
                            <span>p95 {p.p95_seconds !== null ? `${p.p95_seconds.toFixed(2)}с` : "—"} · в SLA {p.on_sla_pct !== null ? `${p.on_sla_pct}%` : "—"}</span>
                            <span>{p.count} задач{p.failed ? ` · ${p.failed} ошибок` : ""}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="card p-5">
                  <h3 className="text-sm font-medium text-slate-300">Поставщики и LLM</h3>
                  <div className="mt-4 space-y-3 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="text-slate-200">Поставщики</span>
                      <span className="text-slate-400">
                        {analytics.data.suppliers
                          ? `${analytics.data.suppliers.attempts_total} попыток · ошибок ${analytics.data.suppliers.failure_rate}%`
                          : "—"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-slate-200">Латентность</span>
                      <span className="text-slate-400">
                        {analytics.data.suppliers
                          ? `avg ${analytics.data.suppliers.avg_latency_ms !== null ? `${analytics.data.suppliers.avg_latency_ms}мс` : "—"} · p95 ${analytics.data.suppliers.p95_latency_ms !== null ? `${analytics.data.suppliers.p95_latency_ms}мс` : "—"}`
                          : "—"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-slate-200">LLM-вызовы</span>
                      <span className="text-slate-400">
                        {analytics.data.llm.calls} · ошибок {analytics.data.llm.failure_rate}% · {analytics.data.llm.available ? "доступен" : "оффлайн"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between border-t border-surface-border pt-3">
                      <span className="text-slate-200">Таймауты задач</span>
                      <span className={analytics.data.task_timeouts > 0 ? "text-rose-400" : "text-slate-400"}>{analytics.data.task_timeouts}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {analytics.data?.sprint39 ? (
            <div className="mt-8">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-medium text-slate-300">Таблица Pilot 500</h2>
                <span className="text-xs text-slate-500">все метрики спринта 3.9 в одном отчёте</span>
              </div>
              <Sprint39Table report={analytics.data.sprint39} />
            </div>
          ) : null}

          <div className="mt-8 grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-medium text-slate-300">Последние задачи</h2>
                <Link href="/tasks" className="text-xs text-accent-soft hover:underline">
                  Все задачи →
                </Link>
              </div>
              {tasks.data && tasks.data.length === 0 ? (
                <EmptyState
                  title="Задач пока нет"
                  description="Создайте первую задачу — SystemAgent получит её и определит нужного агента."
                />
              ) : (
                <div className="card divide-y divide-surface-border p-0">
                  {tasks.data?.map((t) => (
                    <div key={t.id} className="flex items-center justify-between gap-4 px-5 py-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm text-slate-200">{t.title}</div>
                        <div className="mt-0.5 truncate text-xs text-slate-500">{t.objective}</div>
                      </div>
                      <StatusBadge status={t.status} />
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-medium text-slate-300">Агенты</h2>
                <Link href="/agents" className="text-xs text-accent-soft hover:underline">
                  Все →
                </Link>
              </div>
              <div className="space-y-2">
                {agents.data?.map((a) => (
                  <div key={a.id} className="card flex items-center gap-3 py-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/20 text-xs font-bold text-accent-soft">
                      {a.name.slice(0, 2)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm text-slate-200">{a.name}</div>
                      <div className="truncate text-xs text-slate-500">{a.role}</div>
                    </div>
                    <StatusBadge status={a.status} />
                  </div>
                ))}
              </div>

              <div className="mt-6">
                <h2 className="mb-3 text-sm font-medium text-slate-300">Инструменты</h2>
                <div className="card py-3">
                  {tools.data?.map((t) => (
                    <div key={t.name} className="flex items-center justify-between border-b border-surface-border py-2 last:border-0">
                      <span className="font-mono text-xs text-slate-300">{t.name}</span>
                      <span className="badge bg-accent/15 text-accent-soft">v{t.version}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
