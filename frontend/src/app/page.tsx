"use client";

import Link from "next/link";
import { useApi } from "@/lib/useApi";
import type { Agent, DashboardStats, PilotAnalytics, Task, ToolInfo } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, StatCard, StatusBadge } from "@/components/ui";

const PIPELINE_LABELS: Record<string, string> = {
  process_customer_message: "Приём сообщения",
  search_parts: "Поиск запчастей",
  pricing_parts: "Расчёт цены",
  sales_draft: "Черновик КП",
};

export default function DashboardPage() {
  const stats = useApi<DashboardStats>("/dashboard");
  const tasks = useApi<Task[]>("/tasks?limit=6");
  const agents = useApi<Agent[]>("/agents");
  const tools = useApi<ToolInfo[]>("/settings/tools");
  const analytics = useApi<PilotAnalytics>("/analytics/pilot?days=7");

  if (stats.loading || tasks.loading) return <Loading />;
  if (stats.error || tasks.error) return <ErrorBox message={stats.error ?? tasks.error ?? ""} />;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-white">Обзор платформы</h1>
        <p className="mt-1 text-sm text-slate-500">
          Операционная система для цифровых сотрудников — запуск первого спринта.
        </p>
      </div>

      {stats.data && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
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
            <StatCard label="Выручка" value={`${analytics.data.revenue} ₽`} hint={`прибыль: ${analytics.data.gross_profit} ₽`} />
            <StatCard label="Заказы" value={analytics.data.orders_total} hint={`КП отправлено: ${analytics.data.quotes_sent}`} />
            <StatCard label="Запросы" value={analytics.data.requests_total} hint={`AI ответил: ${analytics.data.ai_handled}`} />
            <StatCard
              label="Передано менеджеру"
              value={`${analytics.data.handed_to_manager}`}
              hint={`перехват: ${analytics.data.takeover_rate}% · ответ ${analytics.data.avg_response_seconds ?? "—"}с`}
            />
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
                    {analytics.data.suppliers.attempts_total} попыток · ошибок {analytics.data.suppliers.failure_rate}%
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-200">Латентность</span>
                  <span className="text-slate-400">
                    avg {analytics.data.suppliers.avg_latency_ms !== null ? `${analytics.data.suppliers.avg_latency_ms}мс` : "—"} · p95 {analytics.data.suppliers.p95_latency_ms !== null ? `${analytics.data.suppliers.p95_latency_ms}мс` : "—"}
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
    </div>
  );
}
