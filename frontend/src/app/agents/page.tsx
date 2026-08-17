"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Agent, AgentQualityReport, PromptVersion } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader, StatusBadge } from "@/components/ui";

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value}%`;
}

function money(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(2)} ₽`;
}

export default function AgentsPage() {
  const { data, loading, error } = useApi<Agent[]>("/agents");
  const { data: quality, reload: reloadQuality } = useApi<AgentQualityReport>("/agents/quality?days=7");
  const { data: prompts, reload: reloadPrompts } = useApi<PromptVersion[]>("/prompts");

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

      <div className="mt-10">
        <h2 className="text-sm font-medium text-slate-300">Качество агентов · 7 дней</h2>
        <p className="mt-1 text-xs text-slate-500">
          Как люди оценивают работу агентов: принято как есть, отредактировано, отклонено, галлюцинации; время и стоимость.
        </p>
        {quality?.agents.length ? (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead>
                <tr className="border-b border-surface-border text-xs uppercase tracking-wide text-slate-500">
                  <th className="py-2 pr-4">Агент</th>
                  <th className="py-2 pr-4">Задачи</th>
                  <th className="py-2 pr-4">Принято</th>
                  <th className="py-2 pr-4">Отредакт.</th>
                  <th className="py-2 pr-4">Отклонено</th>
                  <th className="py-2 pr-4">Галлюц.</th>
                  <th className="py-2 pr-4">Ответ</th>
                  <th className="py-2 pr-4">Перехват</th>
                  <th className="py-2 pr-4">LLM</th>
                  <th className="py-2 pr-4">Цена/задача</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border">
                {quality.agents.map((q) => (
                  <tr key={q.agent_id}>
                    <td className="py-2.5 pr-4">
                      <div className="font-medium text-white">{q.name}</div>
                      <div className="text-xs text-slate-500">{q.slug}</div>
                    </td>
                    <td className="py-2.5 pr-4 text-slate-300">{q.tasks_completed} из {q.tasks_total}</td>
                    <td className="py-2.5 pr-4 text-emerald-400">{pct(q.feedback.acceptance_rate)}</td>
                    <td className="py-2.5 pr-4 text-amber-400">{pct(q.feedback.edit_rate)}</td>
                    <td className="py-2.5 pr-4 text-rose-400">{pct(q.feedback.rejection_rate)}</td>
                    <td className="py-2.5 pr-4 text-rose-400">{pct(q.feedback.hallucination_rate)}</td>
                    <td className="py-2.5 pr-4 text-slate-300">
                      {q.avg_response_seconds !== null ? `${q.avg_response_seconds.toFixed(2)}с` : "—"}
                    </td>
                    <td className="py-2.5 pr-4 text-slate-300">{pct(q.human_takeover)}</td>
                    <td className="py-2.5 pr-4 text-slate-300">
                      {q.llm_calls} · {money(q.total_llm_cost)}
                    </td>
                    <td className="py-2.5 pr-4 text-slate-300">{money(q.cost_per_task)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="mt-4">
            <EmptyState title="Данных о качестве пока нет" description="Появятся после прохождения первых диалогов и согласований." />
          </div>
        )}
      </div>

      <div className="mt-10">
        <h2 className="text-sm font-medium text-slate-300">Версии промптов · сравнение качества</h2>
        <p className="mt-1 text-xs text-slate-500">
          Активная версия используется SalesAgent. Обратная связь людей группируется по версии — так видно, какая версия лучше.
        </p>
        <div className="mt-4 space-y-3">
          {prompts?.map((p) => {
            const q = quality?.by_prompt_version.find(
              (r) => r.agent_kind === p.agent_kind && r.prompt_version === p.version
            );
            return (
              <div key={p.id} className={`card p-4 ${p.is_active ? "ring-1 ring-accent/40" : ""}`}>
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white">{p.agent_kind}:{p.version}</span>
                      <span className="truncate text-xs text-slate-500">{p.name}</span>
                      {p.is_active ? (
                        <span className="badge bg-emerald-500/15 text-emerald-400">активна</span>
                      ) : null}
                    </div>
                    {p.description ? (
                      <p className="mt-1 line-clamp-1 text-xs text-slate-500">{p.description}</p>
                    ) : null}
                    {q ? (
                      <p className="mt-2 text-xs text-slate-400">
                        принято {pct(q.acceptance_rate)} · отредакт. {pct(q.edit_rate)} · отклонено {pct(q.rejection_rate)} · галлюц. {pct(q.hallucination_rate)} · N={q.feedback_total}
                      </p>
                    ) : (
                      <p className="mt-2 text-xs text-slate-600">нет обратной связи по этой версии</p>
                    )}
                  </div>
                  {!p.is_active ? (
                    <button
                      className="btn-secondary"
                      onClick={async () => {
                        try {
                          await api.post(`/prompts/${p.id}/activate`, {});
                          await Promise.all([reloadQuality(), reloadPrompts()]);
                        } catch (e) {
                          alert(e instanceof Error ? e.message : "Ошибка активации");
                        }
                      }}
                    >
                      Активировать
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
