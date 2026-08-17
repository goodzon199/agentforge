"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Supplier, SupplierReliability } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader } from "@/components/ui";

function fmt(value: number | null | undefined, suffix = "%"): string {
  return value === null || value === undefined ? "—" : `${value}${suffix}`;
}

function MetricRow({ label, value, good }: { label: string; value: string; good?: boolean }) {
  const color = good === true ? "text-emerald-400" : good === false ? "text-rose-400" : "text-slate-200";
  return (
    <div className="flex items-center justify-between px-4 py-2">
      <div className="text-xs text-slate-400">{label}</div>
      <div className={`font-mono text-sm font-medium ${color}`}>{value}</div>
    </div>
  );
}

function SupplierCard({
  supplier,
  reliability,
  onRecompute,
  busy,
}: {
  supplier: Supplier;
  reliability: SupplierReliability | null;
  onRecompute: () => void;
  busy: boolean;
}) {
  const r = reliability;
  const rating = r?.rating ?? null;
  const ratingGood = rating !== null && rating >= 0.8;
  const ratingTone = rating === null ? "text-slate-400" : ratingGood ? "text-emerald-400" : rating < 0.5 ? "text-rose-400" : "text-amber-400";
  const api = r?.api_availability ?? null;
  const onTime = r?.on_time_delivery ?? null;
  const price = r?.price_change_rate ?? null;
  const cancel = r?.cancellation_rate ?? null;

  return (
    <div className="card p-0">
      <div className="flex items-center justify-between gap-4 border-b border-surface-border px-5 py-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white">{supplier.name}</span>
            <span className="badge bg-accent/15 text-accent-soft">{supplier.adapter_type}</span>
            {supplier.is_experimental ? (
              <span
                className="badge bg-amber-500/15 text-amber-400"
                title="Endpoint'ы не подтверждены на живом API — не production-ready."
              >
                experimental
              </span>
            ) : null}
          </div>
          <div className="mt-0.5 font-mono text-xs text-slate-500">/{supplier.slug}</div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className={`font-mono text-2xl font-semibold ${ratingTone}`}>
              {rating !== null ? rating.toFixed(2) : "—"}
            </div>
            <div className="text-[11px] text-slate-500">рейтинг (0..1)</div>
          </div>
          <button className="btn-secondary" onClick={onRecompute} disabled={busy}>
            Пересчитать
          </button>
        </div>
      </div>

      <div className="grid gap-x-6 gap-y-1 p-2 lg:grid-cols-3">
        <div>
          <div className="px-4 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">
            Заказы
          </div>
          <MetricRow label="Подтверждено" value={`${r?.confirmed ?? 0} / ${r?.orders_total ?? 0}`} />
          <MetricRow
            label="Подтверждение"
            value={fmt(r?.confirmation_rate)}
            good={r?.confirmation_rate !== null && r?.confirmation_rate !== undefined && r.confirmation_rate >= 90}
          />
          <MetricRow
            label="Отмены"
            value={fmt(r?.cancellation_rate)}
            good={r?.cancellation_rate !== null && r?.cancellation_rate !== undefined && r.cancellation_rate <= 5}
          />
        </div>
        <div>
          <div className="px-4 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">
            Поставки ({r?.fulfillments_total ?? 0})
          </div>
          <MetricRow
            label="В срок"
            value={fmt(onTime)}
            good={onTime !== null && onTime >= 90}
          />
          <MetricRow
            label="Изменение цены"
            value={fmt(price)}
            good={price !== null && price !== undefined && price <= 5}
          />
          <MetricRow
            label="Недопоставки"
            value={fmt(r?.under_delivery_rate)}
            good={r?.under_delivery_rate !== null && r?.under_delivery_rate !== undefined && r.under_delivery_rate <= 5}
          />
          <MetricRow
            label="Возвраты"
            value={`${r?.returns_total ?? 0} (${fmt(r?.return_rate)})`}
            good={r?.return_rate !== null && r?.return_rate !== undefined && r.return_rate <= 5}
          />
        </div>
        <div>
          <div className="px-4 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">
            API
          </div>
          <MetricRow
            label="Доступность"
            value={fmt(api)}
            good={api !== null && api >= 99}
          />
          <MetricRow
            label="Попыток / ошибок"
            value={`${r?.attempts_total ?? 0} / ${r?.attempts_failed ?? 0}`}
            good={r?.attempts_total ? r.attempts_failed / r.attempts_total <= 0.02 : undefined}
          />
          <MetricRow
            label="Средний отклик"
            value={r?.api_avg_latency_ms !== null && r?.api_avg_latency_ms !== undefined ? `${r.api_avg_latency_ms}мс` : "—"}
          />
          <MetricRow
            label="P95 отклик"
            value={r?.api_p95_latency_ms !== null && r?.api_p95_latency_ms !== undefined ? `${r.api_p95_latency_ms}мс` : "—"}
          />
        </div>
      </div>

      {r ? (
        <div className="flex items-center justify-between border-t border-surface-border px-5 py-2.5 text-[11px] text-slate-500">
          <span>
            composite: надёжность {r.reliability_score.toFixed(3)} · API {r.api_score.toFixed(3)} · версия {r.rating_version}
          </span>
          <span>рассчитано автоматически</span>
        </div>
      ) : null}
    </div>
  );
}

export default function SuppliersPage() {
  const suppliers = useApi<Supplier[]>("/suppliers");
  const [reliability, setReliability] = useState<Record<string, SupplierReliability>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const router = useRouter();

  useEffect(() => {
    if (!suppliers.data) return;
    let cancelled = false;
    for (const s of suppliers.data) {
      api
        .get<SupplierReliability>(`/suppliers/${s.id}/reliability`)
        .then((r) => {
          if (!cancelled) setReliability((prev) => ({ ...prev, [s.id]: r }));
        })
        .catch(() => undefined);
    }
    return () => {
      cancelled = true;
    };
  }, [suppliers.data]);

  async function recompute(supplier: Supplier) {
    setBusy((prev) => ({ ...prev, [supplier.id]: true }));
    try {
      const r = await api.post<SupplierReliability>(`/suppliers/${supplier.id}/recompute`, {});
      setReliability((prev) => ({ ...prev, [supplier.id]: r }));
    } finally {
      setBusy((prev) => ({ ...prev, [supplier.id]: false }));
    }
  }

  return (
    <div>
      <SectionHeader
        title="Поставщики"
        action={
          <button className="btn-primary" disabled>
            + Добавить поставщика
          </button>
        }
      />
      {suppliers.loading ? (
        <Loading />
      ) : suppliers.error ? (
        <ErrorBox message={suppliers.error} />
      ) : suppliers.data && suppliers.data.length === 0 ? (
        <EmptyState title="Поставщиков пока нет" description="Добавьте поставщика — рейтинг рассчитается автоматически." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-2">
          {suppliers.data?.map((s) => (
            <SupplierCard
              key={s.id}
              supplier={s}
              reliability={reliability[s.id] ?? null}
              onRecompute={() => recompute(s)}
              busy={busy[s.id]}
            />
          ))}
        </div>
      )}
    </div>
  );
}
