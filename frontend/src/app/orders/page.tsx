"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Order, SupplierTracking } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader, StatusBadge } from "@/components/ui";

const TRACKING_LABELS: Record<string, string> = {
  pending: "Не размещён",
  accepted: "Принят",
  assembling: "В сборке",
  shipped: "Отправлен",
  arrived: "Прибыл",
  handed_over: "Выдан клиенту",
};

const TRACKING_COLORS: Record<string, string> = {
  pending: "bg-slate-500/15 text-slate-400",
  accepted: "bg-blue-500/15 text-blue-400",
  assembling: "bg-amber-500/15 text-amber-400",
  shipped: "bg-violet-500/15 text-violet-400",
  arrived: "bg-emerald-500/15 text-emerald-400",
  handed_over: "bg-emerald-500/15 text-emerald-400",
};

function formatPrice(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0,
  }).format(num);
}

export default function OrdersPage() {
  const { data: orders, loading, error, reload } = useApi<Order[]>("/orders");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function refreshTracking() {
    if (!orders) return;
    setBusy(true);
    setActionError(null);
    try {
      await Promise.all(
        orders.map((o) =>
          api
            .post<SupplierTracking>(`/supplier-orders/${o.id}/track`, {})
            .catch(() => null),
        ),
      );
      reload();
    } catch {
      setActionError("Не удалось обновить статусы поставщиков.");
    } finally {
      setBusy(false);
    }
  }

  async function handOver(order: Order) {
    setBusy(true);
    setActionError(null);
    try {
      await api.post<{ tracking_status: string }>(`/supplier-orders/${order.id}/hand-over`, {});
      reload();
    } catch {
      setActionError("Не удалось отметить выдачу заказа.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <SectionHeader
        title="Заказы"
        action={
          <div className="flex items-center gap-2">
            {actionError ? <span className="text-xs text-rose-400">{actionError}</span> : null}
            <button className="btn-ghost" onClick={refreshTracking} disabled={busy}>
              {busy ? "Обновляю…" : "Обновить трекинг"}
            </button>
            <button className="btn-ghost" onClick={reload} disabled={busy}>
              Обновить
            </button>
          </div>
        }
      />

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : orders && orders.length === 0 ? (
        <EmptyState
          title="Заказов пока нет"
          description="Когда клиент примет предложение, менеджер сможет оформить заказ прямо из диалога."
        />
      ) : (
        <div className="card p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-surface-border text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-5 py-3 font-medium">Номер</th>
                  <th className="px-5 py-3 font-medium">Статус</th>
                  <th className="px-5 py-3 font-medium">Трекинг поставщика</th>
                  <th className="px-5 py-3 font-medium">Сумма</th>
                  <th className="px-5 py-3 font-medium">Товары</th>
                  <th className="px-5 py-3 font-medium">Создан</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border">
                {orders?.map((o) => (
                  <tr key={o.id} className="hover:bg-surface-hover">
                    <td className="px-5 py-3 font-mono text-slate-200">{o.order_number}</td>
                    <td className="px-5 py-3">
                      <StatusBadge status={o.status} />
                    </td>
                    <td className="px-5 py-3">
                      <span
                        className={`badge ${TRACKING_COLORS[o.tracking_status] ?? "bg-slate-500/15 text-slate-300"}`}
                      >
                        {TRACKING_LABELS[o.tracking_status] ?? o.tracking_status}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-slate-100">
                      {formatPrice(o.order_total)} {o.currency}
                    </td>
                    <td className="px-5 py-3 text-xs text-slate-300">
                      {o.items.length > 0
                        ? o.items.map((it) => `${it.brand} ${it.article}`).join(", ")
                        : "—"}
                    </td>
                    <td className="px-5 py-3 text-xs text-slate-500">
                      {new Date(o.created_at).toLocaleString("ru-RU")}
                    </td>
                    <td className="px-5 py-3 text-right">
                      {o.tracking_status === "arrived" ? (
                        <button
                          className="btn-ghost text-xs"
                          onClick={() => handOver(o)}
                          disabled={busy}
                        >
                          Выдан клиенту
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
