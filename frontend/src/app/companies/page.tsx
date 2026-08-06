"use client";

import { useApi } from "@/lib/useApi";
import type { Company } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader } from "@/components/ui";

export default function CompaniesPage() {
  const { data, loading, error } = useApi<Company[]>("/companies");

  return (
    <div>
      <SectionHeader
        title="Компании"
        action={
          <button className="btn-primary" disabled>
            + Добавить компанию
          </button>
        }
      />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : data && data.length === 0 ? (
        <EmptyState title="Компаний пока нет" description="Компания по умолчанию появится после первого запуска backend." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {data?.map((c) => (
            <div key={c.id} className="card">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm font-semibold text-white">{c.name}</div>
                  <div className="font-mono text-xs text-slate-500">/{c.slug}</div>
                </div>
                <span className={`badge ${c.is_active ? "bg-emerald-500/15 text-emerald-400" : "bg-slate-500/15 text-slate-400"}`}>
                  {c.is_active ? "активна" : "неактивна"}
                </span>
              </div>
              <p className="mt-3 line-clamp-2 text-xs text-slate-400">{c.description || "—"}</p>
              <div className="mt-4 grid grid-cols-3 gap-2 border-t border-surface-border pt-3 text-center">
                <div>
                  <div className="text-lg font-semibold text-white">{c.agents_count}</div>
                  <div className="text-[11px] text-slate-500">агенты</div>
                </div>
                <div>
                  <div className="text-lg font-semibold text-white">{c.tasks_count}</div>
                  <div className="text-[11px] text-slate-500">задачи</div>
                </div>
                <div>
                  <div className="text-lg font-semibold text-white">{c.agent_quota}</div>
                  <div className="text-[11px] text-slate-500">квота</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
