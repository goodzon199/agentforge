"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { ShadowComparison } from "@/lib/types";
import { StatusBadge } from "@/components/ui";

function MatchPill({ label, value }: { label: string; value: boolean | null }) {
  const cls =
    value === true
      ? "bg-emerald-500/15 text-emerald-400"
      : value === false
        ? "bg-rose-500/15 text-rose-400"
        : "bg-slate-500/15 text-slate-400";
  const text =
    value === true ? "совпало" : value === false ? "не совпало" : "нет данных";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {label}: {text}
    </span>
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
  partRequestId: string;
  comparison: ShadowComparison | null;
  onSubmitted: () => void;
};

export function ShadowPanel({ partRequestId, comparison, onSubmitted }: Props) {
  const [open, setOpen] = useState(false);
  const [vehicle, setVehicle] = useState("");
  const [part, setPart] = useState("");
  const [article, setArticle] = useState("");
  const [price, setPrice] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const done = comparison?.status === "completed";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/manager/shadow/submit", {
        part_request_id: partRequestId,
        vehicle,
        part,
        article,
        price: price ? Number(price) : null,
        reply,
      });
      setOpen(false);
      onSubmitted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка отправки");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 rounded-xl border border-violet-500/30 bg-violet-500/5 px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-violet-300">
            Shadow Mode
          </span>
          <StatusBadge status={comparison ? comparison.status : "pending"} />
        </div>
        <button
          type="button"
          className="text-xs text-violet-300 hover:underline"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Скрыть" : done ? "Сравнение" : "Сравнить с AI"}
        </button>
      </div>

      {comparison && (
        <div className="mt-2 grid gap-3 text-xs lg:grid-cols-2">
          <div className="rounded-lg bg-surface/60 p-3">
            <div className="mb-1 font-medium text-slate-400">AI (Agentos)</div>
            <div className="space-y-1 text-slate-200">
              <div>Деталь: {comparison.ai.part || "—"}</div>
              <div>Артикул: {comparison.ai.article || "—"}</div>
              <div>Авто: {comparison.ai.vehicle || "—"}</div>
              <div>Цена: {formatPrice(comparison.ai.price)}</div>
              {comparison.ai.answer ? (
                <div className="mt-1 rounded bg-surface p-2 text-slate-300">{comparison.ai.answer}</div>
              ) : null}
            </div>
          </div>
          <div className="rounded-lg bg-surface/60 p-3">
            <div className="mb-1 font-medium text-slate-400">Менеджер</div>
            <div className="space-y-1 text-slate-200">
              <div>Деталь: {comparison.manager.part || "—"}</div>
              <div>Артикул: {comparison.manager.article || "—"}</div>
              <div>Авто: {comparison.manager.vehicle || "—"}</div>
              <div>Цена: {formatPrice(comparison.manager.price)}</div>
              {comparison.manager.reply ? (
                <div className="mt-1 rounded bg-surface p-2 text-slate-300">{comparison.manager.reply}</div>
              ) : null}
            </div>
          </div>
        </div>
      )}

      {done && comparison ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <MatchPill label="Авто" value={comparison.result.vehicle_match} />
          <MatchPill label="Деталь" value={comparison.result.part_match} />
          <MatchPill label="OEM" value={comparison.result.oem_match} />
          <span className="inline-flex items-center rounded-full bg-surface px-2 py-0.5 text-[11px] font-medium text-slate-300">
            общих предложений: {comparison.result.offer_overlap}
          </span>
          <span className="inline-flex items-center rounded-full bg-surface px-2 py-0.5 text-[11px] font-medium text-slate-300">
            Δ цены: {comparison.result.price_delta !== null ? formatPrice(comparison.result.price_delta) : "—"}
          </span>
          <span className="inline-flex items-center rounded-full bg-surface px-2 py-0.5 text-[11px] font-medium text-slate-300">
            время: {comparison.result.time_seconds !== null ? `${comparison.result.time_seconds.toFixed(0)}с` : "—"}
          </span>
        </div>
      ) : null}

      {open && !done ? (
        <form onSubmit={submit} className="mt-3 grid gap-2 text-sm lg:grid-cols-2">
          <input className="input" placeholder="Автомобиль (как у клиента)" value={vehicle} onChange={(e) => setVehicle(e.target.value)} />
          <input className="input" placeholder="Деталь" value={part} onChange={(e) => setPart(e.target.value)} />
          <input className="input" placeholder="Артикул (OEM)" value={article} onChange={(e) => setArticle(e.target.value)} />
          <input className="input" placeholder="Цена, ₽" type="number" value={price} onChange={(e) => setPrice(e.target.value)} />
          <textarea
            className="input lg:col-span-2"
            placeholder="Ответ клиенту (отправится только от менеджера)"
            rows={2}
            value={reply}
            onChange={(e) => setReply(e.target.value)}
          />
          <div className="flex items-center gap-2 lg:col-span-2">
            <button type="submit" className="btn-primary" disabled={busy}>
              {busy ? "Отправляем…" : "Отправить клиенту и сравнить"}
            </button>
            {error ? <span className="text-xs text-rose-400">{error}</span> : null}
          </div>
        </form>
      ) : null}
    </div>
  );
}
