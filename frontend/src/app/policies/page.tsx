"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { CompanyPolicies } from "@/lib/types";
import { ErrorBox, Loading, SectionHeader } from "@/components/ui";

function toLines(value: unknown): string {
  return Array.isArray(value) ? value.join("\n") : "";
}

function fromLines(value: string): string[] {
  return value
    .split(/[\n,;]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function toMarkups(value: unknown): string {
  if (typeof value !== "object" || value === null) return "";
  return Object.entries(value as Record<string, unknown>)
    .map(([k, v]) => `${k}: ${v}`)
    .join("\n");
}

function fromMarkups(value: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const line of value.split("\n")) {
    const idx = line.indexOf(":");
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    const num = parseFloat(line.slice(idx + 1).trim());
    if (key && !Number.isNaN(num)) out[key] = num;
  }
  return out;
}

function num(value: unknown): string {
  return value === null || value === undefined || value === "" ? "" : String(value);
}

function numOrNull(value: string): number | null {
  if (value.trim() === "") return null;
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

function Toggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 rounded-lg bg-surface px-3 py-2.5">
      <span className="text-sm text-slate-300">{label}</span>
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-current text-accent"
      />
    </label>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  hint,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  hint?: string;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-slate-500">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="input"
      />
      {hint ? <span className="mt-1 block text-[11px] text-slate-600">{hint}</span> : null}
    </label>
  );
}

function TextArea({
  label,
  value,
  onChange,
  hint,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-slate-500">{label}</span>
      <textarea
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        className="input resize-y font-mono text-xs"
      />
      {hint ? <span className="mt-1 block text-[11px] text-slate-600">{hint}</span> : null}
    </label>
  );
}

type Editable = {
  pricing: Record<string, unknown>;
  supplier: Record<string, unknown>;
  approval: Record<string, unknown>;
  sales: Record<string, unknown>;
  security: Record<string, unknown>;
};

