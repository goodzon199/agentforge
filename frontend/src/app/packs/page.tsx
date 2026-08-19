"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Pack, PlatformOverview } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader, StatusBadge } from "@/components/ui";

const STATE_TONE: Record<string, string> = {
  active: "bg-emerald-500/15 text-emerald-400",
  installed: "bg-slate-500/15 text-slate-400",
  configured: "bg-blue-500/15 text-blue-400",
  disabled: "bg-slate-500/15 text-slate-400",
  degraded: "bg-amber-500/15 text-amber-400",
  upgrade_required: "bg-rose-500/15 text-rose-400",
};

function PackBadge({ state }: { state: string }) {
  return <span className={`badge ${STATE_TONE[state] ?? "bg-slate-500/15 text-slate-300"}`}>{state}</span>;
}

function PackCard({ pack, onChanged }: { pack: Pack; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(action: "enable" | "disable" | "upgrade" | "configure") {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/packs/${pack.name}/${action}`, { config: {} });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent/20 text-sm font-bold text-accent-soft">
            {pack.display_name.slice(0, 2)}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-white">{pack.display_name}</span>
              <span className="font-mono text-[11px] text-slate-500">v{pack.version}</span>
            </div>
            <div className="text-xs text-slate-500">
              {pack.name} · {pack.developer || "неизвестный developer"}
            </div>
          </div>
        </div>
        <PackBadge state={pack.state} />
      </div>

      <p className="mt-3 line-clamp-2 text-xs text-slate-400">{pack.description || "—"}</p>

      <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
        <div className="rounded-lg bg-surface-raised/60 px-3 py-2">
          <div className="text-slate-500">Агенты</div>
          <div className="mt-0.5 font-mono text-sm text-slate-200">{pack.agents.length}</div>
        </div>
        <div className="rounded-lg bg-surface-raised/60 px-3 py-2">
          <div className="text-slate-500">Workflows</div>
          <div className="mt-0.5 font-mono text-sm text-slate-200">{pack.workflows.length}</div>
        </div>
        <div className="rounded-lg bg-surface-raised/60 px-3 py-2">
          <div className="text-slate-500">Tools</div>
          <div className="mt-0.5 font-mono text-sm text-slate-200">{pack.tools.length}</div>
        </div>
        <div className="rounded-lg bg-surface-raised/60 px-3 py-2">
          <div className="text-slate-500">Требует Core</div>
          <div className="mt-0.5 font-mono text-sm text-slate-200">{pack.required_core_version}</div>
        </div>
      </div>

      <div className="mt-4">
        <div className="mb-1.5 flex items-center justify-between text-xs">
          <span className="text-slate-500">Зависимости (Sprint 5.7)</span>
          {pack.checksum ? (
            <span className="font-mono text-[10px] text-slate-600" title={`sha256: ${pack.checksum}`}>
              {pack.checksum.slice(0, 12)}…
            </span>
          ) : null}
        </div>
        {pack.dependencies.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {pack.dependencies.map((d) => (
              <span key={d.name} className="badge bg-surface-raised/60 text-slate-300">
                {d.name} {d.version_req}
              </span>
            ))}
          </div>
        ) : (
          <div className="text-xs text-slate-600">нет зависимостей</div>
        )}
      </div>

      {pack.license ? (
        <div className="mt-3 text-[11px] text-slate-600">
          license {pack.license}
          {pack.signature ? " · подписан" : ""}
        </div>
      ) : null}

      {error ? <div className="mt-3 text-xs text-rose-400">{error}</div> : null}

      <div className="mt-4 flex flex-wrap gap-2">
        {pack.is_active ? (
          <button className="btn-ghost" disabled={busy} onClick={() => act("disable")}>
            Отключить
          </button>
        ) : pack.state === "upgrade_required" ? (
          <button className="btn-primary" disabled={busy} onClick={() => act("upgrade")}>
            Обновить
          </button>
        ) : (
          <button className="btn-primary" disabled={busy} onClick={() => act("enable")}>
            Активировать
          </button>
        )}
        {pack.state === "installed" ? (
          <button className="btn-ghost" disabled={busy} onClick={() => act("configure")}>
            Настроить
          </button>
        ) : null}
        {!pack.is_active && pack.checksum ? (
          <span className="badge bg-emerald-500/15 text-emerald-400" title="реестровая проверка прошла">
            verified
          </span>
        ) : null}
      </div>
    </div>
  );
}

export default function PacksPage() {
  const { data, loading, error, reload } = useApi<Pack[]>("/packs");
  const overview = useApi<PlatformOverview>("/platform/overview");

  return (
    <div>
      <SectionHeader
        title="Реестр packs"
        action={
          <button className="btn-primary" disabled>
            + Установить pack
          </button>
        }
      />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : data && data.length === 0 ? (
        <EmptyState
          title="Packs не зарегистрированы"
          description="Запустите discover — core прочитает манифесты из PACK_BASE_URLS и добавит packs в реестр."
        />
      ) : (
        <>
          {overview.data ? (
            <p className="mb-4 text-xs text-slate-500">
              {overview.data.packs} packs в реестре · {overview.data.packs_active} активных ·{" "}
              {overview.data.workflows} workflows · {overview.data.tools} tools
            </p>
          ) : null}
          <div className="grid gap-4 lg:grid-cols-2">
            {data?.map((p) => <PackCard key={p.name} pack={p} onChanged={reload} />)}
          </div>
        </>
      )}
    </div>
  );
}
