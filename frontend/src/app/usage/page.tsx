"use client";

import { useState } from "react";
import { useApi } from "@/lib/useApi";
import type { UsageSummary } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader, StatCard } from "@/components/ui";

const TARIFFS = [
  { name: "Platform", price: 4990, desc: "базовый: core, packs, approvals, usage" },
  { name: "AutoParts", price: 7990, desc: "вертикаль автозапчастей: поиск, КП, заказы" },
  { name: "Beauty", price: 4990, desc: "вертикаль салона красоты: брони, напоминания" },
];

export default function UsagePage() {
  const [days, setDays] = useState(30);
  const { data, loading, error } = useApi<UsageSummary>(`/platform/usage?days=${days}`);

  return (
    <div>
      <SectionHeader
        title="Usage · метрики и тарифы"
        action={
          <div className="flex items-center gap-1">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`rounded-md px-3 py-1.5 text-xs transition ${
                  days === d ? "bg-accent/15 font-medium text-accent-soft" : "text-slate-400 hover:bg-surface-hover"
                }`}
              >
                {d}д
              </button>
            ))}
          </div>
        }
      />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : !data ? (
        <Loading />
      ) : (
        <div className="space-y-8">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="LLM токены" value={data.totals.llm_tokens.toLocaleString("ru-RU")} hint={`${data.totals.llm_calls} вызовов`} />
            <StatCard label="LLM стоимость" value={`${data.totals.llm_cost_rub.toFixed(2)} ₽`} hint="за период" />
            <StatCard label="Задачи" value={data.totals.tasks_total} hint={`выполнено ${data.totals.tasks_completed} · ошибок ${data.totals.tasks_failed}`} />
            <StatCard label="Workflow runs" value={data.totals.workflow_runs} />
            <StatCard label="Agent executions" value={data.totals.agent_executions} hint={`tool calls: ${data.totals.tool_calls}`} />
            <StatCard label="Approvals" value={data.totals.approvals_pending} hint={`решено за период: ${data.totals.approvals_decided}`} />
            <StatCard
              label="Хранилище (строк)"
              value={Object.values(data.storage_rows).reduce((a, b) => a + b, 0)}
              hint="приблизительно по core-таблицам"
            />
            <StatCard label="Период" value={`${data.days} дней`} />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <UsageTable
              title="По packs"
              rows={data.by_pack}
              empty="Нет workflow-метрик за период"
            />
            <UsageTable
              title="По workflow"
              rows={data.by_workflow}
              empty="Запустите workflow — метрики появятся"
            />
          </div>

          {data.by_tenant.length > 0 ? (
            <div className="card p-0">
              <div className="border-b border-surface-border px-5 py-3 text-xs font-medium uppercase tracking-wide text-slate-500">
                По tenants
              </div>
              <div className="divide-y divide-surface-border/60">
                {data.by_tenant.map((t) => (
                  <div key={String(t.tenant)} className="grid grid-cols-4 gap-4 px-5 py-2.5 text-sm">
                    <span className="truncate text-slate-200">{String(t.tenant)}</span>
                    <span className="text-slate-400">{Number(t.llm_tokens ?? 0).toLocaleString("ru-RU")} токенов</span>
                    <span className="text-slate-400">{Number(t.agent_executions ?? 0)} executions</span>
                    <span className="font-mono text-slate-300">{Number(t.llm_cost_rub ?? 0).toFixed(2)} ₽</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div>
            <h3 className="mb-3 text-sm font-medium text-slate-300">Тарифы (прайс платформы)</h3>
            <div className="grid gap-4 lg:grid-cols-3">
              {TARIFFS.map((t) => (
                <div key={t.name} className="card p-5">
                  <div className="text-xs uppercase tracking-wide text-slate-500">{t.name}</div>
                  <div className="mt-2 text-2xl font-semibold text-white">
                    {t.price.toLocaleString("ru-RU")} <span className="text-sm font-normal text-slate-500">₽/мес</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">{t.desc}</div>
                  <button className="btn-ghost mt-4 w-full">Перейти на тариф</button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function UsageTable({ title, rows, empty }: { title: string; rows: { [k: string]: unknown }[]; empty: string }) {
  if (rows.length === 0) {
    return (
      <div className="card p-0">
        <div className="border-b border-surface-border px-5 py-3 text-xs font-medium uppercase tracking-wide text-slate-500">{title}</div>
        <EmptyState title={title} description={empty} />
      </div>
    );
  }
  return (
    <div className="card p-0">
      <div className="border-b border-surface-border px-5 py-3 text-xs font-medium uppercase tracking-wide text-slate-500">{title}</div>
      <div className="divide-y divide-surface-border/60">
        {rows.map((r) => {
          const key = r.name ?? r.pack ?? r.workflow ?? r.agent_id;
          const label = typeof key === "string" ? (key.length > 16 ? `${key.slice(0, 16)}…` : key) : String(key);
          const value = Number(r.workflow_runs ?? r.agent_executions ?? r.llm_cost_rub ?? 0);
          const suffix = r.workflow_runs !== undefined ? "runs" : r.agent_executions !== undefined ? "exec" : "₽";
          return (
            <div key={String(key)} className="flex items-center justify-between px-5 py-2.5">
              <span className="font-mono text-sm text-slate-200">{label}</span>
              <span className="font-mono text-sm text-slate-400">
                {value.toLocaleString("ru-RU")} {suffix}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
