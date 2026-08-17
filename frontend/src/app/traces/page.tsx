"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { SpanNode, TraceSummary, TraceTree } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader } from "@/components/ui";

const TYPE_LABEL: Record<string, string> = {
  conversation: "Диалог",
  task: "Задача",
  agent: "Агент",
  llm: "LLM",
  supplier: "Поиск поставщиков",
  tool: "Инструмент",
  pricing: "Ценообразование",
  quote: "Квота",
  approval: "Согласование",
  action: "Действие",
  order: "Заказ",
};

function statusColor(status: string): string {
  switch (status) {
    case "ok":
    case "completed":
      return "bg-emerald-500/15 text-emerald-400";
    case "failed":
      return "bg-rose-500/15 text-rose-400";
    case "running":
      return "bg-blue-500/15 text-blue-400";
    default:
      return "bg-slate-500/15 text-slate-400";
  }
}

function SpanRow({ node, depth }: { node: SpanNode; depth: number }) {
  const s = node.span;
  const dur = s.duration_ms != null ? (s.duration_ms >= 1000 ? `${(s.duration_ms / 1000).toFixed(2)}s` : `${s.duration_ms}мс`) : "—";
  const meta = s.meta ?? {};
  return (
    <div>
      <div
        className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition hover:bg-surface-hover"
        style={{ marginLeft: `${depth * 22}px` }}
      >
        <span className={`h-2 w-2 shrink-0 rounded-full ${statusColor(s.status)}`} />
        <span className="w-32 shrink-0 text-xs text-slate-500">
          {TYPE_LABEL[s.span_type] ?? s.span_type}
        </span>
        <span className="min-w-0 flex-1 truncate text-slate-200">{s.name}</span>
        <span className="w-16 shrink-0 text-right font-mono text-xs text-slate-400">{dur}</span>
        <span className="badge bg-slate-500/15 text-slate-300">{s.status}</span>
      </div>
      {s.error_kind ? (
        <div
          className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-300"
          style={{ marginLeft: `${depth * 22 + 24}px` }}
        >
          {s.error_kind}
        </div>
      ) : null}
      {Object.keys(meta).length > 0 ? (
        <div
          className="truncate px-3 pb-1 font-mono text-[11px] text-slate-600"
          style={{ marginLeft: `${depth * 22 + 24}px` }}
        >
          {JSON.stringify(meta)}
        </div>
      ) : null}
      {node.children.map((child) => (
        <SpanRow key={child.span.id} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}

export default function TracesPage() {
  const { data: traces, loading, error } = useApi<TraceSummary[]>("/traces?limit=50");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<TraceTree | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  async function openTrace(id: string) {
    setSelected(id);
    setDetailLoading(true);
    setDetailError(null);
    try {
      const tree = await api.get<TraceTree>(`/traces/${id}`);
      setDetail(tree);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : "Ошибка загрузки трассы");
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <div>
      <SectionHeader title="Трассировка" />

      <div className="mb-6 grid gap-4 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <h2 className="mb-3 text-sm font-medium text-slate-300">Трассы</h2>
          {loading ? (
            <Loading />
          ) : error ? (
            <ErrorBox message={error} />
          ) : traces && traces.length === 0 ? (
            <EmptyState
              title="Трасс пока нет"
              description="Трасса открывается с первого входящего сообщения клиента и описывает весь путь до заказа."
            />
          ) : (
            <div className="card p-0">
              <div className="max-h-[70vh] overflow-y-auto">
                {traces?.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => openTrace(t.id)}
                    className={`block w-full border-b border-surface-border px-4 py-3 text-left transition last:border-b-0 ${
                      selected === t.id ? "bg-accent/10" : "hover:bg-surface-hover"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-slate-500">{t.source}</span>
                      <span className={`badge ${statusColor(t.status)}`}>{t.status}</span>
                    </div>
                    <div className="mt-1 truncate font-mono text-[11px] text-slate-600">
                      {t.id}
                    </div>
                    <div className="mt-1 flex items-center gap-3 text-xs text-slate-400">
                      <span>спанов: {t.span_count}</span>
                      <span>{new Date(t.started_at).toLocaleString("ru-RU")}</span>
                    </div>
                    {t.error_kinds.length > 0 ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {t.error_kinds.map((k) => (
                          <span key={k} className="rounded bg-rose-500/15 px-1.5 py-0.5 font-mono text-[10px] text-rose-300">
                            {k}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="lg:col-span-3">
          <h2 className="mb-3 text-sm font-medium text-slate-300">Дерево спанов</h2>
          {!selected ? (
            <EmptyState
              title="Выберите трассу"
              description="Слева — список обработанных клиентских запросов."
            />
          ) : detailLoading ? (
            <Loading />
          ) : detailError ? (
            <ErrorBox message={detailError} />
          ) : detail?.root ? (
            <div className="card p-3">
              <SpanRow node={detail.root} depth={0} />
            </div>
          ) : (
            <EmptyState title="Спаны не найдены" description="В этой трассе нет записанных спанов." />
          )}
        </div>
      </div>
    </div>
  );
}
