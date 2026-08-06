"use client";

import { useApi } from "@/lib/useApi";
import type { ToolInfo } from "@/lib/types";
import { ErrorBox, Loading, SectionHeader } from "@/components/ui";

type Info = {
  name: string;
  version: string;
  environment: string;
  llm_available: boolean;
  redis_available: boolean;
};

export default function SettingsPage() {
  const info = useApi<Info>("/settings/info");
  const tools = useApi<ToolInfo[]>("/settings/tools");

  return (
    <div>
      <SectionHeader title="Настройки" />

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-4 text-sm font-medium text-slate-300">Платформа</h2>
          {info.loading ? (
            <Loading />
          ) : info.error ? (
            <ErrorBox message={info.error} />
          ) : info.data ? (
            <dl className="space-y-3 text-sm">
              {[
                ["Название", info.data.name],
                ["Версия", info.data.version],
                ["Окружение", info.data.environment],
                ["LLM провайдер", info.data.llm_available ? "подключён" : "не настроен (детерминированный режим)"],
                ["Redis", info.data.redis_available ? "доступен" : "недоступен (синхронный режим)"],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between border-b border-surface-border pb-2 last:border-0">
                  <dt className="text-slate-500">{k}</dt>
                  <dd className={k === "LLM провайдер" || k === "Redis" ? `font-medium ${v === "подключён" || v === "доступен" ? "text-emerald-400" : "text-amber-400"}` : "text-slate-200"}>
                    {v}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>

        <div className="card">
          <h2 className="mb-4 text-sm font-medium text-slate-300">Инструменты (реестр модулей)</h2>
          {tools.loading ? (
            <Loading />
          ) : tools.error ? (
            <ErrorBox message={tools.error} />
          ) : (
            <div className="space-y-2">
              {tools.data?.map((t) => (
                <details key={t.name} className="rounded-lg bg-surface p-3">
                  <summary className="flex cursor-pointer items-center justify-between">
                    <span className="font-mono text-sm text-accent-soft">{t.name}</span>
                    <span className="text-xs text-slate-500">v{t.version}</span>
                  </summary>
                  <p className="mt-2 text-xs text-slate-400">{t.description}</p>
                </details>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
