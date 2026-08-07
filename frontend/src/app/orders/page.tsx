"use client";

import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Order } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader, StatusBadge } from "@/components/ui";

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

  return (
    <div>
      <SectionHeader
        title="Заказы"
        action={
          <button className="btn-ghost" onClick={reload}>
            Обновить
          </button>
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
                  <th className="px-5 py-3 font-medium">Сумма</th>
                  <th className="px-5 py-3 font-medium">Товары</th>
                  <th className="px-5 py-3 font-medium">Создан</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border">
                {orders?.map((o) => (
                  <tr key={o.id} className="hover:bg-surface-hover">
                    <td className="px-5 py-3 font-mono text-slate-200">{o.order_number}</td>
                    <td className="px-5 py-3">
                      <StatusBadge status={o.status} />
                    </td>
                    <td className="px-5 py-3 text-slate-100">
                      {formatPrice(o.order_total)} {o.currency}
                    </td>
                    <td className="px-5 py-3 text-xs text-slate-300">
                      {o.items.length > 0
                        ? o.items
                            .map((it) => `${it.brand} ${it.article}`)
                            .join(", ")
                        : "—"}
                    </td>
                    <td className="px-5 py-3 text-xs text-slate-500">
                      {new Date(o.created_at).toLocaleString("ru-RU")}
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
