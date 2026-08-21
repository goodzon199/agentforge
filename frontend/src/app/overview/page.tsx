"use client";

import Link from "next/link";
import { useApi } from "@/lib/useApi";
import type { PlatformOverview, UsageSummary } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, StatCard } from "@/components/ui";

export default function PlatformOverviewPage() {
  const overview = useApi<PlatformOverview>("/platform/overview");
  const usage = useApi<UsageSummary>("/platform/usage?days=30");

  if (overview.loading || usage.loading) return <Loading />;
  if (overview.error || usage.error) return <ErrorBox message={overview.error ?? usage.error ?? ""} />;
  if (!overview.data || !usage.data) return <Loading />;

  const o = overview.data;
  const t = usage.data.totals;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-white">Платформа</h1>
        <p className="mt-1 text-sm text-slate-500">
          Сводка по всем tenants, packs и цифровым сотрудникам AgentOS.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Компании" value={o.companies} hint="tenants на платформе" />
        <StatCard label="Агенты" value={o.agents} hint={`активных: ${o.agents_active}`} />
        <StatCard label="Packs" value={o.packs} hint={`активных: ${o.packs_active}`} />
        <StatCard label="Задачи" value={o.tasks} hint={`выполнено: ${o.tasks_completed}`} />
        <StatCard label="Workflows" value={o.workflows} hint="определений в packs" />
        <StatCard label="Tools" value={o.tools} hint="pack + core registry" />
        <StatCard label="Approvals" value={o.approvals_pending} hint="ждёт решения человека" />
        <StatCard
          label="LLM · 30 дней"
          value={t.llm_cost_rub.toFixed(2)}
          hint={`${t.llm_calls} вызовов · ${t.llm_tokens.toLocaleString("ru-RU")} токенов`}
        />
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-3">
        <div className="card p-5">
          <h3 className="text-sm font-medium text-slate-300">Быстрые ссылки</h3>
          <div className="mt-3 space-y-2 text-sm">
            <Link href="/packs" className="block rounded-lg px-3 py-2 text-accent-soft transition hover:bg-surface-hover">
              Реестр packs →
            </Link>
            <Link href="/approvals" className="block rounded-lg px-3 py-2 text-accent-soft transition hover:bg-surface-hover">
              Очередь approvals →
            </Link>
            <Link href="/workflows" className="block rounded-lg px-3 py-2 text-accent-soft transition hover:bg-surface-hover">
              Workflows по packs →
            </Link>
            <Link href="/usage" className="block rounded-lg px-3 py-2 text-accent-soft transition hover:bg-surface-hover">
              Usage и тарифы →
            </Link>
          </div>
        </div>

        <div className="lg:col-span-2">
          <h3 className="mb-3 text-sm font-medium text-slate-300">Потребление · 30 дней</h3>
          {usage.data.by_pack.length === 0 && usage.data.by_workflow.length === 0 ? (
            <EmptyState
              title="Метрик пока нет"
              description="Запустите workflow (Sprint 5.3) — usage появится здесь по уровням pack и workflow."
            />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              {usage.data.by_pack.length > 0 && (
                <div className="card p-0">
                  <div className="border-b border-surface-border px-5 py-3 text-xs font-medium uppercase tracking-wide text-slate-500">
                    По packs
                  </div>
                  <div className="divide-y divide-surface-border/60">
                    {usage.data.by_pack.map((p) => (
                      <div key={String(p.pack)} className="flex items-center justify-between px-5 py-2.5">
                        <span className="text-sm text-slate-200">{String(p.pack)}</span>
                        <span className="font-mono text-sm text-slate-400">{Number(p.workflow_runs)} runs</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {usage.data.by_workflow.length > 0 && (
                <div className="card p-0">
                  <div className="border-b border-surface-border px-5 py-3 text-xs font-medium uppercase tracking-wide text-slate-500">
                    По workflow
                  </div>
                  <div className="divide-y divide-surface-border/60">
                    {usage.data.by_workflow.map((w) => (
                      <div key={String(w.workflow)} className="flex items-center justify-between px-5 py-2.5">
                        <span className="text-sm text-slate-200">{String(w.workflow)}</span>
                        <span className="font-mono text-sm text-slate-400">{Number(w.workflow_runs)} runs</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
