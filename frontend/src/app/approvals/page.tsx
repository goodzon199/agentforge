"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { PlatformApprovalList } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader } from "@/components/ui";

const RISK_TONE: Record<string, string> = {
  LOW: "bg-emerald-500/15 text-emerald-400",
  MEDIUM: "bg-amber-500/15 text-amber-400",
  HIGH: "bg-rose-500/15 text-rose-400",
};

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function ApprovalsPage() {
  const { data, loading, error, reload } = useApi<PlatformApprovalList>("/platform/approvals");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function decide(id: string, approve: boolean) {
    if (busyId) return;
    setBusyId(id);
    setErrorMsg(null);
    try {
      await api.post(`/platform/approvals/${id}/${approve ? "approve" : "reject"}`, {});
      reload();
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <SectionHeader
        title="Approvals · очередь подтверждений"
        action={
          data ? (
            <span className="badge bg-amber-500/15 text-amber-400">{data.approvals.length} ожидают</span>
          ) : undefined
        }
      />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : data && data.approvals.length === 0 ? (
        <EmptyState
          title="Очередь пуста"
          description="AgentAction с requires_approval = pending появляются здесь для ручного решения."
        />
      ) : (
        <div className="card divide-y divide-surface-border p-0">
          {data?.approvals.map((a) => {
            const message = (a.input_data as { message?: string } | null)?.message;
            const nodeId = (a.input_data as { node_id?: string } | null)?.node_id;
            return (
              <div key={a.id} className="flex items-start justify-between gap-4 px-5 py-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-200">{a.action_type}</span>
                    <span className={`badge ${RISK_TONE[a.risk_level] ?? "bg-slate-500/15 text-slate-400"}`}>{a.risk_level}</span>
                    {a.target_type ? <span className="text-[11px] text-slate-500">{a.target_type}</span> : null}
                  </div>
                  {message ? <div className="mt-1 text-xs text-slate-400">{message}</div> : null}
                  <div className="mt-1.5 font-mono text-[10px] text-slate-600">
                    {a.id.slice(0, 8)}… · {nodeId ? `node ${nodeId} · ` : ""}
                    {fmtDate(a.created_at)}
                  </div>
                </div>
                <div className="flex shrink-0 gap-2">
                  <button
                    className="btn-primary"
                    disabled={busyId === a.id}
                    onClick={() => decide(a.id, true)}
                  >
                    Одобрить
                  </button>
                  <button
                    className="btn-ghost"
                    disabled={busyId === a.id}
                    onClick={() => decide(a.id, false)}
                  >
                    Отклонить
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {errorMsg ? <div className="mt-4 text-xs text-rose-400">{errorMsg}</div> : null}
    </div>
  );
}
