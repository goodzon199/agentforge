import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-3xl font-semibold text-white">{value}</div>
      {hint ? <div className="mt-1 text-xs text-slate-500">{hint}</div> : null}
    </div>
  );
}

export function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-surface-border py-16 text-center">
      <div className="text-3xl">∅</div>
      <div className="mt-3 text-sm font-medium text-slate-300">{title}</div>
      {description ? <div className="mt-1 max-w-md text-xs text-slate-500">{description}</div> : null}
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    completed: "bg-emerald-500/15 text-emerald-400",
    running: "bg-blue-500/15 text-blue-400",
    queued: "bg-amber-500/15 text-amber-400",
    pending: "bg-slate-500/15 text-slate-400",
    failed: "bg-rose-500/15 text-rose-400",
    cancelled: "bg-slate-500/15 text-slate-400",
    awaiting_routing: "bg-violet-500/15 text-violet-400",
    idle: "bg-slate-500/15 text-slate-400",
    active: "bg-emerald-500/15 text-emerald-400",
    disabled: "bg-slate-500/15 text-slate-400",
    paused: "bg-amber-500/15 text-amber-400",
  };
  return <span className={`badge ${map[status] ?? "bg-slate-500/15 text-slate-300"}`}>{status}</span>;
}

export function SectionHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between">
      <h1 className="text-lg font-semibold text-white">{title}</h1>
      {action}
    </div>
  );
}

export function Loading() {
  return <div className="animate-pulse py-12 text-center text-sm text-slate-500">Загрузка…</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
      Ошибка: {message}
    </div>
  );
}
