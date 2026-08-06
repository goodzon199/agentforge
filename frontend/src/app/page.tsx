"use client";

import Link from "next/link";
import { useApi } from "@/lib/useApi";
import type { Agent, DashboardStats, Task, ToolInfo } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, StatCard, StatusBadge } from "@/components/ui";

export default function DashboardPage() {
  const stats = useApi<DashboardStats>("/dashboard");
  const tasks = useApi<Task[]>("/tasks?limit=6");
  const agents = useApi<Agent[]>("/agents");
  const tools = useApi<ToolInfo[]>("/settings/tools");

  if (stats.loading || tasks.loading) return <Loading />;
  if (stats.error || tasks.error) return <ErrorBox message={stats.error ?? tasks.error ?? ""} />;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-white">Обзор платформы</h1>
        <p className="mt-1 text-sm text-slate-500">
          Операционная система для цифровых сотрудников — запуск первого спринта.
        </p>
      </div>

      {stats.data && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Компании" value={stats.data.companies} />
          <StatCard label="Агенты" value={stats.data.agents} hint={`активных: ${stats.data.agents_active}`} />
          <StatCard label="Задачи" value={stats.data.tasks} hint={`выполнено: ${stats.data.tasks_completed}`} />
          <StatCard label="События логов" value={stats.data.logs_total} hint={`ошибок: ${stats.data.tasks_failed}`} />
        </div>
      )}

      <div className="mt-8 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-300">Последние задачи</h2>
            <Link href="/tasks" className="text-xs text-accent-soft hover:underline">
              Все задачи →
            </Link>
          </div>
          {tasks.data && tasks.data.length === 0 ? (
            <EmptyState
              title="Задач пока нет"
              description="Создайте первую задачу — SystemAgent получит её и определит нужного агента."
            />
          ) : (
            <div className="card divide-y divide-surface-border p-0">
              {tasks.data?.map((t) => (
                <div key={t.id} className="flex items-center justify-between gap-4 px-5 py-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm text-slate-200">{t.title}</div>
                    <div className="mt-0.5 truncate text-xs text-slate-500">{t.objective}</div>
                  </div>
                  <StatusBadge status={t.status} />
                </div>
              ))}
            </div>
          )}
        </div>

        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-300">Агенты</h2>
            <Link href="/agents" className="text-xs text-accent-soft hover:underline">
              Все →
            </Link>
          </div>
          <div className="space-y-2">
            {agents.data?.map((a) => (
              <div key={a.id} className="card flex items-center gap-3 py-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/20 text-xs font-bold text-accent-soft">
                  {a.name.slice(0, 2)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-slate-200">{a.name}</div>
                  <div className="truncate text-xs text-slate-500">{a.role}</div>
                </div>
                <StatusBadge status={a.status} />
              </div>
            ))}
          </div>

          <div className="mt-6">
            <h2 className="mb-3 text-sm font-medium text-slate-300">Инструменты</h2>
            <div className="card py-3">
              {tools.data?.map((t) => (
                <div key={t.name} className="flex items-center justify-between border-b border-surface-border py-2 last:border-0">
                  <span className="font-mono text-xs text-slate-300">{t.name}</span>
                  <span className="badge bg-accent/15 text-accent-soft">v{t.version}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
