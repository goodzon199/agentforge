"use client";

import { useApi } from "@/lib/useApi";
import type { PlatformToolList } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader } from "@/components/ui";

export default function ToolsPage() {
  const { data, loading, error } = useApi<PlatformToolList>("/platform/tools");

  const coreTools = data?.tools.filter((t) => t.source === "core") ?? [];
  const packTools = data?.tools.filter((t) => t.source === "pack") ?? [];

  return (
    <div>
      <SectionHeader
        title="Tools · инвентарь платформы"
        action={
          data ? (
            <span className="text-xs text-slate-500">
              всего {data.tools.length} · pack {packTools.length} · core {coreTools.length}
            </span>
          ) : undefined
        }
      />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : data && data.tools.length === 0 ? (
        <EmptyState title="Инструментов пока нет" description="Core registry и packs ещё не объявили tools." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="card p-0">
            <div className="border-b border-surface-border px-5 py-3 text-xs font-medium uppercase tracking-wide text-slate-500">
              Pack tools
            </div>
            {packTools.length === 0 ? (
              <div className="px-5 py-6 text-center text-xs text-slate-600">packs не объявили tools</div>
            ) : (
              <div className="divide-y divide-surface-border/60">
                {packTools.map((t) => (
                  <div key={`${t.pack}-${t.name}`} className="flex items-center justify-between px-5 py-2.5">
                    <span className="font-mono text-sm text-slate-200">{t.name}</span>
                    <span className="badge bg-accent/15 text-accent-soft">{t.pack}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card p-0">
            <div className="border-b border-surface-border px-5 py-3 text-xs font-medium uppercase tracking-wide text-slate-500">
              Core registry
            </div>
            {coreTools.length === 0 ? (
              <div className="px-5 py-6 text-center text-xs text-slate-600">core registry пуст</div>
            ) : (
              <div className="divide-y divide-surface-border/60">
                {coreTools.map((t) => (
                  <div key={t.name} className="flex items-center justify-between px-5 py-2.5">
                    <span className="font-mono text-sm text-slate-200">{t.name}</span>
                    <span className="badge bg-slate-500/15 text-slate-400">core</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
