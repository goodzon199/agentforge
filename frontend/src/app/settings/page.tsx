"use client";

import { useState } from "react";
import { api, getStoredUser } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { EmergencyStatus, ShadowStats, ToolInfo } from "@/lib/types";
import { ErrorBox, Loading, SectionHeader } from "@/components/ui";

type Info = {
  name: string;
  version: string;
  environment: string;
  llm_available: boolean;
  redis_available: boolean;
};

const MANAGER_ROLES = new Set(["owner", "admin"]);

export default function SettingsPage() {
  const info = useApi<Info>("/settings/info");
  const tools = useApi<ToolInfo[]>("/settings/tools");
  const emergency = useApi<EmergencyStatus>("/ops/emergency");
  const shadowStats = useApi<ShadowStats>("/manager/shadow/stats");
  const [shadowMode, setShadowMode] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const user = getStoredUser<{ role?: string; is_superuser?: boolean }>();
  const canManage = user?.is_superuser || (user?.role ? MANAGER_ROLES.has(user.role) : false);

  const shadowModeOn = shadowMode ?? shadowStats.data?.shadow_mode ?? true;

  async function toggleShadowMode() {
    if (busy) return;
    setBusy(true);
    setActionError(null);
    try {
      const result = await api.patch<{ shadow_mode: boolean }>("/manager/shadow-mode", {
        enabled: !shadowModeOn,
      });
      setShadowMode(result.shadow_mode);
      shadowStats.reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Ошибка переключения");
    } finally {
      setBusy(false);
    }
  }

  async function engage() {
    const reason = window.prompt("Причина приостановки пилота:");
    if (reason === null) return;
    setBusy(true);
    setActionError(null);
    try {
      await api.post("/ops/emergency/engage", { reason });
      emergency.reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Ошибка остановки");
    } finally {
      setBusy(false);
    }
  }

  async function release() {
    setBusy(true);
    setActionError(null);
    try {
      await api.post("/ops/emergency/release", {});
      emergency.reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Ошибка возобновления");
    } finally {
      setBusy(false);
    }
  }

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
          <h2 className="mb-4 text-sm font-medium text-slate-300">Аварийная остановка</h2>
          {emergency.loading ? (
            <Loading />
          ) : emergency.error ? (
            <ErrorBox message={emergency.error} />
          ) : emergency.data ? (
            <div className="space-y-3 text-sm">
              <div className={`flex items-center justify-between rounded-lg px-3 py-2 ${emergency.data.engaged ? "bg-red-500/10 text-red-300" : "bg-emerald-500/10 text-emerald-300"}`}>
                <span className="font-medium">
                  {emergency.data.engaged ? "Пилот ПРИОСТАНОВЛЕН" : "Пилот работает"}
                </span>
                <span className="text-xs">{emergency.data.engaged ? "новые задачи и сообщения заблокированы" : "приём задач и сообщений открыт"}</span>
              </div>
              {emergency.data.engaged && (
                <dl className="space-y-1">
                  {emergency.data.reason && (
                    <div className="flex justify-between">
                      <dt className="text-slate-500">Причина</dt>
                      <dd className="text-slate-200">{emergency.data.reason}</dd>
                    </div>
                  )}
                  {emergency.data.engaged_at && (
                    <div className="flex justify-between">
                      <dt className="text-slate-500">С</dt>
                      <dd className="text-slate-200">{new Date(emergency.data.engaged_at).toLocaleString()}</dd>
                    </div>
                  )}
                </dl>
              )}
              {canManage && (
                <div className="flex gap-2">
                  <button
                    onClick={engage}
                    disabled={busy || emergency.data.engaged}
                    className="rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-40"
                  >
                    Остановить пилот
                  </button>
                  <button
                    onClick={release}
                    disabled={busy || !emergency.data.engaged}
                    className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-40"
                  >
                    Возобновить
                  </button>
                </div>
              )}
              {actionError && <p className="text-xs text-red-400">{actionError}</p>}
              {!canManage && (
                <p className="text-xs text-slate-500">Управление аварийной остановкой доступно владельцу или администратору.</p>
              )}
            </div>
          ) : null}
        </div>
      </div>

      <div className="card mt-4">
        <h2 className="mb-4 text-sm font-medium text-slate-300">Shadow Mode (пилот 3.8.1)</h2>
        {shadowStats.loading ? (
          <Loading />
        ) : shadowStats.error ? (
          <ErrorBox message={shadowStats.error} />
        ) : shadowStats.data ? (
          <div className="space-y-3 text-sm">
            <div className="flex items-center justify-between rounded-lg px-3 py-2 bg-surface/60">
              <div>
                <div className="font-medium text-slate-200">
                  Режим: {shadowModeOn ? "включён" : "выключен"}
                </div>
                <div className="text-xs text-slate-500">
                  AI работает параллельно с менеджером, клиент видит только ответ менеджера.
                </div>
              </div>
              {canManage ? (
                <button
                  onClick={toggleShadowMode}
                  disabled={busy}
                  className={`rounded-lg px-3 py-2 text-sm font-medium text-white disabled:opacity-40 ${
                    shadowModeOn ? "bg-rose-600" : "bg-emerald-600"
                  }`}
                >
                  {shadowModeOn ? "Выключить" : "Включить"}
                </button>
              ) : null}
            </div>
            <dl className="space-y-1">
              <div className="flex justify-between">
                <dt className="text-slate-500">Сравнений / оценено</dt>
                <dd className="text-slate-200">
                  {shadowStats.data.total} / {shadowStats.data.completed}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Лимит пилота</dt>
                <dd className="text-slate-200">{shadowStats.data.limit}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Совпадение деталей</dt>
                <dd className="text-slate-200">
                  {shadowStats.data.part_match_pct !== null ? `${shadowStats.data.part_match_pct}%` : "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Совпадение OEM</dt>
                <dd className="text-slate-200">
                  {shadowStats.data.oem_match_pct !== null ? `${shadowStats.data.oem_match_pct}%` : "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Среднее время ответа</dt>
                <dd className="text-slate-200">
                  {shadowStats.data.avg_time_seconds !== null
                    ? `${shadowStats.data.avg_time_seconds.toFixed(1)}с`
                    : "—"}
                </dd>
              </div>
            </dl>
            {actionError && <p className="text-xs text-red-400">{actionError}</p>}
            {!canManage && (
              <p className="text-xs text-slate-500">
                Управление shadow mode доступно владельцу или администратору.
              </p>
            )}
          </div>
        ) : null}
      </div>

      <div className="card mt-4">
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
  );
}
