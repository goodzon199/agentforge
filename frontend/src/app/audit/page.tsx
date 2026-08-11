"use client";

import { useState } from "react";
import { useApi } from "@/lib/useApi";
import type { AuditEvent, AuditList } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader } from "@/components/ui";

const ACTION_LABEL: Record<string, string> = {
  "approval.approve": "Согласование одобрено",
  "approval.reject": "Согласование отклонено",
  "quote.accept": "Квота принята клиентом",
  "order.create": "Заказ создан",
  "task.replay": "Задача повторена",
  "user.create": "Создан пользователь",
};

const ENTITY_LABEL: Record<string, string> = {
  approval: "Согласование",
  quote: "Квота",
  order: "Заказ",
  task: "Задача",
  user: "Пользователь",
};

function actionColor(action: string): string {
  if (action.startsWith("approval.reject")) return "bg-rose-500/15 text-rose-300";
  if (action === "order.create") return "bg-emerald-500/15 text-emerald-300";
  if (action.startsWith("task.replay")) return "bg-blue-500/15 text-blue-300";
  return "bg-slate-500/15 text-slate-300";
}

export default function AuditPage() {
  const { data, loading, error, reload } = useApi<AuditList>("/audit?limit=100");
  const [selected, setSelected] = useState<AuditEvent | null>(null);

  return (
    <div>
      <SectionHeader title="Аудит" />

      <div className="mb-6 grid gap-4 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-300">Журнал действий</h2>
            <button
              onClick={reload}
              className="rounded-md px-2 py-1 text-xs text-slate-400 transition hover:bg-surface-hover hover:text-slate-200"
            >
              Обновить
            </button>
          </div>
          {loading ? (
            <Loading />
          ) : error ? (
            <ErrorBox message={error} />
          ) : data && data.items.length === 0 ? (
            <EmptyState
              title="Событий нет"
              description="Здесь появятся одобрения, заказы, повторы задач и создание пользователей."
            />
          ) : (
            <div className="card p-0">
              <div className="max-h-[75vh] overflow-y-auto">
                {data?.items.map((e) => (
                  <button
                    key={e.id}
                    onClick={() => setSelected(e)}
                    className={`block w-full border-b border-surface-border px-4 py-3 text-left transition last:border-b-0 ${
                      selected?.id === e.id ? "bg-accent/10" : "hover:bg-surface-hover"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={`badge ${actionColor(e.action)}`}>
                        {ACTION_LABEL[e.action] ?? e.action}
                      </span>
                      <span className="text-xs text-slate-500">
                        {new Date(e.created_at).toLocaleString("ru-RU")}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-slate-400">
                      {ENTITY_LABEL[e.entity_type] ?? e.entity_type}
                      {e.entity_id ? ` · ${e.entity_id.slice(0, 8)}…` : ""}
                    </div>
                  </button>
                ))}
              </div>
              {data && data.total > data.items.length ? (
                <div className="border-t border-surface-border px-4 py-2 text-xs text-slate-500">
                  Показано {data.items.length} из {data.total}
                </div>
              ) : null}
            </div>
          )}
        </div>

        <div className="lg:col-span-3">
          <h2 className="mb-3 text-sm font-medium text-slate-300">Детали события</h2>
          {!selected ? (
            <EmptyState
              title="Выберите событие"
              description="Слева — журнал защищённых действий платформы."
            />
          ) : (
            <div className="card space-y-3 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`badge ${actionColor(selected.action)}`}>
                  {ACTION_LABEL[selected.action] ?? selected.action}
                </span>
                <span className="badge bg-surface-hover text-slate-300">
                  {ENTITY_LABEL[selected.entity_type] ?? selected.entity_type}
                </span>
                <span className="badge bg-surface-hover text-slate-400">
                  actor: {selected.actor_type}
                </span>
              </div>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <dt className="text-xs text-slate-500">Время</dt>
                  <dd className="text-slate-200">
                    {new Date(selected.created_at).toLocaleString("ru-RU")}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Пользователь</dt>
                  <dd className="truncate font-mono text-xs text-slate-300">
                    {selected.user_id ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Компания</dt>
                  <dd className="truncate font-mono text-xs text-slate-300">
                    {selected.company_id ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Сущность</dt>
                  <dd className="truncate font-mono text-xs text-slate-300">
                    {selected.entity_id ?? "—"}
                  </dd>
                </div>
              </dl>
              {Object.keys(selected.detail ?? {}).length > 0 ? (
                <div>
                  <dt className="text-xs text-slate-500">Данные</dt>
                  <pre className="mt-1 overflow-x-auto rounded-lg bg-surface-raised/50 p-3 font-mono text-xs text-slate-300">
                    {JSON.stringify(selected.detail, null, 2)}
                  </pre>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
