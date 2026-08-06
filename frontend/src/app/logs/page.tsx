"use client";

import { useApi } from "@/lib/useApi";
import type { TaskEvent } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader } from "@/components/ui";

function levelColor(level: string) {
  switch (level) {
    case "error":
      return "text-rose-400 bg-rose-500/15";
    case "warning":
      return "text-amber-400 bg-amber-500/15";
    default:
      return "text-blue-400 bg-blue-500/15";
  }
}

export default function LogsPage() {
  const { data, loading, error } = useApi<TaskEvent[]>("/logs?limit=200");

  return (
    <div>
      <SectionHeader title="Логи" />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : data && data.length === 0 ? (
        <EmptyState title="Логов пока нет" description="События появятся при выполнении задач." />
      ) : (
        <div className="card p-0 font-mono">
          <div className="max-h-[calc(100vh-220px)] overflow-y-auto">
            {data?.map((e) => (
              <div key={e.id} className="flex items-start gap-3 border-b border-surface-border px-4 py-2 text-xs last:border-0">
                <span className="w-40 shrink-0 text-slate-500">
                  {new Date(e.created_at).toLocaleTimeString("ru-RU")}
                </span>
                <span className={`badge shrink-0 ${levelColor(e.level)}`}>{e.level}</span>
                <span className="w-36 shrink-0 truncate text-slate-500">{e.source}</span>
                <span className="min-w-0 break-words text-slate-300">{e.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
