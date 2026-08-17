import { useEffect, useState } from "react";
import { api, getStoredUser } from "@/lib/api";
import type { FitmentExplain } from "@/lib/types";

const LEVEL_UI: Record<
  string,
  { dot: string; label: string; ring: string; text: string }
> = {
  high: {
    dot: "bg-emerald-500",
    label: "Высокая уверенность",
    ring: "border-emerald-500/40",
    text: "text-emerald-400",
  },
  medium: {
    dot: "bg-amber-500",
    label: "Требуется проверка",
    ring: "border-amber-500/40",
    text: "text-amber-400",
  },
  low: {
    dot: "bg-rose-500",
    label: "Не рекомендуется",
    ring: "border-rose-500/40",
    text: "text-rose-400",
  },
};

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

type Props = {
  partRequestId: string;
  article: string;
  brand?: string;
};

export function FitmentCard({ partRequestId, article, brand = "" }: Props) {
  const [data, setData] = useState<FitmentExplain | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const stored = getStoredUser<{ is_superuser?: boolean; role?: string }>();
  const canVerify = stored?.is_superuser === true || ["manager", "admin"].includes(stored?.role ?? "");

  function load() {
    api
      .get<FitmentExplain>(`/fitment/${partRequestId}/explain`)
      .then(setData)
      .catch(() => setData(null));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partRequestId]);

  if (!data) return null;

  const ui = LEVEL_UI[data.level] ?? LEVEL_UI.medium;
  const hasEvidence = data.sources.length > 0 || data.checks.length > 0 || data.warnings.length > 0;

  async function verify(result: "confirmed" | "rejected") {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const updated = await api.post<FitmentExplain>(`/fitment/${partRequestId}/verify`, {
        article,
        brand,
        result,
      });
      setData(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить вердикт");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${ui.ring} bg-surface/40`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${ui.dot}`} />
          <span className={`font-medium ${ui.text}`}>{ui.label}</span>
          {data.verdict === "na" ? null : (
            <span className="text-slate-300">
              уверенность <b className="text-white">{percent(data.confidence)}</b>
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {hasEvidence ? (
            <button
              type="button"
              className="rounded bg-surface px-2 py-1 text-[11px] font-medium text-slate-300 hover:bg-surface-hover"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? "Скрыть" : "Почему?"}
            </button>
          ) : null}
          {canVerify ? (
            <>
              <button
                type="button"
                className="rounded bg-emerald-500/15 px-2 py-1 text-[11px] font-medium text-emerald-400 hover:bg-emerald-500/25"
                disabled={busy}
                onClick={() => verify("confirmed")}
              >
                ✓ Подходит
              </button>
              <button
                type="button"
                className="rounded bg-rose-500/15 px-2 py-1 text-[11px] font-medium text-rose-400 hover:bg-rose-500/25"
                disabled={busy}
                onClick={() => verify("rejected")}
              >
                ✕ Не подходит
              </button>
            </>
          ) : null}
        </div>
      </div>

      {error ? <div className="mt-2 text-rose-400">{error}</div> : null}

      {expanded && (
        <div className="mt-2 space-y-1.5 border-t border-surface-border pt-2">
          {data.sources.map((s, i) => (
            <div key={i} className="flex items-baseline justify-between gap-3">
              <span className="shrink-0 text-slate-500">{s.source}</span>
              <span className="text-slate-300">
                {s.detail || "—"}
                <span className="ml-2 text-[10px] text-slate-500">
                  {"+".repeat(Math.max(0, Math.round(s.score * 4)))}
                  {".".repeat(Math.max(0, 4 - Math.round(s.score * 4)))}
                </span>
              </span>
            </div>
          ))}
          {data.checks.map((c, i) => (
            <div key={`c${i}`} className="text-emerald-400">
              + {c}
            </div>
          ))}
          {data.warnings.map((w, i) => (
            <div key={`w${i}`} className="text-rose-400">
              ! {w}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}