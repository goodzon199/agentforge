"use client";

import { useApi } from "@/lib/useApi";
import type { Agent } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader, StatusBadge } from "@/components/ui";

export default function AgentsPage() {
  const { data, loading, error } = useApi<Agent[]>("/agents");

  return (
    <div>
      <SectionHeader
        title="Агенты — цифровые сотрудники"
        action={
          <button className="btn-primary" disabled>
            + Создать агента
          </button>
        }
      />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : data && data.length === 0 ? (
        <EmptyState
          title="Агентов пока нет"
          description="SystemAgent будет создан автоматически при первом запуске backend."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {data?.map((a) => (
            <div key={a.id} className="card">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent/20 text-sm font-bold text-accent-soft">
                  {a.name.slice(0, 2)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-semibold text-white">{a.name}</span>
                    <span className="font-mono text-[10px] text-slate-500">/{a.slug}</span>
                  </div>
                  <div className="truncate text-xs text-slate-500">{a.role}</div>
                </div>
                <StatusBadge status={a.status} />
              </div>

              <p className="mt-3 line-clamp-2 text-xs text-slate-400">{a.description || a.goal || "—"}</p>

              <div className="mt-4 flex flex-wrap gap-1.5">
                <span className="badge bg-surface-hover text-slate-300">{a.model}</span>
                <span className="badge bg-surface-hover text-slate-300">t={a.temperature}</span>
                {a.tools.map((t) => (
                  <span key={t.tool_name} className="badge bg-accent/10 text-accent-soft">
                    {t.tool_name}
                  </span>
                ))}
              </div>

              <div className="mt-4 grid grid-cols-3 gap-2 border-t border-surface-border pt-3 text-center">
                <div>
                  <div className="text-lg font-semibold text-white">{a.tasks_total}</div>
                  <div className="text-[11px] text-slate-500">задач</div>
                </div>
                <div>
                  <div className="text-lg font-semibold text-white">{a.avg_success_rate}%</div>
                  <div className="text-[11px] text-slate-500">успех</div>
                </div>
                <div>
                  <div className="text-lg font-semibold text-white">{a.total_llm_calls}</div>
                  <div className="text-[11px] text-slate-500">LLM вызовы</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
