"use client";

import { useApi } from "@/lib/useApi";
import type { PlatformWorkflow, PlatformWorkflowList } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader } from "@/components/ui";

const NODE_LABEL: Record<string, string> = {
  agent: "агент",
  condition: "условие",
  human: "человек",
  end: "конец",
};

export default function WorkflowsPage() {
  const { data, loading, error } = useApi<PlatformWorkflowList>("/platform/workflows");

  return (
    <div>
      <SectionHeader title="Workflows · определения по packs" />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : data && data.workflows.length === 0 ? (
        <EmptyState
          title="Workflows не найдены"
          description="Активные packs поставляют workflow.yaml по internal-контракту /internal/pack/workflows."
        />
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            {data?.workflows.map((w) => (
              <WorkflowCard key={`${w.pack}-${w.name}`} workflow={w} />
            ))}
          </div>
          {data?.errors && data.errors.length > 0 ? (
            <div className="mt-4 space-y-1 text-xs text-amber-400">
              {data.errors.map((e) => (
                <div key={e.pack}>
                  {e.pack}: {e.error}
                </div>
              ))}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

function WorkflowCard({ workflow }: { workflow: PlatformWorkflow }) {
  const agentNodes = workflow.nodes.filter((n) => n.type === "agent");
  const humanNodes = workflow.nodes.filter((n) => n.type === "human");
  const conditionNodes = workflow.nodes.filter((n) => n.type === "condition");
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white">{workflow.name}</span>
            <span className="font-mono text-[11px] text-slate-500">v{workflow.version}</span>
          </div>
          <div className="mt-0.5 text-xs text-slate-500">
            pack <span className="font-mono text-accent-soft">{workflow.pack}</span> · start:{" "}
            <span className="font-mono">{workflow.start}</span>
          </div>
        </div>
        <span className="badge bg-accent/15 text-accent-soft">{workflow.nodes.length} nodes</span>
      </div>
      <p className="mt-3 text-xs text-slate-600">DAG-описание не объявлено в workflow.yaml</p>
      <div className="mt-4 flex flex-wrap gap-1.5 text-[11px]">
        <span className="badge bg-emerald-500/15 text-emerald-400">{agentNodes.length} агентов</span>
        {humanNodes.length > 0 ? (
          <span className="badge bg-amber-500/15 text-amber-400">{humanNodes.length} human-step</span>
        ) : null}
        {conditionNodes.length > 0 ? (
          <span className="badge bg-blue-500/15 text-blue-400">{conditionNodes.length} условий</span>
        ) : null}
      </div>
      <div className="mt-3 border-t border-surface-border pt-3">
        <div className="mb-1.5 text-[10px] uppercase tracking-wide text-slate-600">Узлы DAG</div>
        <div className="flex flex-wrap gap-1">
          {workflow.nodes.map((n) => (
            <span key={n.id} className="rounded-md bg-surface-raised/60 px-2 py-1 font-mono text-[10px] text-slate-400">
              {n.id} <span className="text-slate-600">({NODE_LABEL[n.type] ?? n.type})</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
