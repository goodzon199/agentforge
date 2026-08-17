"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AuditEvent, AuditList } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader } from "@/components/ui";

const ACTION_LABEL: Record<string, string> = {
  "approval.approve": "Согласование одобрено",
  "approval.reject": "Согласование отклонено",
  "quote.accept": "Квота принята клиентом",
  "order.create": "Заказ создан",
  "task.replay": "Задача повторена",
  "user.create": "Создан пользователь",
  "user.update": "Пользователь обновлён",
  "user.disable": "Пользователь отключён",
  "user.enable": "Пользователь включён",
  "user.reset_password": "Сброс пароля пользователя",
  "user.change_password": "Смена пароля",
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
  if (action.startsWith("user.")) return "bg-violet-500/15 text-violet-300";
  return "bg-slate-500/15 text-slate-300";
}

export default function AuditPage() {
  const [data, setData] = useState<AuditList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const [action, setAction] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const buildQuery = useCallback((cursor?: string) => {
    const params = new URLSearchParams({ limit: "50" });
    if (action) params.set("action", action);
    if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
    if (dateTo) params.set("date_to", new Date(dateTo).toISOString());
    if (cursor) params.set("cursor", cursor);
    return `/audit?${params.toString()}`;
  }, [action, dateFrom, dateTo]);

  const load = useCallback(async (cursor?: string) => {
    setError(null);
    setLoading(true);
    try {
      const page = await api.get<AuditList>(buildQuery(cursor));
      setData((prev) =>
        cursor && prev
          ? { ...page, items: [...prev.items, ...page.items] }
          : page,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить журнал");
    } finally {
      setLoading(false);
    }
  }, [buildQuery]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <SectionHeader title="Аудит" />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-xs text-slate-500">Действие</label>
          <select
            className="input w-52"
            value={action}
            onChange={(e) => setAction(e.target.value)}
          >
            <option value="">Все</option>
            {Object.entries(ACTION_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">С</label>
          <input
            type="date"
            className="input"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">По</label>
          <input
            type="date"
            className="input"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </div>
        <button
          onClick={() => load()}
          className="rounded-md border border-surface-border px-3 py-1.5 text-xs text-slate-300 transition hover:bg-surface-hover"
        >
          Применить
        </button>
      </div>

      <div className="mb-6 grid gap-4 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-300">Журнал действий</h2>
            <span className="text-xs text-slate-500">всего: {data?.total ?? "…"}</span>
          </div>
          {loading && !data ? (
            <Loading />
          ) : error ? (
            <ErrorBox message={error} />
          ) : data && data.items.length === 0 ? (
            <EmptyState
              title="Событий нет"
              description="Здесь появятся одобрения, заказы, повторы задач и действия с пользователями."
            />
          ) : (
            <div className="card p-0">
              <div className="max-h-[65vh] overflow-y-auto">
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
              {data?.next_cursor ? (
                <button
                  onClick={() => load(data.next_cursor!)}
                  disabled={loading}
                  className="block w-full border-t border-surface-border px-4 py-2 text-center text-xs text-slate-400 transition hover:bg-surface-hover hover:text-slate-200"
                >
                  {loading ? "Загружаем…" : "Загрузить ещё"}
                </button>
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
                <div>
                  <dt className="text-xs text-slate-500">IP</dt>
                  <dd className="truncate font-mono text-xs text-slate-300">
                    {selected.ip_address ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Request ID</dt>
                  <dd className="truncate font-mono text-xs text-slate-300">
                    {selected.request_id ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">User-Agent</dt>
                  <dd className="truncate font-mono text-xs text-slate-300">
                    {selected.user_agent ?? "—"}
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
