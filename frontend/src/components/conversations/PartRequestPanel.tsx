import type { PartRequest } from "@/lib/types";
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

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
      <span className="shrink-0 text-xs text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  );
}

export function PartRequestPanel({ partRequests }: { partRequests: PartRequest[] }) {
  const active =
    partRequests.find((pr) => ["collecting_data", "ready_for_search", "searching", "quoted"].includes(pr.status)) ??
    partRequests[0];

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
    </div>
  );
}
