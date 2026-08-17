"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Customer, CustomerGarage } from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader, StatusBadge } from "@/components/ui";

function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0,
  }).format(num);
}

const SEGMENT_LABEL: Record<string, string> = {
  economy: "Эконом",
  middle: "Средний",
  premium: "Премиум",
  unknown: "Не определён",
};

export default function CustomersPage() {
  const { data: customers, loading, error, reload } = useApi<Customer[]>("/customers");
  const [selected, setSelected] = useState<Customer | null>(null);
  const [garage, setGarage] = useState<CustomerGarage | null>(null);
  const [garageLoading, setGarageLoading] = useState(false);
  const [garageError, setGarageError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState({
    brand: "",
    model: "",
    year: "",
    vin: "",
    engine: "",
    body: "",
    registration_number: "",
  });

  async function openGarage(customer: Customer) {
    setSelected(customer);
    setGarageLoading(true);
    setGarageError(null);
    setGarage(null);
    try {
      setGarage(await api.get<CustomerGarage>(`/garage/customers/${customer.id}`));
    } catch (e) {
      setGarageError(e instanceof Error ? e.message : "Не удалось загрузить гараж");
    } finally {
      setGarageLoading(false);
    }
  }

  function updateForm(field: string, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function addVehicle(e: React.FormEvent) {
    e.preventDefault();
    if (!selected || saving) return;
    setSaving(true);
    try {
      await api.post(`/garage/customers/${selected.id}/vehicles`, {
        brand: form.brand,
        model: form.model,
        year: form.year ? Number(form.year) : null,
        vin: form.vin,
        engine: form.engine,
        body: form.body,
        registration_number: form.registration_number,
      });
      setForm({ brand: "", model: "", year: "", vin: "", engine: "", body: "", registration_number: "" });
      setShowAdd(false);
      setGarage(await api.get<CustomerGarage>(`/garage/customers/${selected.id}`));
    } catch (err) {
      setGarageError(err instanceof Error ? err.message : "Не удалось добавить автомобиль");
    } finally {
      setSaving(false);
    }
  }

  async function removeVehicle(vehicleId: string) {
    if (!selected || saving) return;
    setSaving(true);
    try {
      await api.del(`/garage/vehicles/${vehicleId}`);
      setGarage(await api.get<CustomerGarage>(`/garage/customers/${selected.id}`));
    } catch (err) {
      setGarageError(err instanceof Error ? err.message : "Не удалось удалить автомобиль");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <SectionHeader
        title="Клиенты"
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
      ) : customers && customers.length === 0 ? (
        <EmptyState title="Клиентов пока нет" description="Клиенты появятся после первых диалогов." />
      ) : (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[340px_1fr]">
          <div className="card p-0">
            <div className="border-b border-surface-border px-5 py-3 text-xs uppercase tracking-wide text-slate-500">
              Список клиентов
            </div>
            <div className="divide-y divide-surface-border">
              {customers?.map((c) => {
                const active = selected?.id === c.id;
                return (
                  <button
                    key={c.id}
                    onClick={() => openGarage(c)}
                    className={`block w-full px-5 py-3 text-left transition ${
                      active ? "bg-accent/10" : "hover:bg-surface-hover"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={`text-sm font-medium ${active ? "text-accent-soft" : "text-slate-200"}`}>
                        {c.name}
                      </span>
                      <StatusBadge status={c.source === "garage-demo" ? "active" : "new"} />
                    </div>
                    <div className="mt-0.5 truncate text-xs text-slate-500">
                      {c.phone || c.email || "—"}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="space-y-6">
            {!selected ? (
              <EmptyState title="Выберите клиента" description="Нажмите на клиента слева, чтобы увидеть его гараж и историю покупок." />
            ) : garageLoading ? (
              <Loading />
            ) : garageError ? (
              <ErrorBox message={garageError} />
            ) : garage ? (
              <>
                <GarageMemory memory={garage.memory} />
                <VehicleSection
                  vehicles={garage.vehicles}
                  onRemove={removeVehicle}
                />

                <div className="card">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold text-white">Автомобили</div>
                    <button className="btn-ghost" onClick={() => setShowAdd((v) => !v)}>
                      {showAdd ? "Отмена" : "Добавить автомобиль"}
                    </button>
                  </div>

                  {showAdd ? (
                    <form onSubmit={addVehicle} className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <Input label="Марка" value={form.brand} onChange={(v) => updateForm("brand", v)} placeholder="BMW" />
                      <Input label="Модель" value={form.model} onChange={(v) => updateForm("model", v)} placeholder="X5" />
                      <Input label="Год" value={form.year} onChange={(v) => updateForm("year", v)} placeholder="2019" />
                      <Input label="VIN" value={form.vin} onChange={(v) => updateForm("vin", v)} placeholder="WBA…" />
                      <Input label="Двигатель" value={form.engine} onChange={(v) => updateForm("engine", v)} placeholder="B57" />
                      <Input label="Кузов" value={form.body} onChange={(v) => updateForm("body", v)} placeholder="SUV" />
                      <Input
                        label="Госномер"
                        value={form.registration_number}
                        onChange={(v) => updateForm("registration_number", v)}
                        placeholder="А123ВС77"
                      />
                      <div className="flex items-end">
                        <button className="btn-primary w-full" disabled={saving} type="submit">
                          {saving ? "Сохранение…" : "Сохранить"}
                        </button>
                      </div>
                    </form>
                  ) : null}
                </div>
              </>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

function Input({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-slate-500">{label}</span>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-sm text-slate-200 outline-none transition focus:border-accent"
      />
    </label>
  );
}

function GarageMemory({ memory }: { memory: CustomerGarage["memory"] }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wide text-slate-500">Память о клиенте</div>
      <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div>
          <div className="text-xs text-slate-500">Сегмент</div>
          <div className="mt-1 text-lg font-semibold text-white">
            {SEGMENT_LABEL[memory.segment] ?? memory.segment}
          </div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Средний чек</div>
          <div className="mt-1 text-lg font-semibold text-white">{formatMoney(memory.avg_check)}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Предпочтения</div>
          <div className="mt-1 text-sm text-slate-300">
            {Object.entries(memory.preferences ?? {})
              .filter(([k]) => k !== "note")
              .map(([k, v]) => `${k}: ${String(v)}`)
              .join(", ") || "—"}
          </div>
        </div>
      </div>
    </div>
  );
}

function VehicleSection({
  vehicles,
  onRemove,
}: {
  vehicles: CustomerGarage["vehicles"];
  onRemove: (id: string) => void;
}) {
  if (vehicles.length === 0) {
    return (
      <div className="card">
        <div className="text-sm font-semibold text-white">Автомобили</div>
        <p className="mt-2 text-xs text-slate-500">
          В гараже пока нет автомобилей. Добавьте машину, чтобы агент подбирал детали без лишних вопросов.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {vehicles.map(({ vehicle, history }) => (
        <div key={vehicle.id} className="card">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-base font-semibold text-white">
                {vehicle.brand} {vehicle.model}
                {vehicle.year ? ` · ${vehicle.year}` : ""}
              </div>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                {vehicle.vin ? <span>VIN {vehicle.vin}</span> : null}
                {vehicle.engine ? <span>Двигатель {vehicle.engine}</span> : null}
                {vehicle.body ? <span>{vehicle.body}</span> : null}
                {vehicle.registration_number ? <span>{vehicle.registration_number}</span> : null}
              </div>
            </div>
            <button
              className="btn-ghost shrink-0 text-rose-300 hover:bg-rose-500/10"
              onClick={() => onRemove(vehicle.id)}
              title="Удалить автомобиль"
            >
              Удалить
            </button>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-surface-border text-xs uppercase tracking-wide text-slate-500">
                  <th className="py-2 pr-4 font-medium">Покупка</th>
                  <th className="py-2 pr-4 font-medium">Артикул</th>
                  <th className="py-2 pr-4 font-medium">Сумма</th>
                  <th className="py-2 pr-4 font-medium">Статус</th>
                  <th className="py-2 font-medium">Дата</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border">
                {history.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-3 text-xs text-slate-500">
                      Покупок по этой машине пока нет.
                    </td>
                  </tr>
                ) : (
                  history.map((p, i) => (
                    <tr key={`${p.order_id}-${i}`} className="hover:bg-surface-hover">
                      <td className="py-2 pr-4 text-slate-200">{p.part_name}</td>
                      <td className="py-2 pr-4 font-mono text-xs text-slate-400">
                        {p.article || "—"}
                      </td>
                      <td className="py-2 pr-4 text-slate-100">{formatMoney(p.total_price)}</td>
                      <td className="py-2 pr-4">
                        <StatusBadge status={p.status} />
                      </td>
                      <td className="py-2 text-xs text-slate-500">
                        {new Date(p.created_at).toLocaleDateString("ru-RU")}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
