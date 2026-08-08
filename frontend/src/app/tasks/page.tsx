"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Company, DeadTask, Task } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader, StatusBadge } from "@/components/ui";

const REPLAYABLE = new Set(["failed", "cancelled", "completed"]);

export default function TasksPage() {
  const { data: tasks, loading, error, reload } = useApi<Task[]>("/tasks?limit=50");
  const { data: companies } = useApi<Company[]>("/companies");
  const { data: dead, reload: reloadDead } = useApi<DeadTask[]>("/tasks/dead");

  const [companyId, setCompanyId] = useState("");
  const [objective, setObjective] = useState("");
  const [emailTo, setEmailTo] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [result, setResult] = useState<Task | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!objective.trim() || !companyId) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const task = await api.post<Task>("/tasks", {
        company_id: companyId,
        title: objective.slice(0, 120),
        objective: objective.trim(),
        priority: "normal",
        input_data: {
          ...(emailTo.trim() ? { to: emailTo.trim() } : {}),
        },
      });
      setResult(task);
      setObjective("");
      await reload();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Ошибка отправки");
    } finally {
      setSubmitting(false);
    }
  }

  async function replay(taskId: string) {
    setBusyId(taskId);
    try {
      await api.post<Task>(`/tasks/${taskId}/replay`, {});
      await Promise.all([reload(), reloadDead()]);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Ошибка повтора");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <SectionHeader title="Задачи" />

      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <form onSubmit={submit} className="card">
          <h2 className="mb-3 text-sm font-medium text-slate-300">Новая задача</h2>
          <label className="mb-1 block text-xs text-slate-500">Компания</label>
          <select className="input mb-3" value={companyId} onChange={(e) => setCompanyId(e.target.value)} required>
            <option value="">Выберите компанию…</option>
            {companies?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <label className="mb-1 block text-xs text-slate-500">Кому (email, необязательно)</label>
          <input
            type="email"
            className="input mb-3"
            placeholder="demo@agentos.local"
            value={emailTo}
            onChange={(e) => setEmailTo(e.target.value)}
          />
          <label className="mb-1 block text-xs text-slate-500">Задача для SystemAgent</label>
          <textarea
            className="input mb-3 min-h-[80px] resize-y"
            placeholder="Например: Найди тормозные колодки или Отправь письмо клиенту"
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            required
          />
          <button type="submit" className="btn-primary w-full" disabled={submitting}>
            {submitting ? "Отправка…" : "Отправить агенту"}
          </button>
          {submitError ? <div className="mt-3 text-xs text-rose-400">{submitError}</div> : null}
        </form>

        {result ? (
          <div className="card">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-medium text-slate-300">Результат SystemAgent</h2>
              <StatusBadge status={result.status} />
            </div>
            <div className="rounded-lg bg-surface p-3 font-mono text-sm text-slate-200">
              {String(result.output_data?.response ?? result.error ?? "—")}
            </div>
            {result.routing_decision ? (
              <div className="mt-3 text-xs text-slate-500">
                Маршрутизация: <span className="text-accent-soft">{String(result.routing_decision.needs_agent ?? "нет специализированного агента")}</span>
                {" · "}
                {String(result.routing_decision.engine)}
              </div>
            ) : null}
            <div className="mt-3 border-t border-surface-border pt-3">
              <div className="text-xs text-slate-500">События:</div>
              <ul className="mt-2 space-y-1.5">
                {result.events?.map((e) => (
                  <li key={e.id} className="flex items-start gap-2 text-xs">
                    <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                    <span className="text-slate-400">{e.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : null}
      </div>

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : tasks && tasks.length === 0 ? (
        <EmptyState
          title="Задач пока нет"
          description="Отправьте первую задачу — SystemAgent определит, какой агент нужен для её выполнения."
        />
      ) : (
        <div className="card p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-surface-border text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-5 py-3 font-medium">Задача</th>
                  <th className="px-5 py-3 font-medium">Статус</th>
                  <th className="px-5 py-3 font-medium">Маршрут</th>
                  <th className="px-5 py-3 font-medium">Создана</th>
                  <th className="px-5 py-3 font-medium"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border">
                {tasks?.map((t) => (
                  <tr key={t.id} className="hover:bg-surface-hover">
                    <td className="max-w-[320px] px-5 py-3">
                      <div className="truncate text-slate-200">{t.title}</div>
                      <div className="truncate text-xs text-slate-500">{t.objective}</div>
                      {t.replayed_from_task_id ? (
                        <div className="truncate text-xs text-accent-soft">
                          повтор от {t.replayed_from_task_id.slice(0, 8)}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-5 py-3">
                      <StatusBadge status={t.status} />
                    </td>
                    <td className="px-5 py-3 text-xs text-slate-400">
                      {String(t.routing_decision?.needs_agent ?? "—")}
                    </td>
                    <td className="px-5 py-3 text-xs text-slate-500">
                      {new Date(t.created_at).toLocaleString("ru-RU")}
                    </td>
                    <td className="px-5 py-3 text-right">
                      {REPLAYABLE.has(t.status) ? (
                        <button
                          className="btn-ghost text-xs"
                          disabled={busyId === t.id}
                          onClick={() => replay(t.id)}
                        >
                          {busyId === t.id ? "Повтор…" : "Повторить"}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="mt-8">
        <SectionHeader title={`Dead Letter Queue${dead && dead.length ? ` (${dead.length})` : ""}`} />
        {dead && dead.length > 0 ? (
          <div className="card p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-surface-border text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-5 py-3 font-medium">Задача</th>
                    <th className="px-5 py-3 font-medium">Код ошибки</th>
                    <th className="px-5 py-3 font-medium">Попытки</th>
                    <th className="px-5 py-3 font-medium">Упала в DLQ</th>
                    <th className="px-5 py-3 font-medium"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-border">
                  {dead.map((d) => (
                    <tr key={d.id} className="hover:bg-surface-hover">
                      <td className="max-w-[320px] px-5 py-3">
                        <div className="truncate text-slate-200">{d.objective}</div>
                        {d.error ? (
                          <div className="truncate text-xs text-rose-300/70">{d.error}</div>
                        ) : null}
                      </td>
                      <td className="px-5 py-3">
                        <span className="rounded bg-surface px-2 py-0.5 font-mono text-xs text-amber-300">
                          {d.exception_kind}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-xs text-slate-400">{d.attempts}</td>
                      <td className="px-5 py-3 text-xs text-slate-500">
                        {new Date(d.dead_at).toLocaleString("ru-RU")}
                      </td>
                      <td className="px-5 py-3 text-right">
                        <button
                          className="btn-ghost text-xs"
                          disabled={busyId === d.task_id}
                          onClick={() => replay(d.task_id)}
                        >
                          {busyId === d.task_id ? "Повтор…" : d.replayed_task_id ? "Повторено" : "Повторить"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-surface-border p-6 text-center text-xs text-slate-500">
            Пусто — всё, что упало, уже обработано.
          </div>
        )}
      </div>
    </div>
  );
}