export default function PoliciesPage() {
  const { data, loading, error, reload } = useApi<CompanyPolicies>("/company-policies");
  const [editable, setEditable] = useState<Editable | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    setEditable({
      pricing: { ...data.pricing },
      supplier: { ...data.supplier },
      approval: { ...data.approval },
      sales: { ...data.sales },
      security: { ...data.security },
    });
  }, [data]);

  function set(key: keyof Editable, field: string, value: unknown) {
    setEditable((prev) => {
      if (!prev) return prev;
      return { ...prev, [key]: { ...prev[key], [field]: value } };
    });
  }

  async function save() {
    if (!editable) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      await api.put<CompanyPolicies>("/company-policies", {
        pricing: editable.pricing,
        supplier: editable.supplier,
        approval: editable.approval,
        sales: editable.sales,
        security: editable.security,
      });
      setSaved(true);
      reload();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!editable) return null;

  const p = editable.pricing;
  const sp = editable.supplier;
  const ap = editable.approval;
  const sa = editable.sales;
  const sec = editable.security;

  return (
    <div>
      <SectionHeader
        title="Политики компании — как продают AI-сотрудники"
        action={
          <button className="btn-primary" onClick={save} disabled={saving}>
            {saving ? "Сохраняем…" : "Сохранить"}
          </button>
        }
      />
      <p className="mb-6 max-w-3xl text-xs text-slate-500">
        Business rules, по которым работают агенты. Отличие от PermissionEngine
        («можно ли действовать») — здесь решается «как именно компания продаёт».
        Поля, оставленные по умолчанию, берутся из встроенных дефолтов.
      </p>
      {saved ? (
        <div className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-300">
          Политики сохранены.
        </div>
      ) : null}
      {saveError ? <div className="mb-4"><ErrorBox message={saveError} /></div> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-4 text-sm font-medium text-slate-300">Цены (Pricing)</h2>
          <div className="space-y-4">
            <Field
              label="Минимальная маржа, %"
              type="number"
              value={num(p.min_margin_percent)}
              onChange={(v) => set("pricing", "min_margin_percent", numOrNull(v) ?? 0)}
              hint="Ниже этой маржи агент не продаёт (пол этажа над базовой наценкой)."
            />
            <Field
              label="Минимальная прибыль, ₽"
              type="number"
              value={num(p.min_profit)}
              onChange={(v) => set("pricing", "min_profit", numOrNull(v) ?? 0)}
            />
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">Округление цены</span>
              <select
                className="input"
                value={num(p.rounding)}
                onChange={(e) => set("pricing", "rounding", numOrNull(e.target.value) ?? 0.01)}
              >
                {["0.01", "1", "10", "50", "100"].map((s) => (
                  <option key={s} value={s}>
                    {s === "0.01" ? "До копейки" : `До ${s} ₽`}
                  </option>
                ))}
              </select>
            </label>
            <TextArea
              label="Наценки по поставщикам (slug: процент)"
              value={toMarkups(p.markups)}
              onChange={(v) => set("pricing", "markups", fromMarkups(v))}
              placeholder={"mock: 5\nrossko: 8"}
            />
            <div className="space-y-2">
              <Toggle
                label="Разрешить скидки"
                value={Boolean(p.allow_discounts)}
                onChange={(v) => set("pricing", "allow_discounts", v)}
              />
            </div>
            <Field
              label="Максимальная скидка, %"
              type="number"
              value={num(p.max_discount_percent)}
              onChange={(v) => set("pricing", "max_discount_percent", numOrNull(v) ?? 0)}
            />
          </div>
        </div>

        <div className="card">
          <h2 className="mb-4 text-sm font-medium text-slate-300">Поставщики (Supplier)</h2>
          <div className="space-y-4">
            <TextArea
              label="Приоритет поставщиков (slug, по одному на строку)"
              value={toLines(sp.priority)}
              onChange={(v) => set("supplier", "priority", fromLines(v))}
              hint="Чем выше в списке — тем выше приоритет."
            />
            <TextArea
              label="Запрещённые бренды"
              value={toLines(sp.blocked_brands)}
              onChange={(v) => set("supplier", "blocked_brands", fromLines(v))}
            />
            <TextArea
              label="Любимые бренды (показывать первыми)"
              value={toLines(sp.favorite_brands)}
              onChange={(v) => set("supplier", "favorite_brands", fromLines(v))}
            />
            <div className="grid grid-cols-3 gap-3">
              <Field
                label="Макс. срок, дней"
                type="number"
                value={num(sp.max_lead_days)}
                onChange={(v) => set("supplier", "max_lead_days", numOrNull(v))}
              />
              <Field
                label="Мин. рейтинг"
                type="number"
                value={num(sp.min_rating)}
                onChange={(v) => set("supplier", "min_rating", numOrNull(v) ?? 0)}
              />
              <Field
                label="Макс. вариантов"
                type="number"
                value={num(sp.max_variants)}
                onChange={(v) => set("supplier", "max_variants", numOrNull(v) ?? 5)}
              />
            </div>
          </div>
        </div>

        <div className="card">
          <h2 className="mb-4 text-sm font-medium text-slate-300">Согласования (Approval)</h2>
          <div className="space-y-4">
            <Field
              label="Автоотправка quote до суммы, ₽"
              type="number"
              value={num(ap.auto_approve_quote_amount)}
              onChange={(v) => set("approval", "auto_approve_quote_amount", numOrNull(v))}
              hint="Квоты не дороже этой суммы отправляются без менеджера (пусто = не ограничено суммой)."
            />
            <div className="grid grid-cols-2 gap-3">
              <Field
                label="Нужен менеджер от суммы, ₽"
                type="number"
                value={num(ap.manager_above_amount)}
                onChange={(v) => set("approval", "manager_above_amount", numOrNull(v))}
              />
              <Field
                label="Нужен владелец от суммы, ₽"
                type="number"
                value={num(ap.owner_above_amount)}
                onChange={(v) => set("approval", "owner_above_amount", numOrNull(v))}
              />
            </div>
            <TextArea
              label="Действия, требующие менеджера"
              value={toLines(ap.requires_manager)}
              onChange={(v) => set("approval", "requires_manager", fromLines(v))}
              placeholder={"send_customer_message\ngive_discount"}
            />
            <TextArea
              label="Действия, требующие владельца"
              value={toLines(ap.requires_owner)}
              onChange={(v) => set("approval", "requires_owner", fromLines(v))}
              placeholder={"create_order\nprocess_refund"}
            />
          </div>
        </div>

        <div className="card">
          <h2 className="mb-4 text-sm font-medium text-slate-300">Продажи (Sales)</h2>
          <div className="space-y-2">
            <Toggle
              label="Отправлять quote автоматически"
              value={Boolean(sa.auto_send_quote)}
              onChange={(v) => set("sales", "auto_send_quote", v)}
            />
            <Toggle
              label="Использовать эмодзи"
              value={Boolean(sa.use_emojis)}
              onChange={(v) => set("sales", "use_emojis", v)}
            />
            <Toggle
              label="Формальный стиль"
              value={Boolean(sa.formal_style)}
              onChange={(v) => set("sales", "formal_style", v)}
            />
            <Toggle
              label="Показывать аналоги"
              value={Boolean(sa.show_analogs)}
              onChange={(v) => set("sales", "show_analogs", v)}
            />
            <Toggle
              label="Показывать сроки поставки"
              value={Boolean(sa.show_lead_times)}
              onChange={(v) => set("sales", "show_lead_times", v)}
            />
            <Toggle
              label="Показывать остатки"
              value={Boolean(sa.show_stock)}
              onChange={(v) => set("sales", "show_stock", v)}
            />
          </div>
        </div>

        <div className="card lg:col-span-2">
          <h2 className="mb-4 text-sm font-medium text-slate-300">
            Безопасность (Security) — оверрайды PermissionEngine
          </h2>
          <TextArea
            label="Права на действия (action или action:resource → low/medium/high)"
            value={toLines(Object.entries(sec.permissions as Record<string, unknown>).map(([k, v]) => `${k}: ${v}`))}
            onChange={(v) => set("security", "permissions", fromLines(v).reduce<Record<string, string>>((acc, line) => {
              const idx = line.indexOf(":");
              if (idx !== -1) acc[line.slice(0, idx).trim()] = line.slice(idx + 1).trim().toUpperCase();
              return acc;
            }, {}))}
            hint="Пример: send_customer_message: low — агент отправляет сам; give_discount:quote: medium — через согласование."
            placeholder={"send_customer_message: low\ngive_discount:quote: medium"}
          />
        </div>
      </div>
    </div>
  );
}
