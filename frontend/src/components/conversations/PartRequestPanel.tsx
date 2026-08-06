import type { PartQuote, PartRequest, SupplierOffer, SupplierSearchRun } from "@/lib/types";
import { getStoredUser } from "@/lib/api";
import { StatusBadge } from "@/components/ui";

const STATUS_LABEL: Record<string, string> = {
  collecting_data: "Требуется уточнение",
  ready_for_search: "Готов к поиску",
  searching: "Идёт поиск",
  quoted: "Есть предложения",
  approved: "Согласовано",
  completed: "Завершено",
  cancelled: "Отменено",
};

const MISSING_LABEL: Record<string, string> = {
  vin: "VIN",
  vehicle: "автомобиль",
  part: "деталь",
};

const ACTIVE_STATUSES = ["collecting_data", "ready_for_search", "searching", "quoted"];

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
      <span className="shrink-0 text-xs text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  );
}

function formatPrice(value: string | null): string {
  if (value === null || value === "") return "—";
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 2,
  }).format(num);
}

type Props = {
  partRequests: PartRequest[];
  offers: SupplierOffer[];
  searchRuns: SupplierSearchRun[];
  quote: PartQuote | null;
  searching: boolean;
  onSearch: (partRequestId: string) => void;
};

export function PartRequestPanel({
  partRequests,
  offers,
  searchRuns,
  quote,
  searching,
  onSearch,
}: Props) {
  const active =
    partRequests.find((pr) => ACTIVE_STATUSES.includes(pr.status)) ?? partRequests[0];

  if (!active) {
    return null;
  }

  const vehicle = active.vehicle;
  const car = vehicle
    ? [vehicle.brand, vehicle.model, vehicle.year && String(vehicle.year)].filter(Boolean).join(" ")
    : "не указан";
  const vin = vehicle?.vin ? vehicle.vin : "не указан";
  const missingHint = active.missing_fields.length
    ? `Требуется: ${active.missing_fields.map((f) => MISSING_LABEL[f] ?? f).join(", ")}`
    : null;

  const latestRun = searchRuns[0];
  const canSearch = ["ready_for_search", "quoted", "searching"].includes(active.status);
  const isManager = getStoredUser<{ is_superuser?: boolean }>()?.is_superuser === true;

  return (
    <div className="rounded-xl border border-surface-border bg-surface/60 px-4 py-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Запрос клиента</span>
        <StatusBadge status={active.status} />
      </div>

      <div className="mt-1 divide-y divide-surface-border">
        <Field
          label="Деталь"
          value={`${active.part_name || "—"}${active.article ? ` · ${active.article}` : ""}${
            active.quantity > 1 ? ` ×${active.quantity}` : ""
          }`}
        />
        <Field label="Автомобиль" value={car} />
        <Field label="VIN" value={vin} />
      </div>

      <div className="mt-2 flex items-center justify-between text-xs">
        <span className="text-slate-500">{STATUS_LABEL[active.status] ?? active.status}</span>
        {missingHint ? <span className="text-amber-400">{missingHint}</span> : null}
      </div>

      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          className="btn-primary"
          disabled={!canSearch || searching}
          onClick={() => onSearch(active.id)}
        >
          {searching ? "Ищем…" : "Найти предложения"}
        </button>
        {latestRun ? (
          <span className="text-xs text-slate-400">
            Найдено <b className="text-white">{latestRun.offers_found}</b> предложений от{" "}
            <b className="text-white">{latestRun.suppliers_succeeded}</b> поставщиков
            {latestRun.suppliers_failed > 0 ? (
              <span className="text-amber-400"> ({latestRun.suppliers_failed} недоступны)</span>
            ) : null}
          </span>
        ) : null}
      </div>

      {quote && quote.status === "priced" && quote.best_total_price ? (
        <div className="mt-3 rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-xs text-slate-200">
          <span className="font-medium text-white">Лучшее предложение:</span>{" "}
          {[quote.best_brand, quote.best_article].filter(Boolean).join(" ") || "—"} ·{" "}
          {formatPrice(quote.best_unit_price)} /шт × {quote.quantity} ={" "}
          <b className="text-white">{formatPrice(quote.best_total_price)}</b>
          {quote.margin_percent !== null && quote.margin_percent !== undefined ? (
            <span className="text-slate-400"> (наценка {quote.margin_percent}%)</span>
          ) : null}
        </div>
      ) : null}

      {offers.length > 0 ? (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-xs">
            <thead>
              <tr className="border-b border-surface-border text-[11px] uppercase tracking-wide text-slate-500">
                <th className="py-1.5 pr-3 font-medium">Бренд</th>
                <th className="py-1.5 pr-3 font-medium">Артикул</th>
                <th className="py-1.5 pr-3 font-medium">Название</th>
                <th className="py-1.5 pr-3 font-medium">Цена</th>
                {isManager ? (
                  <th className="py-1.5 pr-3 font-medium">Закупка</th>
                ) : null}
                <th className="py-1.5 pr-3 font-medium">Наличие</th>
                <th className="py-1.5 pr-3 font-medium">Срок</th>
                <th className="py-1.5 font-medium">Поставщик</th>
              </tr>
            </thead>
            <tbody>
              {offers.map((o) => (
                <tr key={o.id} className="border-b border-surface-border/60">
                  <td className="py-1.5 pr-3 text-slate-200">{o.brand || "—"}</td>
                  <td className="py-1.5 pr-3 font-mono text-slate-200">{o.article || "—"}</td>
                  <td className="py-1.5 pr-3 text-slate-300">{o.part_name || "—"}</td>
                  <td className="py-1.5 pr-3 text-slate-100">
                    {formatPrice(o.customer_price)}
                    {o.total_price && o.total_price !== o.customer_price ? (
                      <span className="block text-[10px] text-slate-400">
                        итог {formatPrice(o.total_price)}
                      </span>
                    ) : null}
                  </td>
                  {isManager ? (
                    <td className="py-1.5 pr-3 text-slate-100">{formatPrice(o.purchase_price)}</td>
                  ) : null}
                  <td className="py-1.5 pr-3 text-slate-300">
                    {o.quantity !== null && o.quantity !== undefined ? `${o.quantity} шт` : "—"}
                  </td>
                  <td className="py-1.5 pr-3 text-slate-300">
                    {o.delivery_days !== null && o.delivery_days !== undefined
                      ? `${o.delivery_days} дн`
                      : "—"}
                  </td>
                  <td className="py-1.5 text-slate-300">{o.supplier_name || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
